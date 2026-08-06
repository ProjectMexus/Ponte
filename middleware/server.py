"""Stdlib HTTP bridge for the Ponte middleware."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Type
from urllib.parse import parse_qs, urlsplit

from MCP.registry import build_registry
from ponte_logging import log_event

from .contracts import InteractionActionRequest, InteractionRequest, ToolCall, ToolExecutionResult
from .config import load_dotenv
from .cash_sharing_workflow import CashSharingWorkflow
from .controller import InteractionController, LegacyInteractionContractError
from .diagnostics import DiagnosticCommandError
from .execution import ExecutionPipeline, McpExecutionStage
from .intent import IntentRecognizer
from .interaction_contracts import EventEnvelope
from .interaction_core import InteractionCore
from .medical_workflow import MedicalWorkflow
from .interaction_delivery import DeliveryOrchestrator
from .interaction_voice import CoreVoiceTurnProvider
from .mcp_client import McpStdioClient
from .session import SessionStore
from .task_manager.interpreter import TaskRecoveryInterpreter, build_task_recovery_interpreter
from .voice import (
    UnavailableVoiceTurnProvider,
    VoiceProviderError,
    VoiceSpeechStore,
    VoiceTurnProvider,
    VoiceProviderSettings,
    validate_voice_identifier,
)
from .voice_transport import (
    MAX_MULTIPART_BODY_BYTES,
    parse_voice_multipart,
    voice_turn_envelope,
)
from .voice_services import (
    OpenAICompatibleSpeechToText,
    OpenAICompatibleTextToSpeech,
)


class ClientRequestError(Exception):
    """An expected client error safe to expose as JSON."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class MiddlewareApplication:
    """Shared middleware dependencies used by every HTTP request."""

    def __init__(
        self,
        backend_url: str,
        patient_id: str,
        authorization: str,
        *,
        frontend_origins: tuple[str, ...] = (),
        mcp_client: McpStdioClient | None = None,
        mock_user_id: str = "USR-DEMO-001",
        intent_recognizer: IntentRecognizer | None = None,
        recovery_interpreter: TaskRecoveryInterpreter | None = None,
        voice_turn_provider: VoiceTurnProvider | None = None,
    ) -> None:
        self.backend_url = backend_url.rstrip("/")
        self.patient_id = patient_id
        self.authorization = authorization
        self.mock_user_id = mock_user_id
        self.frontend_origins = frontend_origins
        self._closed = False
        self.registry = build_registry()
        self.mcp_client = mcp_client or McpStdioClient(self.backend_url)
        self.mcp_client.start()
        self.pipeline = ExecutionPipeline([
            McpExecutionStage(self.registry, self.mcp_client),
        ])
        self.sessions = SessionStore()
        self.medical_workflow = MedicalWorkflow(
            self.pipeline,
            patient_id,
            authorization,
            mock_user_id=mock_user_id,
        )
        self.cash_workflow = CashSharingWorkflow(
            self.pipeline,
            patient_id,
            authorization,
            mock_user_id=mock_user_id,
        )
        self.interaction_core = InteractionCore(
            self.sessions,
            self.medical_workflow,
            intent_recognizer=intent_recognizer,
            cash_workflow=self.cash_workflow,
        )
        self.delivery_orchestrator = DeliveryOrchestrator()
        self.voice_turn_provider = voice_turn_provider or UnavailableVoiceTurnProvider()
        self.voice_speech = VoiceSpeechStore()
        self.controller = InteractionController(
            self.pipeline,
            self.sessions,
            patient_id,
            authorization,
            intent_recognizer=intent_recognizer,
            mock_user_id=mock_user_id,
            registry=self.registry,
            recovery_interpreter=recovery_interpreter or build_task_recovery_interpreter(),
        )

    def close(self) -> None:
        """Release the MCP child process owned by this application."""
        if self._closed:
            return
        self._closed = True
        self.mcp_client.close()

    def dispatch_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        step_id: str | None = None,
    ) -> ToolExecutionResult:
        return self.pipeline.dispatch(ToolCall(
            name=name,
            arguments=arguments,
            step_id=step_id or f"direct_{name.replace('.', '_')}",
        ))


def create_application(
    backend_url: str,
    patient_id: str,
    authorization: str,
    *,
    mcp_client: McpStdioClient | None = None,
    mock_user_id: str = "USR-DEMO-001",
    intent_recognizer: IntentRecognizer | None = None,
    recovery_interpreter: TaskRecoveryInterpreter | None = None,
    voice_turn_provider: VoiceTurnProvider | None = None,
) -> MiddlewareApplication:
    """Create one isolated middleware application with in-memory sessions."""

    load_dotenv()
    origins = _frontend_origins(os.environ.get("PONTE_FRONTEND_ORIGINS"))
    application = MiddlewareApplication(
        backend_url,
        patient_id,
        authorization,
        frontend_origins=origins,
        mcp_client=mcp_client,
        mock_user_id=mock_user_id,
        intent_recognizer=intent_recognizer,
        recovery_interpreter=recovery_interpreter,
        voice_turn_provider=voice_turn_provider,
    )
    if voice_turn_provider is None:
        configured = _configured_voice_provider(application)
        if configured is not None:
            application.voice_turn_provider = configured
    return application


