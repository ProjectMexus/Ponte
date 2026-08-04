"""Deterministic interaction controller for Ponte service assistance."""

from __future__ import annotations

import uuid
from copy import deepcopy
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from MCP.registry import ToolRegistry, build_registry

from .contracts import InteractionActionRequest, InteractionRequest, ToolCall, ToolExecutionResult
from .diagnostics import (
    DiagnosticCommand,
    describe_diagnostic_command,
    diagnostic_requires_confirmation,
)
from .execution import ExecutionPipeline
from .intent import IntentRecognizer, KeywordIntentRecognizer, build_intent_recognizer
from .session import SessionState, SessionStore, build_response


_ACTION_NAMES = frozenset({
    "search_slots",
    "select_slot",
    "confirm",
    "confirm_tool",
    "cancel",
    "retry",
    "human_help",
})
_MISSING = object()


class InteractionController:
    """Own session state and route approved actions to the execution pipeline."""

    def __init__(
        self,
        pipeline: ExecutionPipeline,
        sessions: SessionStore,
        patient_id: str,
        authorization: str,
        intent_recognizer: IntentRecognizer | None = None,
        *,
        mock_user_id: str = "USR-DEMO-001",
        registry: ToolRegistry | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.sessions = sessions
        self.patient_id = _required_string(patient_id, "patient_id")
        self.authorization = _required_string(authorization, "authorization")
        self.mock_user_id = _required_string(mock_user_id, "mock_user_id")
        self.registry = registry or build_registry()
        self.intent_recognizer = intent_recognizer or build_intent_recognizer()

    def handle_message(self, request: InteractionRequest) -> dict[str, Any]:
        if not isinstance(request, InteractionRequest):
            raise ValueError("request must be an InteractionRequest")
        state = self.sessions.get_or_create(request.session_id)
        state.last_error = None
        state.data.pop("pending_diagnostic", None)

        diagnostic = DiagnosticCommand.parse(request.message)
        if diagnostic is not None:
            return self._handle_diagnostic_message(state, diagnostic)

        intent = self.intent_recognizer.recognize(request.message)
        state.data["intent"] = intent.intent
        state.data["intent_source"] = intent.source
        if intent.is_cash_sharing:
            return self._handle_cash_sharing(state)
        if intent.is_elderly_activity:
            return self._handle_elderly_activity(state)
        if intent.is_medical_query:
            return self._handle_medical_query(state)
        if intent.is_medical_booking:
            return self._handle_medical_booking(state)
        if not intent.is_medical:
            state.task_state = "idle"
            state.current_step = "welcome"
            return build_response(
                state,
                "我可以協助查詢醫療預約、可預約服務和時段。請告訴我你想辦理的事項。",
                [{"action": "human_help", "label": "轉接人工協助"}],
            )

    def _handle_medical_query(self, state: SessionState) -> dict[str, Any]:
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
        state.task_state = "completed"
        state.current_step = "load_appointments"
        state.confirmation_record = None
        return build_response(state, "我已查到你目前的醫療預約。", [])

    def _handle_medical_booking(self, state: SessionState) -> dict[str, Any]:
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

    def _handle_cash_sharing(self, state: SessionState) -> dict[str, Any]:
        state.task_state = "querying"
        state.current_step = "load_cash_sharing_plan"
        result = self._run_tool(
            state,
            "one_account.get_cash_sharing_plan",
            "load_cash_sharing_plan",
            {},
        )
        data = self._result_data(state, result, "load_cash_sharing_plan")
        if data is None:
            return build_response(state, "暫時無法查詢現金分享計劃，請稍後再試。", [])
        state.data["cash_sharing_plan"] = data
        state.task_state = "completed"
        state.current_step = "cash_sharing_plan"
        return build_response(state, "我已查到你的現金分享計劃資料。", [])

    def _handle_elderly_activity(self, state: SessionState) -> dict[str, Any]:
        state.task_state = "querying"
        state.current_step = "search_elderly_activities"
        result = self._run_tool(
            state,
            "one_account.search_elderly_activities",
            "search_elderly_activities",
            {"available_only": True},
        )
        data = self._result_data(state, result, "search_elderly_activities")
        if data is None:
            return build_response(state, "暫時無法查詢長者文娛活動，請稍後再試。", [])
        state.data["activities"] = data
        state.task_state = "completed"
        state.current_step = "elderly_activities"
        return build_response(state, "我已查到目前可參加的長者文娛活動。", [])

    def handle_action(self, request: InteractionActionRequest) -> dict[str, Any]:
        if not isinstance(request, InteractionActionRequest):
            raise ValueError("request must be an InteractionActionRequest")
        if request.action not in _ACTION_NAMES:
            raise ValueError(f"Unknown interaction action: {request.action}")

        state = self.sessions.get_or_create(request.session_id)
        state.last_error = None
        action = request.action
        if action == "confirm_tool":
            return self._confirm_diagnostic(state)
        if action == "search_slots":
            return self._search_slots(state, request.payload)
        if action == "select_slot":
            return self._select_slot(state, request.payload)
        if action == "confirm":
            return self._confirm(state, request.payload)
        if action == "cancel":
            if state.data.get("pending_diagnostic") is not None:
                return self._cancel_diagnostic(state)
            state.task_state = "cancelled"
            state.current_step = "cancel"
            state.confirmation_record = None
            return build_response(state, "已取消這次預約協助。", [])
        if action == "retry":
            return self._retry(state)

        state.task_state = "human_handoff"
        state.current_step = "human_help"
        return build_response(state, "我會為你轉接人工協助。", [])

    def _handle_diagnostic_message(
        self,
        state: SessionState,
        command: DiagnosticCommand,
    ) -> dict[str, Any]:
        descriptor = describe_diagnostic_command(self.registry, command)
        state.data.pop("backend_response", None)
        state.data["diagnostic"] = deepcopy(descriptor)
        if diagnostic_requires_confirmation(self.registry, command):
            state.data["pending_diagnostic"] = {
                "tool_name": command.tool_name,
                "input": deepcopy(command.input_data),
                "diagnostic": deepcopy(descriptor),
            }
            state.task_state = "awaiting_confirmation"
            state.current_step = "confirm_tool"
            return self._diagnostic_response(
                state,
                "這個 MCP tool 會修改測試資料，請確認後才會執行。",
                [
                    {"kind": "confirm_tool", "label": "確認執行此 API"},
                    {"kind": "cancel", "label": "取消"},
                ],
            )

        step_id = _diagnostic_step_id(command.tool_name)
        result = self._run_tool(
            state,
            command.tool_name,
            step_id,
            command.input_data,
        )
        state.data["backend_response"] = _diagnostic_backend_response(result)
        if result.ok:
            state.task_state = "completed"
            state.current_step = step_id
            message = "已完成 MCP tool 測試，以下是 backend 回應。"
        else:
            message = "MCP tool 測試未成功，請檢查以下錯誤資料。"
        return self._diagnostic_response(state, message, [])

    def _confirm_diagnostic(self, state: SessionState) -> dict[str, Any]:
        pending = state.data.pop("pending_diagnostic", None)
        if not isinstance(pending, Mapping):
            raise ValueError("confirm_tool requires a pending diagnostic command")
        name = pending.get("tool_name")
        input_data = pending.get("input")
        if not isinstance(name, str) or not isinstance(input_data, Mapping):
            raise ValueError("pending diagnostic command is invalid")

        command = DiagnosticCommand(name, dict(input_data))
        descriptor = describe_diagnostic_command(self.registry, command)
        state.data["diagnostic"] = deepcopy(descriptor)
        step_id = _diagnostic_step_id(command.tool_name)
        state.task_state = "querying"
        result = self._run_tool(
            state,
            command.tool_name,
            step_id,
            command.input_data,
            safe_for_retry=False,
            include_idempotency=True,
        )
        state.data["backend_response"] = _diagnostic_backend_response(result)
        if result.ok:
            state.task_state = "completed"
            state.current_step = step_id
            message = "已確認並完成 MCP tool 測試，以下是 backend 回應。"
        else:
            message = "已確認執行，但 MCP tool 未成功。"
        return self._diagnostic_response(state, message, [])

    def _cancel_diagnostic(self, state: SessionState) -> dict[str, Any]:
        state.data.pop("pending_diagnostic", None)
        state.task_state = "cancelled"
        state.current_step = "cancel_diagnostic"
        return self._diagnostic_response(state, "已取消這次 MCP tool 測試。", [])

    @staticmethod
    def _diagnostic_response(
        state: SessionState,
        assistant_message: str,
        actions: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        response = build_response(state, assistant_message, actions)
        response["mode"] = "mcp_diagnostic"
        return response

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
            "mock_user_id": self.mock_user_id,
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
    """Backward-compatible deterministic helper for callers outside the controller."""

    return KeywordIntentRecognizer().recognize(message).is_medical


def _request_id() -> str:
    return f"REQ-MW-{uuid.uuid4().hex[:12].upper()}"


def _diagnostic_step_id(tool_name: str) -> str:
    return f"diagnostic_{tool_name.replace('.', '_')}"


def _diagnostic_backend_response(result: ToolExecutionResult) -> dict[str, Any]:
    if result.data is not None:
        return deepcopy(dict(result.data))
    return {
        "request_id": result.request_id,
        "error": deepcopy(dict(result.error or {})),
    }


def _task_state(status: str) -> str:
    normalized = status.casefold()
    if normalized in {"submitted", "pending", "queued", "processing"}:
        return "submitted"
    if normalized in {"completed", "complete", "succeeded", "success"}:
        return "completed"
    return normalized
