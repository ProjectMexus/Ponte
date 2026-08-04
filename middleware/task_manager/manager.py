"""Task lifecycle adapter between SessionState and the execution pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any
import uuid

from ponte_logging import log_event

from .contracts import RecoveryPlan
from .interpreter import DeterministicTaskRecoveryInterpreter, TaskRecoveryInterpreter
from .recovery import build_recovery_plan
from .transitions import ensure_transition
from ..contracts import ToolCall, ToolExecutionResult
from ..session import SessionState


_RECOVERY_DATA_KEYS = frozenset({
    "intent",
    "service_id",
    "date_from",
    "date_to",
    "doctor_id",
    "location_id",
})


class TaskManager:
    """Own lifecycle mutations while keeping SessionState as the storage object."""

    def __init__(
        self,
        state: SessionState,
        recovery_interpreter: TaskRecoveryInterpreter | None = None,
    ) -> None:
        if not isinstance(state, SessionState):
            raise ValueError("state must be a SessionState")
        self.state = state
        self.recovery_interpreter = (
            recovery_interpreter
            if recovery_interpreter is not None
            else DeterministicTaskRecoveryInterpreter()
        )

    def start_new_task(self) -> None:
        self.state.reset_for_new_task()

    def start_action(self) -> None:
        self.state.last_error = None
        self.state.recovery = None

    def transition(self, task_state: str, current_step: str) -> None:
        ensure_transition(self.state.task_state, task_state)
        self.state.task_state = task_state
        self.state.current_step = current_step

    def record_tool_result(
        self,
        result: ToolExecutionResult,
        step_id: str,
        input_data: Mapping[str, Any],
        *,
        safe_for_retry: bool,
        workflow: str,
        call: ToolCall | None = None,
    ) -> None:
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
            event["error"] = _safe_error(result.error)
        self.state.tool_events.append(event)
        self.state.steps.append({"step_id": step_id, "tool_name": result.tool_name, "ok": result.ok})
        if safe_for_retry and call is not None:
            self.state.last_tool_call = call
        if result.ok:
            return

        error = deepcopy(dict(result.error or {
            "code": "TOOL_EXECUTION_FAILED",
            "message": "Tool execution failed.",
            "retryable": False,
        }))
        safe_data = _safe_recovery_data(self.state.data)
        fallback = build_recovery_plan(
            error=error,
            step_id=step_id,
            workflow=workflow,
            data=safe_data,
            result_data=None,
            retryable=safe_for_retry and bool(error.get("retryable", False)),
        )
        interpreted = self._interpret_recovery(
            error=_safe_error(error),
            step_id=step_id,
            workflow=workflow,
            data=safe_data,
            fallback=fallback,
        )
        plan = interpreted if isinstance(interpreted, RecoveryPlan) else fallback
        if isinstance(plan, RecoveryPlan):
            self.request_user_input(plan)
        else:
            self.fail(step_id, error, "這一步未能完成，請稍後再試。")

    def _interpret_recovery(
        self,
        *,
        error: Mapping[str, Any],
        step_id: str,
        workflow: str,
        data: Mapping[str, Any],
        fallback: RecoveryPlan | None,
    ) -> RecoveryPlan | None:
        request_id = f"LLM-REC-{uuid.uuid4().hex[:12].upper()}"
        source = getattr(self.recovery_interpreter, "source", "configured_interpreter")
        if isinstance(self.recovery_interpreter, DeterministicTaskRecoveryInterpreter):
            source = "deterministic_fallback"
        log_event(
            "llm",
            "recovery_interpreter_call",
            request_id=request_id,
            operation="task_recovery",
            source=source,
            error_code=error.get("code"),
            outcome="started",
        )
        try:
            plan = self.recovery_interpreter.interpret(
                error=error,
                step_id=step_id,
                workflow=workflow,
                data=data,
                fallback=fallback,
            )
        except Exception as error:
            log_event(
                "llm",
                "recovery_interpreter_error",
                request_id=request_id,
                operation="task_recovery",
                source=source,
                error_code="task_recovery_interpreter_error",
                error_type=type(error).__name__,
                outcome="error",
            )
            return None
        log_event(
            "llm",
            "recovery_interpreter_result",
            request_id=request_id,
            operation="task_recovery",
            source=source,
            error_code=error.get("code"),
            outcome="recovery_plan" if isinstance(plan, RecoveryPlan) else "no_plan",
            fallback_reason="llm_not_configured" if source == "deterministic_fallback" else None,
        )
        return plan

    def request_user_input(self, plan: RecoveryPlan) -> None:
        if not isinstance(plan, RecoveryPlan):
            raise ValueError("plan must be a RecoveryPlan")
        self.transition("awaiting_user_input", self.state.current_step)
        self.state.recovery = plan.to_dict()

    def complete(self, current_step: str) -> None:
        self.transition("completed", current_step)
        self.state.recovery = None
        self.state.last_error = None

    def cancel(self, current_step: str) -> None:
        self.transition("cancelled", current_step)
        self.state.recovery = None

    def human_handoff(self) -> None:
        self.transition("human_handoff", "human_help")
        self.state.recovery = None

    def fail(self, current_step: str, error: Mapping[str, Any], message: str) -> None:
        self.transition("failed", current_step)
        self.state.recovery = None
        self.state.last_error = {
            "code": str(error.get("code", "TOOL_EXECUTION_FAILED")),
            "message": message if isinstance(message, str) and message.strip() else "這一步未能完成，請稍後再試。",
            "details": _safe_error(error).get("details"),
            "retryable": bool(error.get("retryable", False)),
        }


def _safe_recovery_data(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in data.items()
        if key in _RECOVERY_DATA_KEYS
    }


def _safe_error(error: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {
        "code": error.get("code"),
        "retryable": bool(error.get("retryable", False)),
    }
    status = error.get("status")
    if isinstance(status, int):
        safe["status"] = status
    details = error.get("details")
    if isinstance(details, Mapping):
        safe_details: dict[str, Any] = {}
        for key in ("field", "fields", "alternatives", "available_slots"):
            if key in details:
                safe_details[key] = deepcopy(details[key])
        safe["details"] = safe_details
    return safe
