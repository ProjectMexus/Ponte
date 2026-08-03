"""Deterministic interaction controller for Ponte medical assistance."""

from __future__ import annotations

import uuid
from copy import deepcopy
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .contracts import InteractionActionRequest, InteractionRequest, ToolCall, ToolExecutionResult
from .execution import ExecutionPipeline
from .session import SessionState, SessionStore, build_response


_MEDICAL_INTENT_TERMS = ("醫療", "預約", "覆診", "睇醫生", "改期")
_ACTION_NAMES = frozenset({"search_slots", "select_slot", "confirm", "cancel", "retry", "human_help"})
_MISSING = object()


class InteractionController:
    """Own session state and route approved actions to the execution pipeline."""

    def __init__(
        self,
        pipeline: ExecutionPipeline,
        sessions: SessionStore,
        patient_id: str,
        authorization: str,
    ) -> None:
        self.pipeline = pipeline
        self.sessions = sessions
        self.patient_id = _required_string(patient_id, "patient_id")
        self.authorization = _required_string(authorization, "authorization")

    def handle_message(self, request: InteractionRequest) -> dict[str, Any]:
        if not isinstance(request, InteractionRequest):
            raise ValueError("request must be an InteractionRequest")
        state = self.sessions.get_or_create(request.session_id)
        state.last_error = None

        if not _is_medical_intent(request.message):
            state.task_state = "idle"
            state.current_step = "welcome"
            return build_response(
                state,
                "我可以協助查詢醫療預約、可預約服務和時段。請告訴我你想辦理的事項。",
                [{"action": "human_help", "label": "轉接人工協助"}],
            )

        state.task_state = "querying"
        state.current_step = "load_appointments"
        appointments_result = self._run_tool(
            state,
            "medical.get_my_appointments",
            "load_appointments",
            {},
        )
        appointments = self._result_data(state, appointments_result, "load_appointments")
        if appointments is None:
            return build_response(state, "暫時無法查詢你的醫療預約，請稍後再試。", [])
        state.data["appointments"] = appointments

        state.current_step = "load_services"
        services_result = self._run_tool(
            state,
            "medical.list_appointment_services",
            "load_services",
            {},
        )
        services = self._result_data(state, services_result, "load_services")
        if services is None:
            return build_response(state, "暫時無法載入可預約服務，請稍後再試。", [])
        state.data["services"] = services
        state.task_state = "selecting_service"
        state.current_step = "select_service"
        state.confirmation_record = None
        return build_response(
            state,
            "我已查到你的預約和可預約服務，請選擇你想預約的服務。",
            [{"action": "search_slots", "label": "搜尋可預約時段"}],
        )

    def handle_action(self, request: InteractionActionRequest) -> dict[str, Any]:
        if not isinstance(request, InteractionActionRequest):
            raise ValueError("request must be an InteractionActionRequest")
        if request.action not in _ACTION_NAMES:
            raise ValueError(f"Unknown interaction action: {request.action}")

        state = self.sessions.get_or_create(request.session_id)
        state.last_error = None
        action = request.action
        if action == "search_slots":
            return self._search_slots(state, request.payload)
        if action == "select_slot":
            return self._select_slot(state, request.payload)
        if action == "confirm":
            return self._confirm(state, request.payload)
        if action == "cancel":
            state.task_state = "cancelled"
            state.current_step = "cancel"
            state.confirmation_record = None
            return build_response(state, "已取消這次預約協助。", [])
        if action == "retry":
            return self._retry(state)

        state.task_state = "human_handoff"
        state.current_step = "human_help"
        return build_response(state, "我會為你轉接人工協助。", [])

    def _search_slots(self, state: SessionState, payload: Mapping[str, Any]) -> dict[str, Any]:
        service_id = _payload_string(payload, "service_id")
        date_from = _payload_string(payload, "date_from")
        date_to = _payload_string(payload, "date_to")
        input_data: dict[str, Any] = {
            "service_id": service_id,
            "date_from": date_from,
            "date_to": date_to,
        }
        for key in ("doctor_id", "location_id"):
            if key in payload and payload[key] is not None:
                input_data[key] = _payload_string(payload, key)

        state.data.update({"service_id": service_id, "date_from": date_from, "date_to": date_to})
        state.task_state = "querying"
        result = self._run_tool(state, "medical.search_appointment_slots", "search_slots", input_data)
        slots = self._result_data(state, result, "search_slots")
        if slots is None:
            return build_response(state, "暫時無法查詢可預約時段，請稍後再試。", [])
        state.data["slots"] = slots
        state.task_state = "selecting_slot"
        state.current_step = "select_slot"
        return build_response(state, "請選擇一個可預約時段。", [{"action": "select_slot", "label": "選擇時段"}])

    def _select_slot(self, state: SessionState, payload: Mapping[str, Any]) -> dict[str, Any]:
        slot_id = _payload_string(payload, "slot_id")
        if not state.data.get("service_id"):
            raise ValueError("service_id must be selected before slot_id")
        selected_slot: Any = {"id": slot_id}
        slots = state.data.get("slots")
        if isinstance(slots, list):
            for slot in slots:
                if isinstance(slot, Mapping) and slot.get("id") == slot_id:
                    selected_slot = deepcopy(dict(slot))
                    break
        state.data["slot_id"] = slot_id
        state.data["selected_slot"] = selected_slot
        state.task_state = "awaiting_confirmation"
        state.current_step = "confirm_appointment"
        return build_response(
            state,
            "請確認這個時段後再提交預約。",
            [{"action": "confirm", "label": "確認預約"}, {"action": "cancel", "label": "取消"}],
        )

    def _confirm(self, state: SessionState, payload: Mapping[str, Any]) -> dict[str, Any]:
        if state.task_state != "awaiting_confirmation":
            raise ValueError("confirm requires a selected slot awaiting confirmation")
        service_id = state.data.get("service_id")
        slot_id = state.data.get("slot_id")
        if not isinstance(service_id, str) or not service_id or not isinstance(slot_id, str) or not slot_id:
            raise ValueError("confirm requires a stored selected slot")

        input_data: dict[str, Any] = {
            "patient_id": self.patient_id,
            "service_id": service_id,
            "slot_id": slot_id,
            "consent": True,
        }
        for key in ("referring_appointment_id", "administrative_note"):
            if key in payload and payload[key] is not None:
                input_data[key] = _payload_string(payload, key)

        state.confirmation_record = {
            "step_id": "confirm_appointment",
            "displayed_data": deepcopy(state.data.get("selected_slot", {"id": slot_id})),
            "decision": "confirmed",
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        }
        state.task_state = "submitting"
        create_result = self._run_tool(
            state,
            "medical.create_appointment",
            "create_appointment",
            input_data,
            safe_for_retry=False,
            include_idempotency=True,
        )
        if not create_result.ok:
            return build_response(state, "預約提交未成功，請稍後再試。", [])
        task_id = self._task_id(create_result)
        if task_id is None:
            self._set_error(
                state,
                "create_appointment",
                "BACKEND_INVALID_RESPONSE",
                "預約服務回覆缺少任務編號。",
            )
            return build_response(state, "預約服務回覆格式不完整，請稍後再試。", [])

        state.data["task_id"] = task_id
        state.task_state = "submitted"
        status_result = self._run_tool(
            state,
            "medical.get_task_status",
            "get_task_status",
            {"task_id": task_id},
        )
        status_data = self._result_data(state, status_result, "get_task_status")
        if status_data is None or not isinstance(status_data, Mapping):
            return build_response(state, "預約任務狀態暫時無法確認，請稍後再試。", [])
        status = status_data.get("status")
        if not isinstance(status, str) or not status:
            self._set_error(
                state,
                "get_task_status",
                "BACKEND_INVALID_RESPONSE",
                "任務狀態回覆缺少狀態欄位。",
            )
            return build_response(state, "預約任務回覆格式不完整，請稍後再試。", [])
        state.data["task_status"] = status
        state.task_state = _task_state(status)
        state.current_step = "get_task_status"
        return build_response(state, "預約已提交，我已取得最新任務狀態。", [])

    def _retry(self, state: SessionState) -> dict[str, Any]:
        call = state.last_tool_call
        if call is None:
            return build_response(state, "目前沒有可重試的查詢。", [])
        result = self._run_tool(
            state,
            call.name,
            call.step_id,
            call.arguments.get("input", {}),
        )
        if result.ok:
            data = self._result_data(state, result, call.step_id)
            if data is not None:
                state.data["last_retry_data"] = data
                state.task_state = "querying"
                state.current_step = call.step_id
        return build_response(state, "已重試上一個查詢。" if result.ok else "重試查詢仍未成功，請稍後再試。", [])

    def _run_tool(
        self,
        state: SessionState,
        name: str,
        step_id: str,
        input_data: Mapping[str, Any],
        *,
        safe_for_retry: bool = True,
        include_idempotency: bool = False,
    ) -> ToolExecutionResult:
        call = ToolCall(
            name=name,
            arguments={
                "context": self._context(include_idempotency=include_idempotency),
                "input": deepcopy(dict(input_data)),
            },
            step_id=step_id,
        )
        result = self.pipeline.dispatch(call)
        event: dict[str, Any] = {
            "tool_name": result.tool_name,
            "step_id": result.step_id,
            "ok": result.ok,
            "request_id": result.request_id,
            "arguments": {"input": deepcopy(dict(input_data))},
        }
        if result.data is not None:
            event["data"] = deepcopy(result.data)
        if result.error is not None:
            event["error"] = deepcopy(result.error)
        state.tool_events.append(event)
        state.steps.append({"step_id": step_id, "tool_name": name, "ok": result.ok})
        if safe_for_retry:
            state.last_tool_call = call
        if not result.ok:
            self._set_error(
                state,
                step_id,
                (result.error or {}).get("code", "TOOL_EXECUTION_FAILED"),
                (result.error or {}).get("message", "Tool execution failed."),
                details=result.error,
            )
        return result

    def _context(self, *, include_idempotency: bool) -> dict[str, str]:
        context = {
            "patient_id": self.patient_id,
            "authorization": self.authorization,
            "accept_language": "zh-TW",
            "request_id": _request_id(),
        }
        if include_idempotency:
            context["idempotency_key"] = f"IDEMP-MW-{uuid.uuid4().hex[:16].upper()}"
        return context

    def _result_data(
        self,
        state: SessionState,
        result: ToolExecutionResult,
        step_id: str,
    ) -> Any | None:
        if not result.ok:
            return None
        payload = result.data
        if not isinstance(payload, Mapping) or "data" not in payload:
            self._set_error(
                state,
                step_id,
                "BACKEND_INVALID_RESPONSE",
                "Backend response is missing data.",
            )
            return None
        value = payload["data"]
        if not isinstance(value, (list, Mapping)):
            self._set_error(
                state,
                step_id,
                "BACKEND_INVALID_RESPONSE",
                "Backend response data must be a list or object.",
            )
            return None
        return deepcopy(value)

    @staticmethod
    def _task_id(result: ToolExecutionResult) -> str | None:
        payload = result.data
        if not isinstance(payload, Mapping):
            return None
        data = payload.get("data")
        if isinstance(data, Mapping) and isinstance(data.get("task_id"), str) and data["task_id"]:
            return data["task_id"]
        task = payload.get("task")
        if isinstance(task, Mapping) and isinstance(task.get("id"), str) and task["id"]:
            return task["id"]
        return None

    @staticmethod
    def _set_error(
        state: SessionState,
        step_id: str,
        code: str,
        message: str,
        *,
        details: Any = None,
    ) -> None:
        state.task_state = "error"
        state.current_step = step_id
        state.last_error = {
            "code": code,
            "message": message,
            "details": deepcopy(details),
            "retryable": code in {"BACKEND_UNAVAILABLE", "BACKEND_TIMEOUT"},
        }


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _payload_string(payload: Mapping[str, Any], field_name: str) -> str:
    if field_name not in payload:
        raise ValueError(f"Missing required action field: {field_name}")
    return _required_string(payload[field_name], field_name)


def _is_medical_intent(message: str) -> bool:
    return any(term in message for term in _MEDICAL_INTENT_TERMS)


def _request_id() -> str:
    return f"REQ-MW-{uuid.uuid4().hex[:12].upper()}"


def _task_state(status: str) -> str:
    normalized = status.casefold()
    if normalized in {"submitted", "pending", "queued", "processing"}:
        return "submitted"
    if normalized in {"completed", "complete", "succeeded", "success"}:
        return "completed"
    return normalized
