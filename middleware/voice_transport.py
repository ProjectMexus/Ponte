"""Multipart parsing and HTTP-safe response shaping for voice turns."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from email import policy
from email.parser import BytesParser
from typing import Any
from urllib.parse import quote

from .voice import MAX_AUDIO_BYTES, UploadedAudio, VoiceTurn, VoiceTurnResult


# The limit bounds the in-memory MIME parser while leaving room for boundaries,
# field headers, and the two small string fields around a maximum-sized upload.
MAX_MULTIPART_BODY_BYTES = MAX_AUDIO_BYTES + 64 * 1024
_TEXT_FIELDS = frozenset({"session_id", "turn_id", "locale"})


def parse_voice_multipart(content_type: str | None, body: bytes) -> VoiceTurn:
    """Parse one strictly-shaped ``multipart/form-data`` voice request.

    ``email.parser`` is part of the Python standard library and remains
    available on Python 3.13, unlike the removed ``cgi`` module.
    """

    if not isinstance(body, bytes) or len(body) > MAX_MULTIPART_BODY_BYTES:
        raise ValueError(f"multipart request must not exceed {MAX_MULTIPART_BODY_BYTES} bytes")
    if not isinstance(content_type, str) or not content_type.strip():
        raise ValueError("Content-Type must be multipart/form-data")
    if "\r" in content_type or "\n" in content_type:
        raise ValueError("Content-Type is invalid")
    try:
        content_header = content_type.encode("ascii", "strict")
    except UnicodeEncodeError as error:
        raise ValueError("Content-Type is invalid") from error

    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_header + b"\r\nMIME-Version: 1.0\r\n\r\n" + body,
    )
    if message.get_content_type().casefold() != "multipart/form-data" or not message.is_multipart():
        raise ValueError("Content-Type must be multipart/form-data")
    if not message.get_boundary():
        raise ValueError("multipart boundary is required")

    text_values: dict[str, str] = {}
    audio: UploadedAudio | None = None
    for part in message.iter_parts():
        if part.is_multipart() or part.get_content_disposition() != "form-data":
            raise ValueError("multipart parts must use form-data disposition")
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str):
            raise ValueError("multipart part name is required")
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            raise ValueError(f"multipart field {name!r} is invalid")
        if name in _TEXT_FIELDS:
            if name in text_values:
                raise ValueError(f"multipart field {name!r} must appear once")
            if len(payload) > 256:
                raise ValueError(f"multipart field {name!r} is too long")
            try:
                text_values[name] = payload.decode("utf-8", "strict")
            except UnicodeDecodeError as error:
                raise ValueError(f"multipart field {name!r} must be UTF-8") from error
            continue
        if name != "audio":
            raise ValueError(f"unexpected multipart field: {name}")
        if audio is not None:
            raise ValueError("multipart field 'audio' must appear once")
        audio = UploadedAudio(
            content=payload,
            content_type=part.get_content_type(),
            filename=part.get_filename(),
        )

    missing = {"session_id", "turn_id"}.difference(text_values)
    if missing:
        raise ValueError(f"missing multipart field: {sorted(missing)[0]}")
    if audio is None:
        raise ValueError("missing multipart field: audio")
    return VoiceTurn(
        session_id=text_values["session_id"],
        turn_id=text_values["turn_id"],
        audio=audio,
        locale=text_values.get("locale", "zh-HK"),
    )


def voice_turn_envelope(turn: VoiceTurn, result: VoiceTurnResult) -> dict[str, Any]:
    """Build the public JSON response without leaking uploaded audio bytes."""

    speech = result.speech
    speech_metadata: dict[str, Any] = {"available": speech is not None}
    if speech is not None:
        speech_metadata.update({
            "content_type": speech.content_type,
            "byte_length": len(speech.content),
            "url": (
                f"/api/voice/turn/{quote(turn.turn_id, safe='')}"
                f"/speech?session_id={quote(turn.session_id, safe='')}"
            ),
        })
    result_metadata = deepcopy(dict(result.metadata))
    if "speech_audio" not in result_metadata:
        result_metadata["speech_audio"] = {
            "status": "ready" if speech is not None else "unavailable",
        }
    if speech is not None and isinstance(result_metadata.get("speech_audio"), dict):
        result_metadata["speech_audio"].setdefault("status", "ready")
        result_metadata["speech_audio"].setdefault(
            "url",
            f"/api/voice/turn/{quote(turn.turn_id, safe='')}"
            f"/speech?session_id={quote(turn.session_id, safe='')}",
        )
    return {
        "voice_turn": {
            "session_id": turn.session_id,
            "turn_id": turn.turn_id,
            "locale": turn.locale,
            "audio": {
                "content_type": turn.audio.content_type,
                "byte_length": len(turn.audio.content),
            },
            "speech": speech_metadata,
        },
        "result": result_metadata,
    }
