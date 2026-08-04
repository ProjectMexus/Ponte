"""In-memory interaction session state and response serialization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Sequence

from .contracts import ToolCall


@dataclass
class SessionState:
    """Mutable state for one browser interaction session."""

    session_id: str
    task_state: str = "idle"
    current_step: str = "welcome"
    data: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    last_tool_call: ToolCall | None = None
    confirmation_record: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None


class SessionStore:
    """Thread-safe in-memory store for session objects."""

    def __init__(self) -> None:
        self._states: dict[str, SessionState] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str) -> SessionState:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        normalized = session_id.strip()
        with self._lock:
            state = self._states.get(normalized)
            if state is None:
                state = SessionState(normalized)
                self._states[normalized] = state
            return state

    def save(self, state: SessionState) -> None:
        if not isinstance(state, SessionState):
            raise ValueError("state must be a SessionState")
        if not isinstance(state.session_id, str) or not state.session_id.strip():
            raise ValueError("state.session_id must be a non-empty string")
        with self._lock:
            self._states[state.session_id] = state


def build_response(
    state: SessionState,
    assistant_message: str,
    actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a JSON-safe copy of the public interaction response."""

    public_actions: list[dict[str, Any]] = []
    for action in actions:
        public_action = deepcopy(dict(action))
        if "kind" not in public_action and isinstance(public_action.get("action"), str):
            public_action["kind"] = public_action["action"]
        public_actions.append(public_action)

    response: dict[str, Any] = {
        "session_id": state.session_id,
        "assistant_message": assistant_message,
        "task_state": state.task_state,
        "current_step": state.current_step,
        "steps": deepcopy(state.steps),
        "tool_events": deepcopy(state.tool_events),
        "actions": public_actions,
        "data": deepcopy(state.data),
    }
    if state.last_error is not None:
        response["error"] = deepcopy(state.last_error)
    return response
