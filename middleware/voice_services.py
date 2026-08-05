"""Optional cloud speech adapters and the registry-backed Ponte voice service.

The HTTP transport stays vendor-neutral.  This module is the small composition
layer used by the runnable stack: binary audio is transcribed, the isolated
registry agent handles the turn, and the reply is synthesized when configured.
Cloud settings are optional; tests can inject deterministic adapters.
"""

from __future__ import annotations

import html
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .agent import RegistryDrivenAgent
from .approval import ApprovalGate
from .contracts import PendingToolProposal, ToolExecutionResult
from .llm_transport import ChatCompletionError
from .voice import (
    SpeechPayload,
    SpeechToTextAdapter,
    TextToSpeechAdapter,
    UploadedAudio,
    VoiceProviderError,
    VoiceProviderSettings,
    VoiceTurn,
    VoiceTurnProvider,
    VoiceTurnResult,
)


def _multipart(fields: Mapping[str, str], filename: str, content_type: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"----PonteVoice{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend((f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(), str(value).encode(), b"\r\n"))
    chunks.extend((f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="file"; filename="{filename or "audio.webm"}"\r\n'.encode(), f"Content-Type: {content_type}\r\n\r\n".encode(), content, b"\r\n", f"--{boundary}--\r\n".encode()))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class OpenAICompatibleSpeechToText:
    """OpenAI-compatible transcription endpoint (also works with many proxies)."""

    def __init__(self, *, timeout: float = 20.0, opener: Any | None = None) -> None:
        self.timeout = timeout
        self.opener = opener or build_opener(ProxyHandler({}))

    def transcribe(self, audio: UploadedAudio, settings: VoiceProviderSettings) -> str:
        if not settings.stt_url or not settings.stt_model:
            raise VoiceProviderError("STT_NOT_CONFIGURED", "Speech recognition is not configured.")
        body, content_type = _multipart({"model": settings.stt_model, "language": "zh-HK"}, audio.filename or "audio.webm", audio.content_type, audio.content)
        headers = {"Content-Type": content_type, "Accept": "application/json"}
        if settings.stt_api_key:
            headers["Authorization"] = f"Bearer {settings.stt_api_key}"
        try:
            with self.opener.open(Request(settings.stt_url, data=body, headers=headers, method="POST"), timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
            raise VoiceProviderError("STT_UNAVAILABLE", "Speech recognition is temporarily unavailable.") from error
        text = payload.get("text") if isinstance(payload, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            raise VoiceProviderError("STT_EMPTY", "I could not hear a complete request.", status=422)
        return text.strip()


class OpenAICompatibleTextToSpeech:
    """JSON TTS endpoint returning browser-playable audio bytes."""

    def __init__(self, *, timeout: float = 20.0, opener: Any | None = None) -> None:
        self.timeout = timeout
        self.opener = opener or build_opener(ProxyHandler({}))

    def synthesize(self, text: str, settings: VoiceProviderSettings) -> SpeechPayload:
        if not settings.tts_url or not settings.tts_model:
            raise VoiceProviderError("TTS_NOT_CONFIGURED", "Speech synthesis is not configured.")
        body = json.dumps({"model": settings.tts_model, "voice": settings.tts_voice or "alloy", "input": text, "response_format": "mp3"}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "audio/mpeg"}
        if settings.tts_api_key:
            headers["Authorization"] = f"Bearer {settings.tts_api_key}"
        try:
            with self.opener.open(Request(settings.tts_url, data=body, headers=headers, method="POST"), timeout=self.timeout) as response:
                audio = response.read()
                content_type = response.headers.get_content_type() or "audio/mpeg"
        except (HTTPError, URLError, OSError) as error:
            raise VoiceProviderError("TTS_UNAVAILABLE", "Speech synthesis is temporarily unavailable.") from error
        return SpeechPayload(audio, content_type)


@dataclass
class _VoiceSession:
    history: list[dict[str, str]] = field(default_factory=list)
    pending: PendingToolProposal | None = None


def _receipt(result: ToolExecutionResult) -> dict[str, Any]:
    """Build a compact, escaped HTML artifact for the side drawer."""
    rows = [("Tool", result.tool_name), ("Request", result.request_id), ("Status", "Completed" if result.ok else "Failed")]
    if result.data:
        rows.append(("Result", json.dumps(dict(result.data), ensure_ascii=False, default=str)))
    table = "".join(f"<div class=\"receipt-row\"><span>{html.escape(k)}</span><strong>{html.escape(str(v))}</strong></div>" for k, v in rows)
    return {"kind": "html", "title": "Action receipt", "html": f"<article class=\"action-receipt\"><h3>Action receipt</h3>{table}</article>", "receipt_id": result.request_id}


class RegistryVoiceTurnProvider(VoiceTurnProvider):
    """Compose STT, isolated approval, all-registry agent, and optional TTS."""

    def __init__(self, agent: RegistryDrivenAgent, approval: ApprovalGate, *, context_factory: Callable[[VoiceTurn], Mapping[str, Any]], stt: SpeechToTextAdapter, tts: TextToSpeechAdapter | None = None, settings: VoiceProviderSettings | None = None) -> None:
        self.agent = agent
        self.approval = approval
        self.context_factory = context_factory
        self.stt = stt
        self.tts = tts
        self.settings = settings or VoiceProviderSettings.from_env()
        self._sessions: dict[str, _VoiceSession] = {}
        self._lock = Lock()
        self._busy_sessions: set[str] = set()

    def handle_turn(self, turn: VoiceTurn) -> VoiceTurnResult:
        transcript = self.stt.transcribe(turn.audio, self.settings)
        return self._handle_transcript(turn.session_id, transcript, self.context_factory(turn))

    def handle_transcript(self, session_id: str, transcript: str, context: Mapping[str, Any]) -> VoiceTurnResult:
        """Process browser STT fallback text through the same agent and approval path."""
        return self._handle_transcript(session_id, transcript, context)

    def _handle_transcript(self, session_id: str, transcript: str, context: Mapping[str, Any]) -> VoiceTurnResult:
        with self._lock:
            if session_id in self._busy_sessions:
                return VoiceTurnResult({"transcript": transcript, "assistant_message": "Please wait for the previous turn to finish."})
            self._busy_sessions.add(session_id)
        try:
            return self._handle_transcript_unlocked(session_id, transcript, context)
        finally:
            with self._lock:
                self._busy_sessions.discard(session_id)

    def _handle_transcript_unlocked(self, session_id: str, transcript: str, context: Mapping[str, Any]) -> VoiceTurnResult:
        session = self._sessions.setdefault(session_id, _VoiceSession())
        context = dict(context)
        receipt = None
        approval_payload = None
        if session.pending is not None:
            resolution = self.approval.resolve(transcript, session.pending, context=context)
            if resolution.status == "executed":
                session.pending = None
                message = "Done. The approved action is complete."
                receipt = _receipt(resolution.result) if resolution.result else None
            elif resolution.status == "cancelled":
                session.pending = None
                message = "Cancelled. Nothing was changed."
            elif resolution.status == "uncertain":
                message = "Please say approve or cancel."
                approval_payload = _approval(session.pending)
            else:
                session.pending = None
                message = "That approval expired. Please ask again."
        else:
            outcome = self.agent.run(transcript, history=session.history, context=context)
            message = outcome.message
            if outcome.proposal is not None:
                session.pending = outcome.proposal
                approval_payload = _approval(outcome.proposal)
            if outcome.tool_results:
                last = outcome.tool_results[-1]
                if last.ok and last.tool_name not in {"medical.list_departments", "medical.list_services", "medical.search_slots"}:
                    receipt = _receipt(last)
            session.history.extend(({"role": "user", "content": transcript}, {"role": "assistant", "content": message}))
        metadata: dict[str, Any] = {"transcript": transcript, "assistant_message": message}
        if approval_payload is not None:
            metadata["approval"] = approval_payload
        if receipt is not None:
            metadata["artifact"] = receipt
            metadata["receipt"] = receipt
        speech = None
        if self.tts is not None and message:
            try:
                speech = self.tts.synthesize(message, self.settings)
            except VoiceProviderError:
                speech = None
        return VoiceTurnResult(metadata, speech)


def _approval(proposal: PendingToolProposal) -> dict[str, Any]:
    return {"proposal_id": proposal.proposal_id, "tool_name": proposal.tool_name, "risk_level": proposal.risk_level, "summary": f"Approve {proposal.tool_name}?", "expires_at": proposal.expires_at, "digest": proposal.proposal_hash}
