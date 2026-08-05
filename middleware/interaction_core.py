"""Medical, modality-neutral interaction core for the Demo workflow."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import uuid
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python builds without zoneinfo data
    ZoneInfo = None  # type: ignore[assignment]

from MCP.registry import ToolRegistry, build_registry

from .contracts import ToolCall, ToolExecutionResult
from .execution import ExecutionPipeline
from .intent import IntentRecognizer, build_intent_recognizer
from .interaction_contracts import (
    ActionReceiptBuilder,
    CanonicalInteractionResult,
    ConfirmationDecision,
    EventEnvelope,
    MedicalResultVerifier,
    MedicalTask,
)
from .session import SessionState, SessionStore


class InteractionCore:
    """Own the simplified medical task state and business workflow."""

    def __init__(
        self,
        pipeline: ExecutionPipeline,
        sessions: SessionStore,
        patient_id: str,
        authorization: str,
        *,
        mock_user_id: str = "USR-DEMO-001",
        intent_recognizer: IntentRecognizer | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.sessions = sessions
        self.patient_id = _required(patient_id, "patient_id")
        self.authorization = _required(authorization, "authorization")
        self.mock_user_id = _required(mock_user_id, "mock_user_id")
        self.intent_recognizer = intent_recognizer or build_intent_recognizer()
        self.registry = registry or build_registry()
        self._retry_calls: dict[str, dict[str, Any]] = {}

    def handle(self, envelope: EventEnvelope) -> CanonicalInteractionResult:
        if not isinstance(envelope, EventEnvelope):
            raise ValueError("envelope must be an EventEnvelope")
        state = self.sessions.get_or_create(envelope.session_id)
        event = envelope.event
        event_type = event.get("type")
        if event_type == "user_utterance":
            return self._handle_utterance(state, envelope)
        if event_type == "service_selected":
            return self._service_selected(state, envelope)
        if event_type == "slot_selected":
            return self._slot_selected(state, envelope)
        if event_type == "confirmation_decision":
            return self._confirmation_decision(state, envelope)
        if event_type == "recovery_action":
            return self._recovery_action(state, envelope)
        if event_type == "cancel_task":
            return self._cancel(state, envelope)
        raise ValueError(f"unsupported interaction event: {event_type}")

    def _handle_utterance(self, state: SessionState, envelope: EventEnvelope) -> CanonicalInteractionResult:
        content = _required(envelope.event.get("content"), "event.content")
        if state.task is not None and state.task.get("status") not in {"completed", "cancelled", "failed"}:
            # The Demo has one active task. A follow-up utterance keeps that task
            # and is interpreted as a new request only when no workflow input is pending.
            if state.task.get("status") == "awaiting_confirmation":
                return self._result(state, envelope, "request_confirmation")
        decision = self.intent_recognizer.recognize(content)
        if not getattr(decision, "is_medical", False):
            raise ValueError("medical InteractionCore received a non-medical utterance")
        self._retry_calls.pop(envelope.session_id, None)
        task = self._new_task(state)
        self._log(state, "user_utterance", {"content": content})
        if getattr(decision, "is_medical_query", False):
            result = self._dispatch(state, "medical.get_my_appointments", "load_appointments", {}, session_id=envelope.session_id)
            if not result.ok:
                return self._tool_recovery(state, envelope, result, "load_appointments")
            try:
                appointments = _data_list(result, "appointments")
            except ValueError:
                return self._invalid_backend_recovery(state, envelope, "load_appointments")
            task["facts"] = {"appointments": appointments}
            task["status"] = "completed"
            task["current_step"] = "complete"
            self._log(state, "execution_completed")
            return self._result(state, envelope, "appointment_list")

        result = self._dispatch(state, "medical.list_appointment_services", "load_services", {}, session_id=envelope.session_id)
        if not result.ok:
            return self._tool_recovery(state, envelope, result, "load_services")
        try:
            services = _data_list(result, "services")
        except ValueError:
            return self._invalid_backend_recovery(state, envelope, "load_services")
        task["facts"] = {"services": services}
        task["status"] = "awaiting_input"
        task["current_step"] = "select_service"
        self._log(state, "service_selected", {"count": len(services), "event": "catalog_loaded"})
        return self._result(state, envelope, "select_service")

    def _service_selected(self, state: SessionState, envelope: EventEnvelope) -> CanonicalInteractionResult:
        task = self._require_action_target(state, envelope.event)
        service_id = _required(envelope.event.get("service_id"), "service_id")
        date_from = _required(envelope.event.get("date_from"), "date_from")
        date_to = _required(envelope.event.get("date_to"), "date_to")
        services = task["facts"].get("services", [])
        service = next((item for item in services if isinstance(item, Mapping) and item.get("id") == service_id), None)
        if not isinstance(service, Mapping):
            raise ValueError("service_id is not one of the server-provided services")
        result = self._dispatch(
            state,
            "medical.search_appointment_slots",
            "search_slots",
            {"service_id": service_id, "date_from": date_from, "date_to": date_to},
            session_id=envelope.session_id,
        )
        if not result.ok:
            return self._tool_recovery(state, envelope, result, "search_slots")
        try:
            slots = _data_list(result, "slots")
        except ValueError:
            return self._invalid_backend_recovery(state, envelope, "search_slots")
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
        self._log(state, "service_selected", {"service_id": service_id})
        return self._result(state, envelope, "select_slot")

    def _slot_selected(self, state: SessionState, envelope: EventEnvelope) -> CanonicalInteractionResult:
        task = self._require_action_target(state, envelope.event)
        slot_id = _required(envelope.event.get("slot_id"), "slot_id")
        slots = task["facts"].get("slots", [])
        slot = next((item for item in slots if isinstance(item, Mapping) and item.get("id") == slot_id), None)
        if not isinstance(slot, Mapping):
            raise ValueError("slot_id is not one of the server-provided slots")
        confirmation_id = _identifier("CONF")
        task["facts"]["slot_id"] = slot_id
        task["facts"]["selected_slot"] = _safe_slot(slot)
        task["pending_confirmation"] = {"confirmation_id": confirmation_id, "status": "pending"}
        task["status"] = "awaiting_confirmation"
        task["current_step"] = "confirm_appointment"
        task["recovery"] = None
        self._log(state, "slot_selected", {"slot_id": slot_id})
        self._log(state, "confirmation_requested", {"confirmation_id": confirmation_id})
        return self._result(state, envelope, "request_confirmation")

    def _confirmation_decision(self, state: SessionState, envelope: EventEnvelope) -> CanonicalInteractionResult:
        task = self._require_action_target(state, envelope.event)
        decision = ConfirmationDecision.from_event(envelope.event)
        pending = task.get("pending_confirmation")
        if not isinstance(pending, Mapping) or pending.get("confirmation_id") != decision.confirmation_id:
            raise ValueError("confirmation_id does not match the active task")
        if pending.get("status") != "pending":
            return self._result(state, envelope, _response_intent(task))
        if decision.decision == "reject":
            task["pending_confirmation"]["status"] = "rejected"
            task["status"] = "cancelled"
            task["current_step"] = "cancelled"
            self._log(state, "confirmation_decision", {"decision": "reject"})
            return self._result(state, envelope, "cancelled")
        if decision.decision == "modify":
            task["pending_confirmation"]["status"] = "modified"
            task["status"] = "awaiting_input"
            task["current_step"] = "select_service"
            task["recovery"] = None
            task["facts"].pop("slot_id", None)
            task["facts"].pop("selected_slot", None)
            self._log(state, "confirmation_decision", {"decision": "modify"})
            return self._result(state, envelope, "select_service")

        task["pending_confirmation"]["status"] = "approved"
        task["status"] = "executing"
        task["current_step"] = "create_appointment"
        self._log(state, "confirmation_decision", {"decision": "approve"})
        service_id = _required(task["facts"].get("service_id"), "service_id")
        slot_id = _required(task["facts"].get("slot_id"), "slot_id")
        create_input = {
            "patient_id": self.patient_id,
            "service_id": service_id,
            "slot_id": slot_id,
            "consent": True,
        }
        referral_id = task["facts"].get("referring_appointment_id")
        if isinstance(referral_id, str) and referral_id.strip():
            create_input["referring_appointment_id"] = referral_id.strip()
        result = self._dispatch(
            state,
            "medical.create_appointment",
            "create_appointment",
            create_input,
            idempotency_key=decision.confirmation_id,
            session_id=envelope.session_id,
        )
        if not result.ok:
            return self._tool_recovery(state, envelope, result, "create_appointment")
        try:
            verified = MedicalResultVerifier.verify(result)
            receipt = ActionReceiptBuilder.build(task["task_id"], verified)
        except ValueError:
            return self._invalid_backend_recovery(state, envelope, "create_appointment")
        task["facts"]["appointment"] = deepcopy(verified["appointment"])
        task["receipt"] = receipt
        task["status"] = "completed"
        task["current_step"] = "complete"
        task["recovery"] = None
        self._log(state, "execution_completed", {"receipt_id": receipt["receipt_id"]})
        self._log(state, "receipt_created", {"receipt_id": receipt["receipt_id"]})
        return self._result(state, envelope, "completed")

    def _recovery_action(self, state: SessionState, envelope: EventEnvelope) -> CanonicalInteractionResult:
        task = self._require_action_target(state, envelope.event)
        action = _required(envelope.event.get("action"), "action")
        if action == "cancel":
            return self._cancel(state, envelope)
        if action == "human_help":
            task["status"] = "awaiting_input"
            task["current_step"] = "human_help"
            task["recovery"] = {"reason": "human_help_requested", "allowed_actions": ["cancel"]}
            return self._result(state, envelope, "recovery")
        if action != "retry":
            raise ValueError("recovery action must be retry, human_help, or cancel")
        recovery = task.get("recovery")
        retry_call = self._retry_calls.get(envelope.session_id)
        if not isinstance(recovery, Mapping) or not isinstance(retry_call, Mapping):
            raise ValueError("no retryable recovery is available")
        result = self._dispatch(
            state,
            _required(retry_call.get("name"), "retry tool"),
            _required(retry_call.get("step_id"), "retry step"),
            retry_call.get("input", {}),
            idempotency_key=retry_call.get("idempotency_key"),
            session_id=envelope.session_id,
        )
        step = _required(retry_call.get("step_id"), "retry step")
        if not result.ok:
            return self._tool_recovery(state, envelope, result, step)
        if step == "load_appointments":
            try:
                task["facts"] = {"appointments": _data_list(result, "appointments")}
            except ValueError:
                return self._invalid_backend_recovery(state, envelope, step)
            task["status"] = "completed"
            task["current_step"] = "complete"
            task["recovery"] = None
            self._log(state, "execution_completed")
            return self._result(state, envelope, "appointment_list")
        if step == "load_services":
            try:
                task["facts"] = {"services": _data_list(result, "services")}
            except ValueError:
                return self._invalid_backend_recovery(state, envelope, step)
            task["status"] = "awaiting_input"
            task["current_step"] = "select_service"
            task["recovery"] = None
            return self._result(state, envelope, "select_service")
        if step == "search_slots":
            try:
                slots = _data_list(result, "slots")
            except ValueError:
                return self._invalid_backend_recovery(state, envelope, step)
            task["facts"]["slots"] = slots
            task["status"] = "awaiting_input"
            task["current_step"] = "select_slot"
            task["recovery"] = None
            return self._result(state, envelope, "select_slot")
        if step == "create_appointment":
            try:
                verified = MedicalResultVerifier.verify(result)
                receipt = ActionReceiptBuilder.build(task["task_id"], verified)
            except ValueError:
                return self._invalid_backend_recovery(state, envelope, step)
            task["facts"]["appointment"] = deepcopy(verified["appointment"])
            task["receipt"] = receipt
            task["status"] = "completed"
            task["current_step"] = "complete"
            task["recovery"] = None
            self._log(state, "execution_completed", {"receipt_id": receipt["receipt_id"]})
            self._log(state, "receipt_created", {"receipt_id": receipt["receipt_id"]})
            return self._result(state, envelope, "completed")
        raise ValueError("no retryable recovery is available")

    def _cancel(self, state: SessionState, envelope: EventEnvelope) -> CanonicalInteractionResult:
        task = self._require_action_target(state, envelope.event)
        pending = task.get("pending_confirmation")
        if isinstance(pending, dict) and pending.get("status") == "pending":
            pending["status"] = "rejected"
        task["status"] = "cancelled"
        task["current_step"] = "cancelled"
        task["recovery"] = None
        self._log(state, "confirmation_decision", {"decision": "cancel"})
        return self._result(state, envelope, "cancelled")

    def _tool_recovery(self, state: SessionState, envelope: EventEnvelope, result: ToolExecutionResult, step: str) -> CanonicalInteractionResult:
        code = str((result.error or {}).get("code", "BACKEND_UNAVAILABLE"))
        task = self._require_task(state, {})
        reason = _recovery_reason(code)
        task["status"] = "awaiting_input"
        task["current_step"] = step
        task["recovery"] = {
            "reason": reason,
            "allowed_actions": ["retry", "human_help", "cancel"],
        }
        return self._result(state, envelope, "recovery")

    def _invalid_backend_recovery(self, state: SessionState, envelope: EventEnvelope, step: str) -> CanonicalInteractionResult:
        task = self._require_task(state, {})
        task["status"] = "awaiting_input"
        task["current_step"] = step
        task["recovery"] = {
            "reason": "invalid_backend_response",
            "allowed_actions": ["retry", "human_help", "cancel"],
        }
        return self._result(state, envelope, "recovery")

    def _new_task(self, state: SessionState) -> dict[str, Any]:
        task = MedicalTask(_identifier("TASK")).to_dict()
        state.active_task_id = task["task_id"]
        state.task = task
        return task

    def _require_task(self, state: SessionState, event: Mapping[str, Any]) -> dict[str, Any]:
        task = state.task
        if not isinstance(task, dict):
            raise ValueError("task does not exist")
        task_id = event.get("task_id") if isinstance(event, Mapping) else None
        if task_id is not None and task_id != task.get("task_id"):
            raise ValueError("task_id does not match the active task")
        return task

    def _require_action_target(self, state: SessionState, event: Mapping[str, Any]) -> dict[str, Any]:
        task = self._require_task(state, event)
        _required(event.get("action_id"), "action_id")
        _required(event.get("task_id"), "task_id")
        return task

    def _dispatch(
        self,
        state: SessionState,
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
        state.interaction_log.append({"type": "tool_execution", "tool": name, "ok": result.ok})
        return result

    def _result(self, state: SessionState, envelope: EventEnvelope, response_intent: str) -> CanonicalInteractionResult:
        task = deepcopy(state.task or {})
        facts = deepcopy(task.get("facts", {}))
        actions = self._actions(task, response_intent)
        confirmation = deepcopy(task.get("pending_confirmation"))
        return CanonicalInteractionResult(
            interaction_id=envelope.interaction_id,
            task=task,
            response_intent=response_intent,
            facts=facts,
            allowed_actions=actions,
            confirmation=confirmation,
            recovery=deepcopy(task.get("recovery")),
            receipt=deepcopy(task.get("receipt")),
        )

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
                for decision, label in (("approve", "確認預約"), ("reject", "取消預約"), ("modify", "修改資料")):
                    event = {
                        "type": "confirmation_decision",
                        "action_id": _identifier("ACT"),
                        "task_id": task_id,
                        "confirmation_id": confirmation.get("confirmation_id"),
                        "decision": decision,
                    }
                    service = facts.get("service")
                    if isinstance(service, Mapping) and service.get("requires_referral"):
                        # The mock backend has no seeded referral resource. Keep
                        # the Demo target server-issued and replace this with a
                        # user-selected referral when that field is migrated.
                        event["referring_appointment_id"] = "APT-REF-DEMO-001"
                    actions.append(self._action(label, event))
        elif response_intent == "recovery":
            recovery = task.get("recovery")
            if isinstance(recovery, Mapping):
                for action, label in (("retry", "再試一次"), ("human_help", "尋求人工協助"), ("cancel", "取消")):
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
    def _log(state: SessionState, event_type: str, details: Mapping[str, Any] | None = None) -> None:
        entry = {"type": event_type}
        if details:
            entry.update(deepcopy(dict(details)))
        state.interaction_log.append(entry)


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
    allowed = {"id", "name", "name_en", "active", "type", "duration_minutes", "location_id", "service_id", "start", "end", "remaining", "status", "requires_referral"}
    return {key: deepcopy(item) for key, item in value.items() if key in allowed}


def _safe_service(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value[key]) for key in ("id", "name", "name_en", "type", "duration_minutes", "location_id", "requires_referral") if key in value}


def _safe_slot(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value[key]) for key in ("id", "service_id", "start", "end", "location_id", "status") if key in value}


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
