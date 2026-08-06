"""Deterministic interaction controller for Ponte service assistance."""

from __future__ import annotations

import uuid
from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from MCP.registry import ToolRegistry, build_registry

from .contracts import InteractionActionRequest, InteractionRequest, ToolCall, ToolExecutionResult
from .diagnostics import (
    DiagnosticCommand,
    describe_diagnostic_command,
    diagnostic_requires_confirmation,
)
from .execution import ExecutionPipeline
from .intent import IntentRecognizer, build_intent_recognizer
from .session import SessionState, SessionStore, build_response
from .task_manager.interpreter import DeterministicTaskRecoveryInterpreter, TaskRecoveryInterpreter
from .task_manager.manager import TaskManager


_ACTION_NAMES = frozenset({
    "confirm_tool",
    "cancel",
})
_RETIRED_MEDICAL_ACTIONS = frozenset({
    "select_service",
    "search_slots",
    "select_slot",
    "confirm",
    "retry",
    "human_help",
})


class LegacyInteractionContractError(ValueError):
    """A legacy interaction route received a request owned by the canonical event contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
        recovery_interpreter: TaskRecoveryInterpreter | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.sessions = sessions
        self.patient_id = _required_string(patient_id, "patient_id")
        self.authorization = _required_string(authorization, "authorization")
        self.mock_user_id = _required_string(mock_user_id, "mock_user_id")
        self.registry = registry or build_registry()
        self.intent_recognizer = intent_recognizer or build_intent_recognizer()
        self.recovery_interpreter = recovery_interpreter or DeterministicTaskRecoveryInterpreter()

    def handle_message(self, request: InteractionRequest) -> dict[str, Any]:
        if not isinstance(request, InteractionRequest):
            raise ValueError("request must be an InteractionRequest")
        state = self.sessions.get_or_create(request.session_id)
        self._task_manager(state).start_new_task()

        diagnostic = DiagnosticCommand.parse(request.message)
        if diagnostic is not None:
            return self._handle_diagnostic_message(state, diagnostic)

        intent = self.intent_recognizer.recognize(request.message)
        state.data["intent"] = intent.intent
        state.data["intent_source"] = intent.source
        if intent.is_medical:
            raise LegacyInteractionContractError(
                "INTERACTION_EVENT_REQUIRED",
                "醫療預約已改用 /api/interactions 事件合約，legacy 文字路徑不再執行醫療工具。",
            )
        if intent.is_cash_sharing:
            raise LegacyInteractionContractError(
                "INTERACTION_EVENT_REQUIRED",
                "現金分享查詢已改用 /api/interactions 事件合約，legacy 文字路徑不再執行一戶通工具。",
            )
        if intent.is_elderly_activity:
            return self._handle_elderly_activity(state)
        self._task_manager(state).transition("idle", "welcome")
        return build_response(
            state,
            "我可以協助查詢醫療預約、可預約服務和時段。請告訴我你想辦理的事項。",
            [{"action": "human_help", "label": "轉接人工協助"}],
        )

    def _handle_elderly_activity(self, state: SessionState) -> dict[str, Any]:
        manager = self._task_manager(state)
        manager.transition("querying", "search_elderly_activities")
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
        manager.complete("elderly_activities")
        return build_response(state, "我已查到目前可參加的長者文娛活動。", [])

    def handle_action(self, request: InteractionActionRequest) -> dict[str, Any]:
        if not isinstance(request, InteractionActionRequest):
            raise ValueError("request must be an InteractionActionRequest")
        if request.action in _RETIRED_MEDICAL_ACTIONS:
            raise LegacyInteractionContractError(
                "INTERACTION_EVENT_REQUIRED",
                "醫療 action 已改用 /api/interactions 事件合約，legacy action 路徑不再執行醫療工具。",
            )
        if request.action not in _ACTION_NAMES:
            raise ValueError(f"Unknown interaction action: {request.action}")

        state = self.sessions.get_or_create(request.session_id)
        self._task_manager(state).start_action()
        if request.action == "confirm_tool":
            return self._confirm_diagnostic(state)
        if state.data.get("pending_diagnostic") is not None:
            return self._cancel_diagnostic(state)
        raise LegacyInteractionContractError(
            "INTERACTION_EVENT_REQUIRED",
            "legacy cancel 只適用於 MCP 診斷確認；醫療預約請改用 /api/interactions 事件合約。",
        )

    def _task_manager(self, state: SessionState) -> TaskManager:
        return TaskManager(state, self.recovery_interpreter)

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
            self._task_manager(state).transition("awaiting_confirmation", "confirm_tool")
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
            self._task_manager(state).complete(step_id)
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
        self._task_manager(state).transition("querying", step_id)
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
            self._task_manager(state).complete(step_id)
            message = "已確認並完成 MCP tool 測試，以下是 backend 回應。"
        else:
            message = "已確認執行，但 MCP tool 未成功。"
        return self._diagnostic_response(state, message, [])

    def _cancel_diagnostic(self, state: SessionState) -> dict[str, Any]:
        state.data.pop("pending_diagnostic", None)
        self._task_manager(state).cancel("cancel_diagnostic")
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
        self._task_manager(state).record_tool_result(
            result,
            step_id,
            input_data,
            safe_for_retry=safe_for_retry,
            workflow=str(state.data.get("intent", "general")),
            call=call,
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

    def _set_error(
        self,
        state: SessionState,
        step_id: str,
        code: str,
        message: str,
        *,
        details: Any = None,
    ) -> None:
        self._task_manager(state).fail(
            step_id,
            {
                "code": code,
                "message": message,
                "details": deepcopy(details),
                "retryable": code in {"BACKEND_UNAVAILABLE", "BACKEND_TIMEOUT"},
            },
            message,
        )


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


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
