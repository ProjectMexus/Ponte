"""Safe, shared terminal logging for Ponte services."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import sys
from collections.abc import Mapping
from urllib.parse import urlsplit


__all__ = ["endpoint_label", "log_debug_event", "log_event"]


_LOGGER = logging.getLogger("ponte")
_SUPPORTED_COMPONENTS = frozenset({"frontend", "middleware", "llm", "mcp", "backend"})
_SUPPORTED_FIELDS = frozenset(
    {
        "request_id",
        "model",
        "endpoint",
        "message_count",
        "message_chars",
        "intent",
        "confidence",
        "latency_ms",
        "source",
        "fallback_reason",
        "method",
        "path",
        "status",
        "bytes",
        "operation",
        "tool",
        "input_keys",
        "outcome",
        "error_code",
        "error_type",
    }
)
_DEBUG_FIELDS = frozenset(
    {
        "request_id",
        "model",
        "endpoint",
        "prompt",
        "response",
        "request",
        "result",
        "intent",
        "confidence",
        "latency_ms",
        "operation",
        "tool",
        "outcome",
        "error_code",
        "error_type",
    }
)
_DEBUG_CREDENTIAL_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set_cookie",
        "api_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "password",
        "secret",
        "token",
    }
)
_HANDLER_MARKER = "_ponte_terminal_handler"
_MAX_STRING_LENGTH = 120
_MISSING = object()
_UUID_SEGMENT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_UPPERCASE_IDENTIFIER_SEGMENT = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)+$")
_BEARER_TEXT = re.compile(r'''(?i)\bBearer\s+[^\s,;}\]"']+''')
_DEBUG_CREDENTIAL_KEY_PATTERN = (
    r"(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|secret|token|cookie|set[-_]?cookie)"
)
_HEADER_CREDENTIAL_TEXT = re.compile(
    r'''(?ix)
    (?P<prefix>
        (?<![\w-])
        (?:authorization|cookie|set[-_]?cookie)
        \s*[:=]\s*
    )
    (?P<value>[^\r\n]*)
    '''
)
_TOKEN_ASSIGNMENT_TEXT = re.compile(
    rf'''(?ix)
    (?P<prefix>
        (?<![\w-])
        (?:\\?["'])?
        {_DEBUG_CREDENTIAL_KEY_PATTERN}
        (?:\\?["'])?
        \s*[:=]\s*
    )
    (?:
        "(?:\\.|[^"\\])*"
        | '(?:\\.|[^'\\])*'
        | [^\s,;}}\]"']+
    )'''
)


class _PonteStreamHandler(logging.StreamHandler):
    """A stderr handler that follows the current process stderr stream."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)

    def format(self, record: logging.LogRecord) -> str:
        # The component is included in the message as well as in ``extra`` so
        # unittest.assertLogs captures the same useful prefix. Strip the
        # message copy for this handler so the terminal line has one prefix.
        rendered_record = copy.copy(record)
        component = getattr(rendered_record, "component", "")
        prefix = f"[{component}] "
        if isinstance(rendered_record.msg, str) and rendered_record.msg.startswith(prefix):
            rendered_record.msg = rendered_record.msg[len(prefix) :]
            rendered_record.args = ()
        return super().format(rendered_record)


def _level_from_environment() -> int:
    level_name = os.environ.get("PONTE_LOG_LEVEL", "INFO").strip().upper()
    level = logging._nameToLevel.get(level_name, logging.INFO)
    return level if isinstance(level, int) else logging.INFO


def _ensure_logger(level: int) -> None:
    _LOGGER.setLevel(level)
    _LOGGER.propagate = False

    ponte_handlers = [
        handler
        for handler in _LOGGER.handlers
        if getattr(handler, _HANDLER_MARKER, False)
    ]
    if ponte_handlers:
        for duplicate in ponte_handlers[1:]:
            _LOGGER.removeHandler(duplicate)
        return

    handler = _PonteStreamHandler()
    setattr(handler, _HANDLER_MARKER, True)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(component)s] %(message)s"
        )
    )
    _LOGGER.addHandler(handler)


def _safe_scalar(value: object) -> str | object:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)[:_MAX_STRING_LENGTH]
    if isinstance(value, float):
        return format(value, ".6f").rstrip("0").rstrip(".")[:_MAX_STRING_LENGTH]
    if isinstance(value, str):
        return " ".join(value.split())[:_MAX_STRING_LENGTH]
    return _MISSING