class MiddlewareHTTPServer(ThreadingHTTPServer):
    """HTTP server that closes the application-owned MCP process."""

    def __init__(self, server_address: tuple[str, int], handler: Type[BaseHTTPRequestHandler], application: MiddlewareApplication):
        self.application = application
        super().__init__(server_address, handler)

    def server_close(self) -> None:
        self.application.close()
        super().server_close()


def create_http_server(
    host: str,
    port: int,
    application: MiddlewareApplication,
) -> ThreadingHTTPServer:
    """Create an HTTP server bound to one middleware application."""

    handler = _make_request_handler(application)
    return MiddlewareHTTPServer((host, port), handler, application)


def _make_request_handler(application: MiddlewareApplication) -> Type[BaseHTTPRequestHandler]:
    class MiddlewareRequestHandler(BaseHTTPRequestHandler):
        server_version = "PonteMiddleware/1.0"

        def _send_json(self, status: int, payload: dict[str, Any] | None) -> None:
            self._response_status = status
            try:
                raw = b"" if payload is None else json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            except Exception:
                self._response_status = 500
                raise
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if raw:
                self.wfile.write(raw)

        def _send_binary(self, status: int, content_type: str, content: bytes) -> None:
            self._response_status = status
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def _cors_headers(self) -> None:
            origin = self.headers.get("Origin")
            if origin and (origin in application.frontend_origins or "*" in application.frontend_origins):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _send_error(self, error: ClientRequestError) -> None:
            self._send_json(error.status, {
                "error": {
                    "code": error.code,
                    "message": error.message,
                },
            })

        def _body(self) -> dict[str, Any]:
            length_value = self.headers.get("Content-Length")
            if length_value is None:
                raise ClientRequestError(400, "INVALID_REQUEST", "request body 必須是 JSON object。")
            try:
                length = int(length_value)
            except ValueError as error:
                raise ClientRequestError(400, "INVALID_CONTENT_LENGTH", "Content-Length 不正確。") from error
            if length < 0:
                raise ClientRequestError(400, "INVALID_CONTENT_LENGTH", "Content-Length 不可以是負數。")
            raw = self.rfile.read(length)
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ClientRequestError(400, "INVALID_JSON", "request body 不是有效 JSON。") from error
            if not isinstance(value, dict):
                raise ClientRequestError(400, "INVALID_REQUEST", "request body 必須是 JSON object。")
            return value

        def _voice_turn(self):
            length_value = self.headers.get("Content-Length")
            if length_value is None:
                raise ClientRequestError(400, "INVALID_VOICE_REQUEST", "Content-Length is required")
            try:
                length = int(length_value)
            except ValueError as error:
                raise ClientRequestError(400, "INVALID_CONTENT_LENGTH", "Content-Length is invalid") from error
            if length < 0 or length > MAX_MULTIPART_BODY_BYTES:
                raise ClientRequestError(413, "VOICE_AUDIO_TOO_LARGE", "Voice upload exceeds the 4 MiB limit")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ClientRequestError(400, "INVALID_VOICE_REQUEST", "Voice upload ended unexpectedly")
            try:
                return parse_voice_multipart(self.headers.get("Content-Type"), raw)
            except ValueError as error:
                if "must not exceed" in str(error):
                    raise ClientRequestError(413, "VOICE_AUDIO_TOO_LARGE", "Voice upload exceeds the 4 MiB limit") from error
                raise ClientRequestError(400, "INVALID_VOICE_REQUEST", str(error)) from error

        def _speech(self, path: str) -> tuple[str, bytes]:
            match = _VOICE_SPEECH_PATH.fullmatch(path)
            if match is None:
                raise ClientRequestError(404, "NOT_FOUND", "API path was not found")
            session_values = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("session_id")
            if session_values is None or len(session_values) != 1:
                raise ClientRequestError(400, "INVALID_VOICE_REQUEST", "session_id query parameter is required once")
            try:
                session_id = validate_voice_identifier(session_values[0], "session_id")
                turn_id = validate_voice_identifier(match.group("turn_id"), "turn_id")
            except ValueError as error:
                raise ClientRequestError(400, "INVALID_VOICE_REQUEST", str(error)) from error
            speech = application.voice_speech.get(session_id, turn_id)
            if speech is None:
                raise ClientRequestError(404, "SPEECH_NOT_FOUND", "Speech is not available for this voice turn")
            return speech.content_type, speech.content

        def _handle(self) -> None:
            request_id = f"HTTP-MW-{uuid.uuid4().hex[:12].upper()}"
            path = urlsplit(self.path).path
            started_at = time.monotonic()
            self._response_status = 500
            log_event(
                "middleware",
                "request_start",
                method=self.command,
                path=path,
                request_id=request_id,
            )
            try:
                if self.command == "OPTIONS":
                    self._send_json(204, None)
                    return
                if self.command == "GET":
                    if _VOICE_SPEECH_PATH.fullmatch(path):
                        content_type, content = self._speech(path)
                        self._send_binary(200, content_type, content)
                        return
                    payload = self._get(path)
                    self._send_json(200, payload)
                    return
                if self.command == "POST":
                    if path == "/api/voice/turn":
                        turn = self._voice_turn()
                        result = application.voice_turn_provider.handle_turn(turn)
                        if result.speech is not None:
                            application.voice_speech.put(turn.session_id, turn.turn_id, result.speech)
                        self._send_json(200, voice_turn_envelope(turn, result))
                        return
                    payload = self._post(path, self._body())
                    self._send_json(200, payload)
                    return
                if path in _KNOWN_PATHS or _VOICE_SPEECH_PATH.fullmatch(path):
                    raise ClientRequestError(405, "METHOD_NOT_ALLOWED", "此 API 不支援目前的 HTTP method。")
                raise ClientRequestError(404, "NOT_FOUND", "找不到此 API 路徑。")
            except ClientRequestError as error:
                self._send_error(error)
            except VoiceProviderError as error:
                self._send_error(ClientRequestError(error.status, error.code, error.message))
            except ValueError as error:
                self._send_error(ClientRequestError(400, "INVALID_REQUEST", str(error)))
            except Exception:
                self._send_error(ClientRequestError(500, "MIDDLEWARE_ERROR", "Middleware 暫時不可用。"))
            finally:
                log_event(
                    "middleware",
                    "request_end",
                    method=self.command,
                    path=path,
                    request_id=request_id,
                    status=self._response_status,
                    latency_ms=(time.monotonic() - started_at) * 1000,
                )

        def _get(self, path: str) -> dict[str, Any]:
            if path == "/api/health":
                result = application.dispatch_tool(
                    "medical.list_departments",
                    {
                        "context": {
                            "authorization": application.authorization,
                            "mock_user_id": application.mock_user_id,
                            "accept_language": "zh-TW",
                            "request_id": _request_id(),
                        },
                        "input": {},
                    },
                    step_id="health",
                )
                response: dict[str, Any] = {
                    "status": "ok",
                    "backend_url": application.backend_url,
                    "tool_count": len(application.registry.names()),
                    "backend_reachable": result.ok,
                    "voice_ready": not isinstance(application.voice_turn_provider, UnavailableVoiceTurnProvider),
                }
                return response
            if path == "/api/mcp/tools":
                return {"tools": application.registry.list_mcp_tools()}
            raise ClientRequestError(404, "NOT_FOUND", "找不到此 API 路徑。")

        def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
            if path == "/api/mcp/tools/call":
                return self._call_tool(body)
            if path == "/api/interactions":
                try:
                    envelope = EventEnvelope.from_json(body)
                    canonical = application.interaction_core.handle(envelope)
                    return application.delivery_orchestrator.deliver(canonical)
                except ValueError as error:
                    raise ClientRequestError(400, "INVALID_INTERACTION", str(error)) from error
            if path == "/api/interactions/message":
                try:
                    request = InteractionRequest.from_json(body)
                except ValueError as error:
                    raise ClientRequestError(400, "INVALID_REQUEST", str(error)) from error
                if request.source == "voice":
                    raise ClientRequestError(
                        410,
                        "INTERACTION_EVENT_REQUIRED",
                        "Voice input must use /api/voice/turn or the normalized /api/interactions event contract.",
                    )
                try:
                    return application.controller.handle_message(request)
                except LegacyInteractionContractError as error:
                    raise ClientRequestError(400, error.code, error.message) from error
                except DiagnosticCommandError as error:
                    raise ClientRequestError(400, error.code, error.message) from error
            if path == "/api/interactions/action":
                try:
                    request = InteractionActionRequest.from_json(body)
                except ValueError as error:
                    raise ClientRequestError(400, "INVALID_REQUEST", str(error)) from error
                try:
                    return application.controller.handle_action(request)
                except LegacyInteractionContractError as error:
                    raise ClientRequestError(400, error.code, error.message) from error
                except ValueError as error:
                    raise ClientRequestError(400, "INVALID_ACTION", str(error)) from error
            raise ClientRequestError(404, "NOT_FOUND", "找不到此 API 路徑。")

        def _call_tool(self, body: dict[str, Any]) -> dict[str, Any]:
            name = body.get("name")
            arguments = body.get("arguments")
            if not isinstance(name, str) or not name.strip():
                raise ClientRequestError(400, "INVALID_TOOL_REQUEST", "name 必須是非空字串。")
            try:
                definition = application.registry.get(name)
            except KeyError as error:
                raise ClientRequestError(400, "UNKNOWN_TOOL", "Tool 不在固定 registry 內。") from error
            if definition.method.upper() != "GET":
                raise ClientRequestError(400, "CONFIRMATION_REQUIRED", "此 tool 必須經由前端確認 action。")
            if not isinstance(arguments, dict):
                raise ClientRequestError(400, "INVALID_TOOL_REQUEST", "arguments 必須是 JSON object。")
            safe_arguments = _safe_tool_arguments(arguments, application)
            result = application.dispatch_tool(name, safe_arguments)
            payload = result.to_dict()
            if result.error and result.error.get("code") == "INVALID_TOOL_ARGUMENTS":
                raise ClientRequestError(400, "INVALID_TOOL_ARGUMENTS", "Tool arguments 不符合固定 contract。")
            return payload

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def do_OPTIONS(self) -> None:
            self._handle()

        def do_PUT(self) -> None:
            self._handle()

        def do_PATCH(self) -> None:
            self._handle()

        def do_DELETE(self) -> None:
            self._handle()

        def do_HEAD(self) -> None:
            self._handle()

        def log_message(self, format: str, *args: Any) -> None:
            return

    return MiddlewareRequestHandler


