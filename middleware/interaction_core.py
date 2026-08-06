"""Task-oriented interaction routing independent of domain workflow details."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .intent import IntentDecision, IntentRecognizer, build_intent_recognizer
from .interaction_contracts import CanonicalInteractionResult, EventEnvelope
from .medical_workflow import MedicalWorkflow, WorkflowResult
from .session import SessionState, SessionStore


class InteractionCore:
    """Load one active task, select its workflow, and persist its result."""

    def __init__(
        self,
        sessions: SessionStore,
        medical_workflow: MedicalWorkflow,
        *,
        intent_recognizer: IntentRecognizer | None = None,
        cash_workflow: Any | None = None,
    ) -> None:
        self.sessions = sessions
        self.medical_workflow = medical_workflow
        self.cash_workflow = cash_workflow
        self.intent_recognizer = intent_recognizer or build_intent_recognizer()

    def handle(self, envelope: EventEnvelope) -> CanonicalInteractionResult:
        if not isinstance(envelope, EventEnvelope):
            raise ValueError("envelope must be an EventEnvelope")
        state = self.sessions.get_or_create(envelope.session_id)
        if envelope.event.get("type") == "user_utterance":
            outcome = self._handle_utterance(state, envelope)
        else:
            task = self._active_task(state)
            outcome = self._workflow_for_task(task).handle(deepcopy(task), envelope)
        return self._save(state, outcome)

    def _handle_utterance(self, state: SessionState, envelope: EventEnvelope) -> WorkflowResult:
        task = state.task
        if isinstance(task, Mapping) and task.get("status") not in {"completed", "cancelled", "failed"}:
            return self._workflow_for_task(task).handle(deepcopy(dict(task)), envelope)
        content = envelope.event.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("event.content must be a non-empty string")
        decision = self.intent_recognizer.recognize(content.strip())
        return self._workflow_for_intent(decision).start(envelope, decision)

    def _workflow_for_intent(self, decision: IntentDecision) -> Any:
        if decision.is_medical:
            return self.medical_workflow
        if decision.is_cash_sharing and self.cash_workflow is not None:
            return self.cash_workflow
        raise ValueError("unsupported interaction intent")

    def _workflow_for_task(self, task: Mapping[str, Any]) -> Any:
        task_type = task.get("type")
        if task_type == "medical_appointment":
            return self.medical_workflow
        if task_type == "cash_sharing_query" and self.cash_workflow is not None:
            return self.cash_workflow
        raise ValueError("unsupported task type")

    @staticmethod
    def _active_task(state: SessionState) -> dict[str, Any]:
        if not isinstance(state.task, dict):
            raise ValueError("task does not exist")
        return state.task

    def _save(self, state: SessionState, outcome: WorkflowResult) -> CanonicalInteractionResult:
        task, result, log_entries = outcome
        if not isinstance(task, dict) or not isinstance(result, CanonicalInteractionResult):
            raise ValueError("workflow returned an invalid result")
        state.active_task_id = task.get("task_id")
        state.task = deepcopy(task)
        state.interaction_log.extend(deepcopy(log_entries))
        self.sessions.save(state)
        return result
