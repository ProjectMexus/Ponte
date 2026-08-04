"""Allowed task lifecycle transitions."""

from __future__ import annotations

from typing import Final


TERMINAL_TASK_STATES: Final = frozenset({
    "completed",
    "cancelled",
    "failed",
    "human_handoff",
})

_ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "idle": frozenset({
        "idle",
        "querying",
        "awaiting_confirmation",
        "awaiting_user_input",
        "completed",
        "cancelled",
        "failed",
        "human_handoff",
    }),
    "querying": frozenset({
        "querying",
        "selecting_service",
        "selecting_slot",
        "awaiting_confirmation",
        "awaiting_user_input",
        "submitted",
        "completed",
        "cancelled",
        "failed",
        "human_handoff",
    }),
    "selecting_service": frozenset({
        "querying",
        "selecting_service",
        "selecting_slot",
        "awaiting_user_input",
        "cancelled",
        "failed",
        "human_handoff",
    }),
    "selecting_slot": frozenset({
        "querying",
        "selecting_slot",
        "awaiting_confirmation",
        "awaiting_user_input",
        "cancelled",
        "failed",
        "human_handoff",
    }),
    "awaiting_confirmation": frozenset({
        "querying",
        "submitting",
        "awaiting_confirmation",
        "awaiting_user_input",
        "cancelled",
        "failed",
        "human_handoff",
    }),
    "submitting": frozenset({
        "submitting",
        "submitted",
        "awaiting_user_input",
        "completed",
        "failed",
        "human_handoff",
    }),
    "submitted": frozenset({
        "submitted",
        "querying",
        "awaiting_user_input",
        "completed",
        "failed",
        "human_handoff",
    }),
    "awaiting_user_input": frozenset({
        "querying",
        "selecting_service",
        "selecting_slot",
        "awaiting_confirmation",
        "submitting",
        "submitted",
        "awaiting_user_input",
        "completed",
        "cancelled",
        "failed",
        "human_handoff",
    }),
    "error": frozenset(),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
    "human_handoff": frozenset(),
}


class InvalidTaskTransition(ValueError):
    """Raised when a task attempts to move to an invalid lifecycle state."""


def ensure_transition(current: str, target: str) -> None:
    """Raise InvalidTaskTransition unless target is allowed from current."""

    if not isinstance(current, str) or not isinstance(target, str):
        raise InvalidTaskTransition("task states must be strings")
    allowed = _ALLOWED_TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidTaskTransition(f"unknown current task state: {current}")
    if target not in _ALLOWED_TRANSITIONS:
        raise InvalidTaskTransition(f"unknown target task state: {target}")
    if target not in allowed:
        raise InvalidTaskTransition(f"cannot transition task from {current} to {target}")
