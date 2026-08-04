"""Independent interpreter boundary for backend-result recovery guidance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from .contracts import RecoveryPlan


class TaskRecoveryInterpreter(Protocol):
    """Understand a sanitized backend result and return a validated recovery plan."""

    def interpret(
        self,
        *,
        error: Mapping[str, Any] | None,
        step_id: str,
        workflow: str,
        data: Mapping[str, Any],
        fallback: RecoveryPlan | None,
    ) -> RecoveryPlan | None:
        ...


class DeterministicTaskRecoveryInterpreter:
    """Default recovery interpreter used when no separate LLM client is configured."""

    def interpret(
        self,
        *,
        error: Mapping[str, Any] | None,
        step_id: str,
        workflow: str,
        data: Mapping[str, Any],
        fallback: RecoveryPlan | None,
    ) -> RecoveryPlan | None:
        del error, step_id, workflow, data
        return fallback