_KNOWN_PATHS = frozenset({
    "/api/health",
    "/api/mcp/tools",
    "/api/mcp/tools/call",
    "/api/interactions/message",
    "/api/interactions/action",
    "/api/interactions",
    "/api/voice/turn",
})
_VOICE_SPEECH_PATH = re.compile(r"/api/voice/turn/(?P<turn_id>[A-Za-z0-9][A-Za-z0-9._-]{0,127})/speech\Z")


def _configured_voice_provider(application: MiddlewareApplication) -> VoiceTurnProvider | None:
    """Compose STT/TTS adapters around the shared InteractionCore."""
    settings = VoiceProviderSettings.from_env()
    if not settings.stt_url or not settings.stt_model:
        return None
    try:
        tts = OpenAICompatibleTextToSpeech() if settings.tts_url and settings.tts_model else None
        return CoreVoiceTurnProvider(
            application.interaction_core,
            application.delivery_orchestrator,
            stt=OpenAICompatibleSpeechToText(),
            tts=tts,
            settings=settings,
        )
    except (ValueError, TypeError, OSError):
        # Configuration errors leave the explicit 503 provider in place.
        return None


def _safe_tool_arguments(arguments: dict[str, Any], application: MiddlewareApplication) -> dict[str, Any]:
    if set(arguments) != {"context", "input"}:
        raise ClientRequestError(400, "INVALID_TOOL_REQUEST", "arguments 只允許 context 和 input。")
    context = arguments["context"]
    input_data = arguments["input"]
    if not isinstance(context, dict):
        raise ClientRequestError(400, "INVALID_TOOL_REQUEST", "arguments.context 必須是 JSON object。")
    if not isinstance(input_data, dict):
        raise ClientRequestError(400, "INVALID_TOOL_REQUEST", "arguments.input 必須是 JSON object。")
    safe_context = dict(context)
    safe_context["authorization"] = application.authorization
    safe_context["patient_id"] = application.patient_id
    safe_context["mock_user_id"] = application.mock_user_id
    safe_context["accept_language"] = "zh-TW"
    safe_context["request_id"] = _request_id()
    return {"context": safe_context, "input": dict(input_data)}


def _frontend_origins(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ("http://127.0.0.1:5173", "http://localhost:5173")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _request_id() -> str:
    return f"REQ-MW-{uuid.uuid4().hex[:12].upper()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Ponte's frontend-facing middleware bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8090, type=int)
    args = parser.parse_args()
    load_dotenv()
    application = create_application(
        os.environ.get("PONTE_BACKEND_URL", "http://127.0.0.1:8080"),
        os.environ.get("PONTE_PATIENT_ID", "PAT-DEMO-001"),
        os.environ.get("PONTE_AUTHORIZATION", "Bearer mock-user-token"),
        mock_user_id=os.environ.get("PONTE_MOCK_USER_ID", "USR-DEMO-001"),
    )
    server = create_http_server(args.host, args.port, application)
    print(f"Ponte middleware listening on http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        application.close()


if __name__ == "__main__":
    main()
