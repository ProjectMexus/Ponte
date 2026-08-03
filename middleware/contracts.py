"""Immutable request and tool-call contracts shared by the middleware."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _object(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return dict(value)


@dataclass(frozen=True)
class InteractionRequest:
    """A user message submitted to an interaction session."""

    session_id: str
    message: str
    source: Literal["text", "voice"] = "text"

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _required_string(self.session_id, "session_id"))
        object.__setattr__(self, "message", _required_string(self.message, "message"))
        if self.source not in ("text", "voice"):
            raise ValueError("source must be either 'text' or 'voice'")

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "InteractionRequest":
        if not isinstance(value, Mapping):
            raise ValueError("request body must be an object")
        return cls(
            session_id=value.get("session_id"),
            message=value.get("message"),
            source=value.get("source", "text"),
        )


@dataclass(frozen=True)
class InteractionActionRequest:
    """A deterministic action submitted to an interaction session."""

    session_id: str
    action: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _required_string(self.session_id, "session_id"))
        object.__setattr__(self, "action", _required_string(self.action, "action"))
        object.__setattr__(self, "payload", _object(self.payload, "payload"))

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "InteractionActionRequest":
        if not isinstance(value, Mapping):
            raise ValueError("request body must be an object")
        return cls(
            session_id=value.get("session_id"),
            action=value.get("action"),
            payload=value.get("payload", {}),
        )


@dataclass(frozen=True)
class ToolCall:
    """A fixed-registry tool invocation requested by the controller."""

    name: str
    arguments: Mapping[str, Any]
    step_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_string(self.name, "name"))
        object.__setattr__(self, "step_id", _required_string(self.step_id, "step_id"))
        object.__setattr__(self, "arguments", _object(self.arguments, "arguments"))


@dataclass(frozen=True)
class ToolExecutionResult:
    """Safe, serializable result returned by an execution pipeline."""

    tool_name: str
    step_id: str
    ok: bool
    request_id: str
    data: Mapping[str, Any] | None = None
    error: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_name", _required_string(self.tool_name, "tool_name"))
        object.__setattr__(self, "step_id", _required_string(self.step_id, "step_id"))
        object.__setattr__(self, "request_id", _required_string(self.request_id, "request_id"))
        if not isinstance(self.ok, bool):
            raise ValueError("ok must be a boolean")
        if self.data is not None:
            object.__setattr__(self, "data", _object(self.data, "data"))
        if self.error is not None:
            object.__setattr__(self, "error", _object(self.error, "error"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "step_id": self.step_id,
            "ok": self.ok,
            "request_id": self.request_id,
            "data": self.data,
            "error": self.error,
        }
