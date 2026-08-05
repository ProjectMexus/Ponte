"""Channel-independent contracts for the Demo interaction core."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .contracts import ToolExecutionResult


def _required(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return deepcopy(dict(value))


@dataclass(frozen=True)
class EventEnvelope:
    """Routing envelope around one authoritative, modality-neutral event."""

    interaction_id: str
    session_id: str
    event: Mapping[str, Any]
    audit: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "interaction_id", _required(self.interaction_id, "interaction_id"))
        object.__setattr__(self, "session_id", _required(self.session_id, "session_id"))
        event = _mapping(self.event, "event")
        event_type = _required(event.get("type"), "event.type")
        event["type"] = event_type
        # These fields may arrive from transport adapters but are not domain input.
        event.pop("source", None)
        event.pop("language", None)
        event.pop("transcript", None)
        if event_type == "user_utterance":
            event["content"] = _required(event.get("content"), "event.content")
            if event.get("task_id") is not None:
                event["task_id"] = _required(event["task_id"], "event.task_id")
        object.__setattr__(self, "event", event)
        object.__setattr__(self, "audit", _mapping(self.audit, "audit"))

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "EventEnvelope":
        if not isinstance(value, Mapping):
            raise ValueError("request body must be an object")
        routing = value.get("routing")
        if not isinstance(routing, Mapping):
            raise ValueError("routing must be an object")
        return cls(
            routing.get("interaction_id"),
            routing.get("session_id"),
            value.get("event"),
            value.get("audit", {}),
        )


@dataclass(frozen=True)
class ConfirmationDecision:
    action_id: str
    task_id: str
    confirmation_id: str
    decision: str

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> "ConfirmationDecision":
        if not isinstance(event, Mapping):
            raise ValueError("confirmation event must be an object")
        decision = _required(event.get("decision"), "decision")
        if decision not in {"approve", "reject", "modify"}:
            raise ValueError("decision must be approve, reject, or modify")
        return cls(
            _required(event.get("action_id"), "action_id"),
            _required(event.get("task_id"), "task_id"),
            _required(event.get("confirmation_id"), "confirmation_id"),
            decision,
        )


@dataclass
class MedicalTask:
    task_id: str
    type: str = "medical_appointment"
    status: str = "awaiting_input"
    current_step: str = "select_service"
    facts: dict[str, Any] = field(default_factory=dict)
    pending_confirmation: dict[str, Any] | None = None
    recovery: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "type": self.type,
            "status": self.status,
            "current_step": self.current_step,
            "facts": deepcopy(self.facts),
            "pending_confirmation": deepcopy(self.pending_confirmation),
            "recovery": deepcopy(self.recovery),
            "receipt": deepcopy(self.receipt),
        }


@dataclass(frozen=True)
class CanonicalInteractionResult:
    interaction_id: str
    task: Mapping[str, Any]
    response_intent: str
    facts: Mapping[str, Any] = field(default_factory=dict)
    allowed_actions: list[Mapping[str, Any]] = field(default_factory=list)
    confirmation: Mapping[str, Any] | None = None
    recovery: Mapping[str, Any] | None = None
    receipt: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "task": deepcopy(dict(self.task)),
            "response_intent": self.response_intent,
            "facts": deepcopy(dict(self.facts)),
            "allowed_actions": deepcopy([dict(action) for action in self.allowed_actions]),
            "confirmation": deepcopy(dict(self.confirmation)) if self.confirmation is not None else None,
            "recovery": deepcopy(dict(self.recovery)) if self.recovery is not None else None,
            "receipt": deepcopy(dict(self.receipt)) if self.receipt is not None else None,
        }


class MedicalResultVerifier:
    """Verify business completion and extract only safe appointment facts."""

    @staticmethod
    def verify(result: ToolExecutionResult) -> dict[str, Any]:
        if not isinstance(result, ToolExecutionResult) or not result.ok:
            raise ValueError("medical execution did not succeed")
        payload = result.data
        if not isinstance(payload, Mapping):
            raise ValueError("medical backend response must be an object")
        appointment = payload.get("data")
        task = payload.get("task")
        receipt = payload.get("receipt")
        if not isinstance(appointment, Mapping) or not isinstance(task, Mapping) or not isinstance(receipt, Mapping):
            raise ValueError("medical backend response is missing appointment, task, or receipt")
        task_id = _required(task.get("id"), "task.id")
        receipt_id = _required(receipt.get("reference"), "receipt.reference")
        issued_at = _required(receipt.get("issued_at"), "receipt.issued_at")
        service = appointment.get("service")
        location = appointment.get("location")
        start = _required(appointment.get("start"), "appointment.start")
        if not isinstance(service, Mapping) or not isinstance(location, Mapping):
            raise ValueError("appointment service and location are required")
        service_id = _required(service.get("id"), "appointment.service.id")
        service_name = _required(service.get("display"), "appointment.service.display")
        location_name = _required(location.get("display"), "appointment.location.display")
        try:
            parsed_start = datetime.fromisoformat(start)
        except ValueError as error:
            raise ValueError("appointment.start is invalid") from error
        return {
            "task_id": task_id,
            "receipt_id": receipt_id,
            "issued_at": issued_at,
            "appointment": {
                "appointment_id": _required(appointment.get("id"), "appointment.id"),
                "service_id": service_id,
                "service": service_name,
                "date": parsed_start.date().isoformat(),
                "time": parsed_start.strftime("%H:%M"),
                "location": location_name,
                "status": _required(appointment.get("status"), "appointment.status"),
            },
        }


class ActionReceiptBuilder:
    """Build the canonical user-safe medical receipt from verified facts."""

    @staticmethod
    def build(task_id: str, verified: Mapping[str, Any]) -> dict[str, Any]:
        task_id = _required(task_id, "task_id")
        if not isinstance(verified, Mapping):
            raise ValueError("verified facts must be an object")
        receipt_id = _required(verified.get("receipt_id"), "receipt_id")
        issued_at = _required(verified.get("issued_at"), "issued_at")
        appointment = verified.get("appointment")
        if not isinstance(appointment, Mapping):
            raise ValueError("verified appointment facts are required")
        return {
            "receipt_id": receipt_id,
            "kind": "medical_appointment",
            "status": "completed",
            "issued_at": issued_at,
            "task_id": task_id,
            "appointment": {
                "service": _required(appointment.get("service"), "appointment.service"),
                "date": _required(appointment.get("date"), "appointment.date"),
                "time": _required(appointment.get("time"), "appointment.time"),
                "location": _required(appointment.get("location"), "appointment.location"),
                "status": _required(appointment.get("status"), "appointment.status"),
            },
        }
