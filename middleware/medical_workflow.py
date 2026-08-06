"""Medical appointment workflow independent of interaction routing and sessions."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python builds without zoneinfo data
    ZoneInfo = None  # type: ignore[assignment]

from .contracts import ToolCall, ToolExecutionResult
from .execution import ExecutionPipeline
from .intent import IntentDecision
from .interaction_contracts import (
    CanonicalInteractionResult,
    ConfirmationDecision,
    EventEnvelope,
    InteractionTask,
)


WorkflowResult = tuple[dict[str, Any], CanonicalInteractionResult, list[dict[str, Any]]]


class MedicalWorkflow:
    """Own medical task transitions and execution while callers own persistence."""

    def __init__(
        self,
        pipeline: ExecutionPipeline,
        patient_id: str,
        authorization: str,
        *,
        mock_user_id: str = "USR-DEMO-001",
    ) -> None:
        self.pipeline = pipeline
        self.patient_id = _required(patient_id, "patient_id")
        self.authorization = _required(authorization, "authorization")
        self.mock_user_id = _required(mock_user_id, "mock_user_id")
        self._retry_calls: dict[str, dict[str, Any]] = {}

    def start(self, envelope: EventEnvelope, intent: IntentDecision) -> WorkflowResult:
        """Start one medical workflow from a classified user utterance."""
        _require_envelope(envelope)
        if envelope.event.get("type") != "user_utterance":
            raise ValueError("medical workflow must start with a user_utterance")
        if not isinstance(intent, IntentDecision) or not intent.is_medical:
            raise ValueError("medical workflow received a non-medical intent")

        task = InteractionTask(
            task_id=_identifier("TASK"),
            type="medical_appointment",
            status="awaiting_input",
            current_step="select_service",
        ).to_dict()
        logs: list[dict[str, Any]] = []
        self._retry_calls.pop(envelope.session_id, None)
        self._log(logs, "user_utterance", {"content": envelope.event["content"]})

        if intent.is_medical_query:
            result = self._dispatch(
                logs,
                "medical.get_my_appointments",
                "load_appointments",
                {},
                session_id=envelope.session_id,
            )
            if not result.ok:
                return self._tool_recovery(task, envelope, result, "load_appointments", logs)
            try:
                appointments = _data_list(result, "appointments")
            except ValueError:
                return self._invalid_backend_recovery(task, envelope, "load_appointments", logs)
            task["facts"] = {"appointments": appointments}
            task["status"] = "completed"
            task["current_step"] = "complete"
            self._log(logs, "execution_completed")
            return self._outcome(task, envelope, "appointment_list", logs)

        result = self._dispatch(
            logs,
            "medical.list_appointment_services",
            "load_services",
            {},
            session_id=envelope.session_id,
        )
        if not result.ok:
            return self._tool_recovery(task, envelope, result, "load_services", logs)
        try:
            services = _data_list(result, "services")
        except ValueError:
            return self._invalid_backend_recovery(task, envelope, "load_services", logs)
        task["facts"] = {"services": services}
        task["status"] = "awaiting_input"
        task["current_step"] = "select_service"
        self._log(logs, "service_selected", {"count": len(services), "event": "catalog_loaded"})
        return self._outcome(task, envelope, "select_service", logs)

    def handle(self, task_dict: dict[str, Any], envelope: EventEnvelope) -> WorkflowResult:
        """Advance an existing medical task and return its new state, result, and logs."""
        _require_envelope(envelope)
        task = _copy_task(task_dict)
        event_type = envelope.event.get("type")
        logs: list[dict[str, Any]] = []
        if event_type == "user_utterance":
            if task.get("status") in {"completed", "cancelled", "failed"}:
                raise ValueError("terminal medical task cannot accept a follow-up utterance")
            return self._outcome(task, envelope, _pending_response_intent(task), logs)
        if event_type == "service_selected":
            return self._service_selected(task, envelope, logs)
        if event_type == "slot_selected":
            return self._slot_selected(task, envelope, logs)
        if event_type == "confirmation_decision":
            return self._confirmation_decision(task, envelope, logs)
        if event_type == "recovery_action":
            return self._recovery_action(task, envelope, logs)
        if event_type == "cancel_task":
            return self._cancel(task, envelope, logs)
        raise ValueError(f"unsupported medical workflow event: {event_type}")

    def _service_selected(
        self, task: dict[str, Any], envelope: EventEnvelope, logs: list[dict[str, Any]]
    ) -> WorkflowResult:
        self._require_action_target(task, envelope.event)
        service_id = _required(envelope.event.get("service_id"), "service_id")
        date_from = _required(envelope.event.get("date_from"), "date_from")
        date_to = _required(envelope.event.get("date_to"), "date_to")
        services = task["facts"].get("services", [])
        service = next(
            (item for item in services if isinstance(item, Mapping) and item.get("id") == service_id),
            None,
        )
        if not isinstance(service, Mapping):
            raise ValueError("service_id is not one of the server-provided services")
        result = self._dispatch(
            logs,
            "medical.search_appointment_slots",
            "search_slots",
            {"service_id": service_id, "date_from": date_from, "date_to": date_to},
            session_id=envelope.session_id,
        )
        if not result.ok:
            return self._tool_recovery(task, envelope, result, "search_slots", logs)
        try:
            slots = _data_list(result, "slots")
        except ValueError:
            return self._invalid_backend_recovery(task, envelope, "search_slots", logs)
        task["facts"].update({
            "service_id": service_id,
            "service": _safe_service(service),
            "date_from": date_from,
            "date_to": date_to,
            "slots": slots,
        })
        if service.get("requires_referral"):
            task["facts"]["referring_appointment_id"] = "APT-REF-DEMO-001"
        task["status"] = "awaiting_input"
        task["current_step"] = "select_slot"
        task["recovery"] = None
        self._log(logs, "service_selected", {"service_id": service_id})
        return self._outcome(task, envelope, "select_slot", logs)

    def _slot_selected(
        self, task: dict[str, Any], envelope: EventEnvelope, logs: list[dict[str, Any]]
    ) -> WorkflowResult:
        self._require_action_target(task, envelope.event)
        slot_id = _required(envelope.event.get("slot_id"), "slot_id")
        slots = task["facts"].get("slots", [])
        slot = next(
            (item for item in slots if isinstance(item, Mapping) and item.get("id") == slot_id),
            None,
        )
        if not isinstance(slot, Mapping):
            raise ValueError("slot_id is not one of the server-provided slots")
        confirmation_id = _identifier("CONF")
        task["facts"]["slot_id"] = slot_id
        task["facts"]["selected_slot"] = _safe_slot(slot)
        task["pending_confirmation"] = {"confirmation_id": confirmation_id, "status": "pending"}
        task["status"] = "awaiting_confirmation"
        task["current_step"] = "confirm_appointment"
        task["recovery"] = None
        self._log(logs, "slot_selected", {"slot_id": slot_id})
        self._log(logs, "confirmation_requested", {"confirmation_id": confirmation_id})
        return self._outcome(task, envelope, "request_confirmation", logs)

    def _confirmation_decision(
        self, task: dict[str, Any], envelope: EventEnvelope, logs: list[dict[str, Any]]
    ) -> WorkflowResult:
        self._require_action_target(task, envelope.event)
        decision = ConfirmationDecision.from_event(envelope.event)
        pending = task.get("pending_confirmation")
        if not isinstance(pending, Mapping) or pending.get("confirmation_id") != decision.confirmation_id:
            raise ValueError("confirmation_id does not match the active task")
        if pending.get("status") != "pending":
            return self._outcome(task, envelope, _response_intent(task), logs)
        if decision.decision == "reject":
            task["pending_confirmation"]["status"] = "rejected"
            task["status"] = "cancelled"
            task["current_step"] = "cancelled"
            self._log(logs, "confirmation_decision", {"decision": "reject"})
            return self._outcome(task, envelope, "cancelled", logs)
        if decision.decision == "modify":
            task["pending_confirmation"]["status"] = "modified"
            task["status"] = "awaiting_input"
            task["current_step"] = "select_service"
            task["recovery"] = None
            task["facts"].pop("slot_id", None)
            task["facts"].pop("selected_slot", None)
            self._log(logs, "confirmation_decision", {"decision": "modify"})
            return self._outcome(task, envelope, "select_service", logs)

        task["pending_confirmation"]["status"] = "approved"
        task["status"] = "executing"
        task["current_step"] = "create_appointment"
        self._log(logs, "confirmation_decision", {"decision": "approve"})
        create_input = {
            "patient_id": self.patient_id,
            "service_id": _required(task["facts"].get("service_id"), "service_id"),
            "slot_id": _required(task["facts"].get("slot_id"), "slot_id"),
            "consent": True,
        }
        referral_id = task["facts"].get("referring_appointment_id")
        if isinstance(referral_id, str) and referral_id.strip():
            create_input["referring_appointment_id"] = referral_id.strip()
        result = self._dispatch(
            logs,
            "medical.create_appointment",
            "create_appointment",
            create_input,
            idempotency_key=decision.confirmation_id,
            session_id=envelope.session_id,
        )
        if not result.ok:
            return self._tool_recovery(task, envelope, result, "create_appointment", logs)
        return self._complete_appointment(task, envelope, result, logs)

    def _recovery_action(
        self, task: dict[str, Any], envelope: EventEnvelope, logs: list[dict[str, Any]]
    ) -> WorkflowResult:
        self._require_action_target(task, envelope.event)
        action = _required(envelope.event.get("action"), "action")
        if action == "cancel":
            return self._cancel(task, envelope, logs)
        if action == "human_help":
            task["status"] = "awaiting_input"
            task["current_step"] = "human_help"
            task["recovery"] = {"reason": "human_help_requested", "allowed_actions": ["cancel"]}
            return self._outcome(task, envelope, "recovery", logs)
        if action != "retry":
            raise ValueError("recovery action must be retry, human_help, or cancel")
        recovery = task.get("recovery")
        retry_call = self._retry_calls.get(envelope.session_id)
        if not isinstance(recovery, Mapping) or not isinstance(retry_call, Mapping):
            raise ValueError("no retryable recovery is available")
        result = self._dispatch(
            logs,
            _required(retry_call.get("name"), "retry tool"),
            _required(retry_call.get("step_id"), "retry step"),
            retry_call.get("input", {}),
            idempotency_key=retry_call.get("idempotency_key"),
            session_id=envelope.session_id,
        )
        step = _required(retry_call.get("step_id"), "retry step")
        if not result.ok:
            return self._tool_recovery(task, envelope, result, step, logs)
        if step == "load_appointments":
            try:
                task["facts"] = {"appointments": _data_list(result, "appointments")}
            except ValueError:
                return self._invalid_backend_recovery(task, envelope, step, logs)
            task["status"] = "completed"
            task["current_step"] = "complete"
            task["recovery"] = None
            self._log(logs, "execution_completed")
            return self._outcome(task, envelope, "appointment_list", logs)
        if step == "load_services":
            try:
                task["facts"] = {"services": _data_list(result, "services")}
            except ValueError:
                return self._invalid_backend_recovery(task, envelope, step, logs)
            task["status"] = "awaiting_input"
            task["current_step"] = "select_service"
            task["recovery"] = None
            return self._outcome(task, envelope, "select_service", logs)
        if step == "search_slots":
            try:
                task["facts"]["slots"] = _data_list(result, "slots")
            except ValueError:
                return self._invalid_backend_recovery(task, envelope, step, logs)
            task["status"] = "awaiting_input"
            task["current_step"] = "select_slot"
            task["recovery"] = None
            return self._outcome(task, envelope, "select_slot", logs)
        if step == "create_appointment":
            return self._complete_appointment(task, envelope, result, logs)
        raise ValueError("no retryable recovery is available")

    def _complete_appointment(
        self,
        task: dict[str, Any],
        envelope: EventEnvelope,
        result: ToolExecutionResult,
        logs: list[dict[str, Any]],
    ) -> WorkflowResult:
        try:
            verified = _verify_medical_result(result)
            receipt = _build_action_receipt(task["task_id"], verified)
        except ValueError:
            return self._invalid_backend_recovery(task, envelope, "create_appointment", logs)
        task["facts"]["appointment"] = deepcopy(verified["appointment"])
        task["receipt"] = receipt
        task["status"] = "completed"
        task["current_step"] = "complete"
        task["recovery"] = None
        self._log(logs, "execution_completed", {"receipt_id": receipt["receipt_id"]})
        self._log(logs, "receipt_created", {"receipt_id": receipt["receipt_id"]})
        return self._outcome(task, envelope, "completed", logs)

    def _cancel(
        self, task: dict[str, Any], envelope: EventEnvelope, logs: list[dict[str, Any]]
    ) -> WorkflowResult:
        self._require_action_target(task, envelope.event)
        pending = task.get("pending_confirmation")
        if isinstance(pending, dict) and pending.get("status") == "pending":
            pending["status"] = "rejected"
        task["status"] = "cancelled"
        task["current_step"] = "cancelled"
        task["recovery"] = None
        self._log(logs, "confirmation_decision", {"decision": "cancel"})
        return self._outcome(task, envelope, "cancelled", logs)

    def _tool_recovery(
        self,
        task: dict[str, Any],
        envelope: EventEnvelope,
        result: ToolExecutionResult,
        step: str,
        logs: list[dict[str, Any]],
    ) -> WorkflowResult:
        code = str((result.error or {}).get("code", "BACKEND_UNAVAILABLE"))
        task["status"] = "awaiting_input"
        task["current_step"] = step
        task["recovery"] = {
            "reason": _recovery_reason(code),
            "allowed_actions": ["retry", "human_help", "cancel"],
        }
        return self._outcome(task, envelope, "recovery", logs)

    def _invalid_backend_recovery(
        self,
        task: dict[str, Any],
        envelope: EventEnvelope,
        step: str,
        logs: list[dict[str, Any]],
    ) -> WorkflowResult:
        task["status"] = "awaiting_input"
        task["current_step"] = step
        task["recovery"] = {
            "reason": "invalid_backend_response",
            "allowed_actions": ["retry", "human_help", "cancel"],
        }
        return self._outcome(task, envelope, "recovery", logs)

    def _dispatch(
        self,
        logs: list[dict[str, Any]],
        name: str,
        step_id: str,
        input_data: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        context = {
            "patient_id": self.patient_id,
            "mock_user_id": self.mock_user_id,
            "authorization": self.authorization,
            "accept_language": "zh-TW",
            "request_id": _identifier("REQ"),
        }
        if idempotency_key:
            context["idempotency_key"] = f"IDEMP-{idempotency_key}"
        call = ToolCall(name, {"context": context, "input": deepcopy(dict(input_data))}, step_id)
        if session_id:
            self._retry_calls[session_id] = {
                "name": name,
                "step_id": step_id,
                "input": deepcopy(dict(input_data)),
                "idempotency_key": idempotency_key,
            }
        try:
            result = self.pipeline.dispatch(call)
        except Exception as error:
            result = ToolExecutionResult(
                name,
                step_id,
                False,
                _identifier("REQ"),
                error={"code": "BACKEND_UNAVAILABLE", "message": str(error), "retryable": True},
            )
        logs.append({"type": "tool_execution", "tool": name, "ok": result.ok})
        return result

    def _outcome(
        self,
        task: dict[str, Any],
        envelope: EventEnvelope,
        response_intent: str,
        logs: list[dict[str, Any]],
    ) -> WorkflowResult:
        task_snapshot = deepcopy(task)
        result = CanonicalInteractionResult(
            interaction_id=envelope.interaction_id,
            task=task_snapshot,
            response_intent=response_intent,
            facts=deepcopy(task_snapshot.get("facts", {})),
            allowed_actions=self._actions(task_snapshot, response_intent),
            confirmation=deepcopy(task_snapshot.get("pending_confirmation")),
            recovery=deepcopy(task_snapshot.get("recovery")),
            receipt=deepcopy(task_snapshot.get("receipt")),
        )
        return task_snapshot, result, deepcopy(logs)

    def _actions(self, task: Mapping[str, Any], response_intent: str) -> list[dict[str, Any]]:
        task_id = task.get("task_id")
        facts = task.get("facts") if isinstance(task.get("facts"), Mapping) else {}
        actions: list[dict[str, Any]] = []
        if response_intent == "select_service":
            for service in facts.get("services", []):
                if isinstance(service, Mapping) and isinstance(service.get("id"), str):
                    actions.append(self._action("選擇服務", {
                        "type": "service_selected",
                        "action_id": _identifier("ACT"),
                        "task_id": task_id,
                        "service_id": service["id"],
                        "date_from": facts.get("date_from", _today()),
                        "date_to": facts.get("date_to", _date_plus(14)),
                    }))
        elif response_intent == "select_slot":
            for slot in facts.get("slots", []):
                if isinstance(slot, Mapping) and isinstance(slot.get("id"), str):
                    actions.append(self._action("選擇時段", {
                        "type": "slot_selected",
                        "action_id": _identifier("ACT"),
                        "task_id": task_id,
                        "slot_id": slot["id"],
                    }))
        elif response_intent == "request_confirmation":
            confirmation = task.get("pending_confirmation")
            if isinstance(confirmation, Mapping):
                for decision, label in (
                    ("approve", "確認預約"),
                    ("reject", "取消預約"),
                    ("modify", "修改資料"),
                ):
                    event = {
                        "type": "confirmation_decision",
                        "action_id": _identifier("ACT"),
                        "task_id": task_id,
                        "confirmation_id": confirmation.get("confirmation_id"),
                        "decision": decision,
                    }
                    service = facts.get("service")
                    if isinstance(service, Mapping) and service.get("requires_referral"):
                        event["referring_appointment_id"] = "APT-REF-DEMO-001"
                    actions.append(self._action(label, event))
        elif response_intent == "recovery":
            recovery = task.get("recovery")
            if isinstance(recovery, Mapping):
                for action, label in (
                    ("retry", "再試一次"),
                    ("human_help", "尋求人工協助"),
                    ("cancel", "取消"),
                ):
                    if action in recovery.get("allowed_actions", []):
                        actions.append(self._action(label, {
                            "type": "recovery_action",
                            "action_id": _identifier("ACT"),
                            "task_id": task_id,
                            "action": action,
                        }))
        return actions

    @staticmethod
    def _action(label: str, event: Mapping[str, Any]) -> dict[str, Any]:
        return {"label": label, "event": deepcopy(dict(event))}

    @staticmethod
    def _log(
        logs: list[dict[str, Any]], event_type: str, details: Mapping[str, Any] | None = None
    ) -> None:
        entry = {"type": event_type}
        if details:
            entry.update(deepcopy(dict(details)))
        logs.append(entry)

    @staticmethod
    def _require_action_target(task: Mapping[str, Any], event: Mapping[str, Any]) -> None:
        task_id = _required(event.get("task_id"), "task_id")
        _required(event.get("action_id"), "action_id")
        if task_id != task.get("task_id"):
            raise ValueError("task_id does not match the active task")


def _require_envelope(envelope: EventEnvelope) -> None:
    if not isinstance(envelope, EventEnvelope):
        raise ValueError("envelope must be an EventEnvelope")


def _copy_task(task: Any) -> dict[str, Any]:
    if not isinstance(task, dict):
        raise ValueError("task must be an object")
    copied = deepcopy(task)
    _required(copied.get("task_id"), "task_id")
    _required(copied.get("type"), "task.type")
    _required(copied.get("status"), "task.status")
    _required(copied.get("current_step"), "task.current_step")
    if not isinstance(copied.get("facts"), dict):
        raise ValueError("task.facts must be an object")
    return copied


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _today() -> str:
    return _demo_now().date().isoformat()


def _date_plus(days: int) -> str:
    return (_demo_now().date() + timedelta(days=days)).isoformat()


def _demo_now() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Macau"))
    return datetime.now(timezone.utc)


def _data_list(result: ToolExecutionResult, noun: str) -> list[dict[str, Any]]:
    if not result.ok or not isinstance(result.data, Mapping) or not isinstance(result.data.get("data"), list):
        raise ValueError(f"medical backend response is missing {noun}")
    return [_safe_mapping(item) for item in result.data["data"] if isinstance(item, Mapping)]


def _safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "id", "name", "name_en", "active", "type", "duration_minutes", "location_id",
        "service_id", "start", "end", "remaining", "status", "requires_referral",
    }
    return {key: deepcopy(item) for key, item in value.items() if key in allowed}


def _safe_service(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value[key])
        for key in (
            "id", "name", "name_en", "type", "duration_minutes", "location_id", "requires_referral"
        )
        if key in value
    }


def _safe_slot(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value[key])
        for key in ("id", "service_id", "start", "end", "location_id", "status")
        if key in value
    }


def _verify_medical_result(result: ToolExecutionResult) -> dict[str, Any]:
    if not isinstance(result, ToolExecutionResult) or not result.ok:
        raise ValueError("medical execution did not succeed")
    payload = result.data
    if not isinstance(payload, Mapping):
        raise ValueError("medical backend response must be an object")
    appointment = payload.get("data")
    backend_task = payload.get("task")
    receipt = payload.get("receipt")
    if not isinstance(appointment, Mapping) or not isinstance(backend_task, Mapping) or not isinstance(receipt, Mapping):
        raise ValueError("medical backend response is missing appointment, task, or receipt")
    service = appointment.get("service")
    location = appointment.get("location")
    start = _required(appointment.get("start"), "appointment.start")
    if not isinstance(service, Mapping) or not isinstance(location, Mapping):
        raise ValueError("appointment service and location are required")
    try:
        parsed_start = datetime.fromisoformat(start)
    except ValueError as error:
        raise ValueError("appointment.start is invalid") from error
    return {
        "task_id": _required(backend_task.get("id"), "task.id"),
        "receipt_id": _required(receipt.get("reference"), "receipt.reference"),
        "issued_at": _required(receipt.get("issued_at"), "receipt.issued_at"),
        "appointment": {
            "appointment_id": _required(appointment.get("id"), "appointment.id"),
            "service_id": _required(service.get("id"), "appointment.service.id"),
            "service": _required(service.get("display"), "appointment.service.display"),
            "date": parsed_start.date().isoformat(),
            "time": parsed_start.strftime("%H:%M"),
            "location": _required(location.get("display"), "appointment.location.display"),
            "status": _required(appointment.get("status"), "appointment.status"),
        },
    }


def _build_action_receipt(task_id: str, verified: Mapping[str, Any]) -> dict[str, Any]:
    task_id = _required(task_id, "task_id")
    if not isinstance(verified, Mapping):
        raise ValueError("verified facts must be an object")
    appointment = verified.get("appointment")
    if not isinstance(appointment, Mapping):
        raise ValueError("verified appointment facts are required")
    return {
        "receipt_id": _required(verified.get("receipt_id"), "receipt_id"),
        "kind": "medical_appointment",
        "status": "completed",
        "issued_at": _required(verified.get("issued_at"), "issued_at"),
        "task_id": task_id,
        "appointment": {
            "service": _required(appointment.get("service"), "appointment.service"),
            "date": _required(appointment.get("date"), "appointment.date"),
            "time": _required(appointment.get("time"), "appointment.time"),
            "location": _required(appointment.get("location"), "appointment.location"),
            "status": _required(appointment.get("status"), "appointment.status"),
        },
    }


def _recovery_reason(code: str) -> str:
    return {
        "SLOT_NOT_AVAILABLE": "slot_unavailable",
        "DUPLICATE_BOOKING": "duplicate_booking",
        "REFERRAL_REQUIRED": "referral_required",
        "BACKEND_INVALID_RESPONSE": "invalid_backend_response",
    }.get(code, "backend_unavailable")


def _response_intent(task: Mapping[str, Any]) -> str:
    status = task.get("status")
    if status == "completed":
        return "completed"
    if status == "cancelled":
        return "cancelled"
    if status == "awaiting_confirmation":
        return "request_confirmation"
    return "recovery"


def _pending_response_intent(task: Mapping[str, Any]) -> str:
    if task.get("status") == "awaiting_confirmation":
        return "request_confirmation"
    if task.get("recovery") is not None or task.get("current_step") == "human_help":
        return "recovery"
    if task.get("current_step") == "select_service":
        return "select_service"
    if task.get("current_step") == "select_slot":
        return "select_slot"
    return _response_intent(task)
