"""Stdlib HTTP bridge for the Ponte middleware."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Type
from urllib.parse import urlsplit

from MCP.registry import build_registry
from MCP.rest_adapter import RestAdapter

from .contracts import InteractionActionRequest, InteractionRequest, ToolCall, ToolExecutionResult
from .config import load_dotenv
from .controller import InteractionController
from .execution import DirectMcpExecutionStage, ExecutionPipeline
from .session import SessionStore


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
    ) -> None:
        self.backend_url = backend_url.rstrip("/")
        self.patient_id = patient_id
        self.authorization = authorization
        self.frontend_origins = frontend_origins
        self.registry = build_registry()
        self.adapter = RestAdapter(self.backend_url)
        self.pipeline = ExecutionPipeline([
            DirectMcpExecutionStage(self.registry, self.adapter),
        ])
        self.sessions = SessionStore()
        self.controller = InteractionController(
            self.pipeline,
            self.sessions,
            patient_id,
            authorization,
        )

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
) -> MiddlewareApplication:
    """Create one isolated middleware application with in-memory sessions."""

    load_dotenv()
    origins = _frontend_origins(os.environ.get("PONTE_FRONTEND_ORIGINS"))
    return MiddlewareApplication(
        backend_url,
        patient_id,
        authorization,
        frontend_origins=origins,
    )


def create_http_server(
    host: str,
    port: int,
    application: MiddlewareApplication,
) -> ThreadingHTTPServer:
    """Create an HTTP server bound to one middleware application."""

    handler = _make_request_handler(application)
    server = ThreadingHTTPServer((host, port), handler)
    server.application = application  # type: ignore[attr-defined]
    return server


def _make_request_handler(application: MiddlewareApplication) -> Type[BaseHTTPRequestHandler]:
    class MiddlewareRequestHandler(BaseHTTPRequestHandler):
        server_version = "PonteMiddleware/1.0"

        def _send_json(self, status: int, payload: dict[str, Any] | None) -> None:
            raw = b"" if payload is None else json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if raw:
                self.wfile.write(raw)

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

        def _handle(self) -> None:
            if self.command == "OPTIONS":
                self._send_json(204, None)
                return
            try:
                path = urlsplit(self.path).path
                if self.command == "GET":
                    payload = self._get(path)
                    self._send_json(200, payload)
                    return
                if self.command == "POST":
                    payload = self._post(path, self._body())
                    self._send_json(200, payload)
                    return
                if path in _KNOWN_PATHS:
                    raise ClientRequestError(405, "METHOD_NOT_ALLOWED", "此 API 不支援目前的 HTTP method。")
                raise ClientRequestError(404, "NOT_FOUND", "找不到此 API 路徑。")
            except ClientRequestError as error:
                self._send_error(error)
            except ValueError as error:
                self._send_error(ClientRequestError(400, "INVALID_REQUEST", str(error)))
            except Exception:
                self._send_error(ClientRequestError(500, "MIDDLEWARE_ERROR", "Middleware 暫時不可用。"))

        def _get(self, path: str) -> dict[str, Any]:
            if path == "/api/health":
                result = application.dispatch_tool(
                    "medical.list_departments",
                    {
                        "context": {
                            "authorization": application.authorization,
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
                }
                return response
            if path == "/api/mcp/tools":
                return {"tools": application.registry.list_mcp_tools()}
            raise ClientRequestError(404, "NOT_FOUND", "找不到此 API 路徑。")

        def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
            if path == "/api/mcp/tools/call":
                return self._call_tool(body)
            if path == "/api/interactions/message":
                try:
                    request = InteractionRequest.from_json(body)
                except ValueError as error:
                    raise ClientRequestError(400, "INVALID_REQUEST", str(error)) from error
                return application.controller.handle_message(request)
            if path == "/api/interactions/action":
                try:
                    request = InteractionActionRequest.from_json(body)
                except ValueError as error:
                    raise ClientRequestError(400, "INVALID_REQUEST", str(error)) from error
                try:
                    return application.controller.handle_action(request)
                except ValueError as error:
                    raise ClientRequestError(400, "INVALID_ACTION", str(error)) from error
            raise ClientRequestError(404, "NOT_FOUND", "找不到此 API 路徑。")

        def _call_tool(self, body: dict[str, Any]) -> dict[str, Any]:
            name = body.get("name")
            arguments = body.get("arguments")
            if not isinstance(name, str) or not name.strip():
                raise ClientRequestError(400, "INVALID_TOOL_REQUEST", "name 必須是非空字串。")
            try:
                application.registry.get(name)
            except KeyError as error:
                raise ClientRequestError(400, "UNKNOWN_TOOL", "Tool 不在固定 registry 內。") from error
            if name == "medical.create_appointment":
                raise ClientRequestError(400, "CONFIRMATION_REQUIRED", "medical.create_appointment 必須經由 confirm action。")
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
})


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


if __name__ == "__main__":
    main()
