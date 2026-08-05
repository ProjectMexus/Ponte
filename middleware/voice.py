"""Safe transport contracts for optional voice-turn providers.

This module deliberately does not recognize intent, call an LLM, or choose a
speech service.  The HTTP bridge turns multipart input into :class:`VoiceTurn`
and delegates it to an injected provider.  A caller may then expose the
provider-produced speech through the session/turn scoped binary route.
"""

from __future__ import annotations

import re
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Protocol
from urllib.parse import urlsplit


MAX_AUDIO_BYTES = 4 * 1024 * 1024
"""Largest accepted audio file (four MiB)."""

ALLOWED_AUDIO_CONTENT_TYPES = frozenset({"audio/webm", "audio/ogg"})

# The values are emitted in a URL path/query string, and are also storage keys.
# Keep them compact and unambiguous instead of accepting arbitrary user strings.
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class VoiceProviderError(Exception):
    """A safe error raised by an injected voice provider."""

    def __init__(self, code: str, message: str, *, status: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class VoiceProviderSettings:
    """Cloud-adapter configuration, deliberately separate from HTTP transport.

    The settings do not select a vendor or make a network request.  An
    application integration can use these values to instantiate a provider
    adapter appropriate for its selected cloud service.
    """

    stt_url: str | None = None
    stt_api_key: str | None = None
    stt_model: str | None = None
    tts_url: str | None = None
    tts_api_key: str | None = None
    tts_model: str | None = None
    tts_voice: str | None = None

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> "VoiceProviderSettings":
        values = os.environ if environment is None else environment
        return cls(
            stt_url=_optional_http_url(values.get("PONTE_VOICE_STT_URL"), "PONTE_VOICE_STT_URL"),
            stt_api_key=_optional_value(values.get("PONTE_VOICE_STT_API_KEY")),
            stt_model=_optional_value(values.get("PONTE_VOICE_STT_MODEL")),
            tts_url=_optional_http_url(values.get("PONTE_VOICE_TTS_URL"), "PONTE_VOICE_TTS_URL"),
            tts_api_key=_optional_value(values.get("PONTE_VOICE_TTS_API_KEY")),
            tts_model=_optional_value(values.get("PONTE_VOICE_TTS_MODEL")),
            tts_voice=_optional_value(values.get("PONTE_VOICE_TTS_VOICE")),
        )


def _optional_value(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("voice provider environment values must be strings")
    normalized = value.strip()
    return normalized or None


def _optional_http_url(value: object, field_name: str) -> str | None:
    normalized = _optional_value(value)
    if normalized is None:
        return None
    parts = urlsplit(normalized)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"{field_name} must be an absolute http(s) URL")
    return normalized


def validate_voice_identifier(value: object, field_name: str) -> str:
    """Return a URL-safe session or turn identifier, or raise ``ValueError``."""

    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(
            f"{field_name} must be 1-128 characters of letters, digits, '.', '_' or '-'"
        )
    return value


@dataclass(frozen=True)
class UploadedAudio:
    """Validated binary audio supplied as the ``audio`` multipart form part."""

    content: bytes
    content_type: str
    filename: str | None = None

    def __post_init__(self) -> None:
        normalized_type = self.content_type.casefold()
        if normalized_type not in ALLOWED_AUDIO_CONTENT_TYPES:
            allowed = ", ".join(sorted(ALLOWED_AUDIO_CONTENT_TYPES))
            raise ValueError(f"audio content type must be one of: {allowed}")
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("audio must not be empty")
        if len(self.content) > MAX_AUDIO_BYTES:
            raise ValueError(f"audio must not exceed {MAX_AUDIO_BYTES} bytes")
        object.__setattr__(self, "content_type", normalized_type)
        if self.filename is not None and not isinstance(self.filename, str):
            raise ValueError("audio filename must be a string")


@dataclass(frozen=True)
class VoiceTurn:
    """One complete, validated uploaded voice turn."""

    session_id: str
    turn_id: str
    audio: UploadedAudio
    locale: str = "zh-HK"

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", validate_voice_identifier(self.session_id, "session_id"))
        object.__setattr__(self, "turn_id", validate_voice_identifier(self.turn_id, "turn_id"))
        if not isinstance(self.audio, UploadedAudio):
            raise ValueError("audio must be an UploadedAudio")
        if self.locale not in {"zh-HK", "en-US"}:
            raise ValueError("locale must be zh-HK or en-US")


@dataclass(frozen=True)
class SpeechPayload:
    """Binary speech returned by a provider for a voice turn."""

    content: bytes
    content_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("speech content must not be empty")
        if not isinstance(self.content_type, str) or not self.content_type.strip():
            raise ValueError("speech content_type must be a non-empty string")
        # Header injection protection.  The provider still chooses its actual
        # MIME type, because browser-compatible speech formats vary by service.
        if "\r" in self.content_type or "\n" in self.content_type:
            raise ValueError("speech content_type is invalid")
        object.__setattr__(self, "content_type", self.content_type.strip())


@dataclass(frozen=True)
class VoiceTurnResult:
    """Provider output with JSON-safe metadata and optional synthesized speech."""

    metadata: Mapping[str, Any] = field(default_factory=dict)
    speech: SpeechPayload | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, Mapping):
            raise ValueError("voice result metadata must be an object")
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.speech is not None and not isinstance(self.speech, SpeechPayload):
            raise ValueError("voice result speech must be a SpeechPayload")


class VoiceTurnProvider(Protocol):
    """Bridge from validated audio to application-specific voice handling."""

    def handle_turn(self, turn: VoiceTurn) -> VoiceTurnResult:
        """Return safe metadata and, optionally, synthesized speech for ``turn``."""


class SpeechToTextAdapter(Protocol):
    """Vendor adapter contract for cloud speech-to-text integration."""

    def transcribe(self, audio: UploadedAudio, settings: VoiceProviderSettings) -> str:
        """Return a non-empty transcript or raise :class:`VoiceProviderError`."""


class TextToSpeechAdapter(Protocol):
    """Vendor adapter contract for cloud text-to-speech integration."""

    def synthesize(self, text: str, settings: VoiceProviderSettings) -> SpeechPayload:
        """Return browser-ready speech bytes or raise :class:`VoiceProviderError`."""


class UnavailableVoiceTurnProvider:
    """Explicit default until an application wires ASR/agent/TTS services."""

    def handle_turn(self, turn: VoiceTurn) -> VoiceTurnResult:
        raise VoiceProviderError(
            "VOICE_PROVIDER_UNAVAILABLE",
            "Voice processing is not configured.",
            status=503,
        )


class VoiceSpeechStore:
    """Thread-safe concerns are owned by the server; this is a key-value facade.

    The minimal interface keeps voice providers free to decide how metadata is
    generated while ensuring only the exact session/turn pair can retrieve its
    synthesized bytes.
    """

    def __init__(self) -> None:
        self._speech: dict[tuple[str, str], SpeechPayload] = {}
        self._lock = Lock()

    def put(self, session_id: str, turn_id: str, speech: SpeechPayload) -> None:
        key = (
            validate_voice_identifier(session_id, "session_id"),
            validate_voice_identifier(turn_id, "turn_id"),
        )
        with self._lock:
            self._speech[key] = speech

    def get(self, session_id: str, turn_id: str) -> SpeechPayload | None:
        key = (
            validate_voice_identifier(session_id, "session_id"),
            validate_voice_identifier(turn_id, "turn_id"),
        )
        with self._lock:
            return self._speech.get(key)
