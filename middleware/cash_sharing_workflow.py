"""Read-only cash sharing workflow independent of interaction routing and sessions."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any
import uuid

from .contracts import ToolCall, ToolExecutionResult
from .execution import ExecutionPipeline
from .intent import IntentDecision
from .interaction_contracts import (
    CanonicalInteractionResult,
    EventEnvelope,
    InteractionTask,
)


WorkflowResult = tuple[dict[str, Any], CanonicalInteractionResult, list[dict[str, Any]]]


class CashSharingWorkflow:
    """Own the read-only cash sharing lookup while callers own persistence."""

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
        """Start one read-only cash sharing lookup from a classified user utterance."""
        _require_envelope(envelope)
        if envelope.event.get("type") != "user_utterance":
            raise ValueError("cash sharing workflow must start with a user_utterance")
        if not isinstance(intent, IntentDecision) or not intent.is_cash_sharing:
            raise ValueError("cash sharing workflow received a non-cash intent")

        task = InteractionTask(
            task_id=_identifier("TASK"),
            type="cash_sharing_query",
            status="awaiting_input",
            current_step="load_cash_sharing_plan",
        ).to_dict()
        logs: list[dict[str, Any]] = []
        self._retry_calls.pop(envelope.session_id, None)
        self._log(logs, "user_utterance", {"content": envelope.event["content"]})
        return self._load_plan(task, envelope, logs)

    def handle(self, task_dict: dict[str, Any], envelope: EventEnvelope) -> WorkflowResult:
        """Advance an existing cash task; only recovery and cancel events are accepted."""
        _require_envelope(envelope)
        task = _copy_task(task_dict)
        event_type = envelope.event.get("type")
        logs: list[dict[str, Any]] = []
        if event_type == "user_utterance":
            if task.get("status") in {"completed", "cancelled", "failed"}:
                raise ValueError("terminal cash sharing task cannot accept a follow-up utterance")
            return self._outcome(task, envelope, _response_intent(task), logs)
        if event_type == "recovery_action":
            return self._recovery_action(task, envelope, logs)
        if event_type == "cancel_task":
            return self._cancel(task, envelope, logs)
        raise ValueError(f"unsupported cash sharing workflow event: {event_type}")

    def _load_plan(
        self, task: dict[str, Any], envelope: EventEnvelope, logs: list[dict[str, Any]]
    ) -> WorkflowResult:
        result = self._dispatch(
            logs,
            "one_account.get_cash_sharing_plan",
            "load_cash_sharing_plan",
            {},
            session_id=envelope.session_id,
        )
        if not result.ok:
            return self._tool_recovery(task, envelope, result, "load_cash_sharing_plan", logs)
        try:
            facts = _verify_cash_result(result)
        except ValueError:
            return self._invalid_backend_recovery(task, envelope, "load_cash_sharing_plan", logs)
        task["facts"] = facts
        task["status"] = "completed"
        task["current_step"] = "complete"
        task["recovery"] = None
        # TODO: Cash-sharing receipt semantics remain undefined until the backend
        # issues a business reference and timestamp. Never derive a receipt from
        # ToolExecutionResult.request_id or a middleware-generated identifier.
        task["receipt"] = None
        self._log(logs, "execution_completed")
        return self._outcome(task, envelope, "cash_sharing_summary", logs)

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
            return self._outcome(task, envelope, "cash_sharing_recovery", logs)
        if action != "retry":
            raise ValueError("recovery action must be retry, human_help, or cancel")
        recovery = task.get("recovery")
        retry_call = self._retry_calls.get(envelope.session_id)
        if not isinstance(recovery, Mapping) or not isinstance(retry_call, Mapping):
            raise ValueError("no retryable recovery is available")
        return self._load_plan(task, envelope, logs)

    def _cancel(
        self, task: dict[str, Any], envelope: EventEnvelope, logs: list[dict[str, Any]]
    ) -> WorkflowResult:
        self._require_action_target(task, envelope.event)
        task["status"] = "cancelled"
        task["current_step"] = "cancelled"
        task["recovery"] = None
        self._log(logs, "cash_query_cancelled")
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
        return self._outcome(task, envelope, "cash_sharing_recovery", logs)

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
        return self._outcome(task, envelope, "cash_sharing_recovery", logs)

    def _dispatch(
        self,
        logs: list[dict[str, Any]],
        name: str,
        step_id: str,
        input_data: Mapping[str, Any],
        *,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        context = {
            "patient_id": self.patient_id,
            "mock_user_id": self.mock_user_id,
            "authorization": self.authorization,
            "accept_language": "zh-TW",
            "request_id": _identifier("REQ"),
        }
        call = ToolCall(name, {"context": context, "input": deepcopy(dict(input_data))}, step_id)
        if session_id:
            self._retry_calls[session_id] = {
                "name": name,
                "step_id": step_id,
                "input": deepcopy(dict(input_data)),
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
            confirmation=None,
            recovery=deepcopy(task_snapshot.get("recovery")),
            receipt=deepcopy(task_snapshot.get("receipt")),
        )
        return task_snapshot, result, deepcopy(logs)

    def _actions(self, task: Mapping[str, Any], response_intent: str) -> list[dict[str, Any]]:
        task_id = task.get("task_id")
        actions: list[dict[str, Any]] = []
        if response_intent != "cash_sharing_recovery":
            return actions
        recovery = task.get("recovery")
        if not isinstance(recovery, Mapping):
            return actions
        for action, label in (
            ("retry", "再試一次"),
            ("human_help", "尋求人工協助"),
            ("cancel", "取消"),
        ):
            if action in recovery.get("allowed_actions", []):
                actions.append({
                    "label": label,
                    "event": {
                        "type": "recovery_action",
                        "action_id": _identifier("ACT"),
                        "task_id": task_id,
                        "action": action,
                    },
                })
        return actions

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


def _required_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _verify_cash_result(result: ToolExecutionResult) -> dict[str, Any]:
    if not isinstance(result, ToolExecutionResult) or not result.ok:
        raise ValueError("cash sharing lookup did not succeed")
    payload = result.data
    if not isinstance(payload, Mapping):
        raise ValueError("cash sharing backend response must be an object")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("cash sharing backend response is missing data")
    plan = data.get("plan")
    if not isinstance(plan, Mapping):
        raise ValueError("cash sharing response is missing plan")
    return {
        "plan": _verify_plan(plan),
        "history": _verify_history(data.get("history")),
    }


def _verify_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    verified: dict[str, Any] = {
        "plan_id": _required(plan.get("plan_id"), "plan.plan_id"),
        "plan_name": _required(plan.get("plan_name"), "plan.plan_name"),
        "year": _required_int(plan.get("year"), "plan.year"),
        "status": _required(plan.get("status"), "plan.status"),
    }
    eligibility = plan.get("eligibility")
    if not isinstance(eligibility, Mapping):
        raise ValueError("plan.eligibility is required")
    verified["eligibility"] = _verify_eligibility(eligibility)
    payout = plan.get("payout")
    if not isinstance(payout, Mapping):
        raise ValueError("plan.payout is required")
    verified["payout"] = _verify_payout(payout)
    last_updated = plan.get("last_updated_at")
    if isinstance(last_updated, str) and last_updated.strip():
        verified["last_updated_at"] = last_updated.strip()
    return verified


def _verify_eligibility(eligibility: Mapping[str, Any]) -> dict[str, Any]:
    eligible = eligibility.get("eligible")
    if not isinstance(eligible, bool):
        raise ValueError("plan.eligibility.eligible must be a boolean")
    verified: dict[str, Any] = {"eligible": eligible}
    status = eligibility.get("status")
    if isinstance(status, str) and status.strip():
        verified["status"] = status.strip()
    reason = eligibility.get("reason")
    if isinstance(reason, str) and reason.strip():
        verified["reason"] = reason.strip()
    return verified


def _verify_payout(payout: Mapping[str, Any]) -> dict[str, Any]:
    verified: dict[str, Any] = {
        "amount": _required_int(payout.get("amount"), "plan.payout.amount"),
        "currency": _required(payout.get("currency"), "plan.payout.currency"),
    }
    payment_status = payout.get("payment_status")
    if isinstance(payment_status, str) and payment_status.strip():
        verified["payment_status"] = payment_status.strip()
    scheduled_date = payout.get("scheduled_date")
    if isinstance(scheduled_date, str) and scheduled_date.strip():
        verified["scheduled_date"] = scheduled_date.strip()
    return verified


def _verify_history(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    allowed = {"year", "amount", "currency", "status", "paid_at", "payment_reference"}
    history: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        entry = {key: deepcopy(item[key]) for key in allowed if key in item}
        if entry:
            history.append(entry)
    return history


def _recovery_reason(code: str) -> str:
    return {
        "BACKEND_INVALID_RESPONSE": "invalid_backend_response",
    }.get(code, "backend_unavailable")


def _response_intent(task: Mapping[str, Any]) -> str:
    if task.get("recovery") is not None or task.get("current_step") == "human_help":
        return "cash_sharing_recovery"
    if task.get("status") == "cancelled":
        return "cancelled"
    return "cash_sharing_summary"