def _path_label(value: object) -> str | object:
    if value is None:
        return "none"
    if not isinstance(value, str):
        return _MISSING
    try:
        segments = urlsplit(value).path.split("/")
        safe_segments: list[str] = []
        for index, segment in enumerate(segments):
            if (
                segment
                and (
                    index > 4
                    or "%" in segment
                    or segment.isdigit()
                    or _UUID_SEGMENT.fullmatch(segment)
                    or _UPPERCASE_IDENTIFIER_SEGMENT.fullmatch(segment)
                )
            ):
                safe_segments.append(":id")
            else:
                safe_segments.append(" ".join(segment.split()))
        return "/".join(safe_segments)[:_MAX_STRING_LENGTH]
    except Exception:
        return _MISSING


def endpoint_label(url: str) -> str:
    """Return only the endpoint host and path, excluding query and fragment."""
    if url is None:
        return "none"
    if not isinstance(url, str):
        return ""
    try:
        parsed = urlsplit(url)
        if parsed.netloc:
            host = parsed.hostname or ""
            try:
                port = f":{parsed.port}" if parsed.port is not None else ""
            except ValueError:
                port = ""
            return f"{host}{port}{parsed.path}"[:_MAX_STRING_LENGTH]
        return parsed.path[:_MAX_STRING_LENGTH]
    except Exception:
        return ""


def _is_debug_credential_key(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = re.sub(r"[-_]+", "_", value.strip().lower())
    if normalized in _DEBUG_CREDENTIAL_KEYS:
        return True
    return normalized.endswith(
        (
            "_access_token",
            "_api_key",
            "_authorization",
            "_client_secret",
            "_cookie",
            "_password",
            "_refresh_token",
            "_secret",
            "_token",
        )
    )


def _redact_debug_text(value: str) -> str:
    configured_key = os.environ.get("PONTE_LLM_API_KEY", "")
    if configured_key:
        value = value.replace(configured_key, "<redacted>")
    value = _HEADER_CREDENTIAL_TEXT.sub(r"\g<prefix><redacted>", value)
    value = _BEARER_TEXT.sub("Bearer <redacted>", value)
    return _TOKEN_ASSIGNMENT_TEXT.sub(r"\g<prefix><redacted>", value)


def _redact_debug_value(value: object) -> object:
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key, nested_value in value.items():
            try:
                key_text = key if isinstance(key, str) else str(key)
            except Exception:
                key_text = "<unserializable>"
            if _is_debug_credential_key(key_text):
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = _redact_debug_value(nested_value)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact_debug_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_debug_text(value)
    return "<unserializable>"


def log_debug_event(component: str, event: str, **fields: object) -> None:
    """Emit structured DEBUG content without allowing logging to affect callers."""
    try:
        if component not in _SUPPORTED_COMPONENTS or not isinstance(event, str):
            return

        event_text = _safe_scalar(event)
        if event_text is _MISSING:
            return

        _ensure_logger(_level_from_environment())
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return

        debug_fields: list[str] = []
        for name, value in fields.items():
            if name not in _DEBUG_FIELDS:
                continue
            redacted_value = _redact_debug_value(value)
            serialized_value = json.dumps(
                redacted_value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            debug_fields.append(f"{name}={serialized_value}")

        message = f"[{component}] {event_text}"
        if debug_fields:
            message += " " + " ".join(debug_fields)

        _LOGGER.debug(message, extra={"component": component})
    except Exception:
        return


def log_event(component: str, event: str, **fields: object) -> None:
    """Emit a safe structured event without allowing logging to affect callers."""
    try:
        if component not in _SUPPORTED_COMPONENTS or not isinstance(event, str):
            return

        event_text = _safe_scalar(event)
        if event_text is _MISSING:
            return

        safe_fields: list[str] = []
        for name, value in fields.items():
            if name not in _SUPPORTED_FIELDS:
                continue
            if name == "endpoint":
                safe_value = endpoint_label(value) if isinstance(value, str) else _safe_scalar(value)
            elif name == "path":
                safe_value = _path_label(value)
            else:
                safe_value = _safe_scalar(value)
            if safe_value is _MISSING:
                continue
            safe_fields.append(f"{name}={safe_value}")

        message = f"[{component}] {event_text}"
        if safe_fields:
            message += " " + " ".join(safe_fields)

        _ensure_logger(_level_from_environment())
        _LOGGER.info(message, extra={"component": component})
    except Exception:
        return
