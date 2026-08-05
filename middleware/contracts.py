"""Immutable request and tool-call contracts shared by the middleware."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest
import json
import math
import time
from types import MappingProxyType
from typing import Any, Literal
import uuid


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


RiskLevel = Literal["R0", "R1", "R2"]
ApprovalLabel = Literal["APPROVE", "CANCEL", "UNCERTAIN"]


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("proposal arguments cannot contain non-finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("proposal arguments must contain only JSON values")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class PendingToolProposal:
    """Tamper-evident, immutable R1/R2 invocation awaiting approval."""

    proposal_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    risk_level: Literal["R1", "R2"]
    created_at: float
    expires_at: float
    proposal_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _required_string(self.proposal_id, "proposal_id"))
        object.__setattr__(self, "tool_name", _required_string(self.tool_name, "tool_name"))
        if self.risk_level not in ("R1", "R2"):
            raise ValueError("pending proposals require R1 or R2 risk")
        created_at = float(self.created_at)
        expires_at = float(self.expires_at)
        if not math.isfinite(created_at) or not math.isfinite(expires_at):
            raise ValueError("proposal timestamps must be finite")
        if expires_at != created_at + 300.0:
            raise ValueError("pending proposals must expire after exactly 300 seconds")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "arguments", _freeze_json(self.arguments))
        object.__setattr__(self, "proposal_hash", _required_string(self.proposal_hash, "proposal_hash"))

    @classmethod
    def create(
        cls,
        tool_name: str,
        arguments: Mapping[str, Any],
        risk_level: Literal["R1", "R2"],
        *,
        now: float | None = None,
        proposal_id: str | None = None,
    ) -> "PendingToolProposal":
        tool_name = _required_string(tool_name, "tool_name")
        if risk_level not in ("R1", "R2"):
            raise ValueError("pending proposals require R1 or R2 risk")
        if not isinstance(arguments, Mapping):
            raise ValueError("arguments must be an object")
        created_at = time.time() if now is None else float(now)
        expires_at = created_at + 300.0
        identifier = proposal_id or f"PROP-{uuid.uuid4().hex[:16].upper()}"
        identifier = _required_string(identifier, "proposal_id")
        frozen_arguments = _freeze_json(arguments)
        proposal_hash = cls._calculate_hash(
            identifier,
            tool_name,
            frozen_arguments,
            risk_level,
            created_at,
            expires_at,
        )
        return cls(
            identifier,
            tool_name,
            frozen_arguments,
            risk_level,
            created_at,
            expires_at,
            proposal_hash,
        )

    @staticmethod
    def _calculate_hash(
        proposal_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        risk_level: str,
        created_at: float,
        expires_at: float,
    ) -> str:
        canonical = json.dumps(
            {
                "proposal_id": proposal_id,
                "tool_name": tool_name,
                "arguments": _thaw_json(arguments),
                "risk_level": risk_level,
                "created_at": created_at,
                "expires_at": expires_at,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        expected = self._calculate_hash(
            self.proposal_id,
            self.tool_name,
            self.arguments,
            self.risk_level,
            self.created_at,
            self.expires_at,
        )
        return compare_digest(expected, self.proposal_hash)

    def is_expired(self, now: float | None = None) -> bool:
        checked_at = time.time() if now is None else float(now)
        return checked_at >= self.expires_at

    def tool_arguments(self) -> dict[str, Any]:
        return _thaw_json(self.arguments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "tool_name": self.tool_name,
            "arguments": self.tool_arguments(),
            "risk_level": self.risk_level,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "proposal_hash": self.proposal_hash,
        }


@dataclass(frozen=True)
class ApprovalClassification:
    decision: ApprovalLabel
    confidence: float


@dataclass(frozen=True)
class AgentRunResult:
    kind: Literal["respond", "clarify", "pending_approval", "limit_reached"]
    message: str
    decision_count: int
    tool_results: tuple[ToolExecutionResult, ...] = ()
    proposal: PendingToolProposal | None = None


@dataclass(frozen=True)
class ApprovalResolution:
    status: Literal["executed", "cancelled", "uncertain", "expired", "invalid"]
    classification: ApprovalClassification | None
    pending_proposal: PendingToolProposal | None
    execution_result: ToolExecutionResult | None = None
