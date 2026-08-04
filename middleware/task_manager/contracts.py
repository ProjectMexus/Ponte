"""Serializable values shared by task lifecycle and recovery adapters."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class RecoveryField:
    """A user-facing field that must be supplied before a task can continue."""

    name: str
    label: str
    input_type: str = "text"
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_string(self.name, "name"))
        object.__setattr__(self, "label", _required_string(self.label, "label"))
        object.__setattr__(self, "input_type", _required_string(self.input_type, "input_type"))
        if not isinstance(self.reason, str):
            raise ValueError("reason must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "input_type": self.input_type,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RecoveryOption:
    """One allowlisted action that can be offered to the user."""

    action: str
    label: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _required_string(self.action, "action"))
        object.__setattr__(self, "label", _required_string(self.label, "label"))
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be an object")
        object.__setattr__(self, "payload", deepcopy(dict(self.payload)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "label": self.label,
            "payload": deepcopy(dict(self.payload)),
        }


@dataclass(frozen=True)
class RecoveryPlan:
    """Validated, user-safe explanation and continuation options."""

    category: str
    reason_code: str
    explanation: str
    required_fields: tuple[RecoveryField, ...] = ()
    options: tuple[RecoveryOption, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _required_string(self.category, "category"))
        object.__setattr__(self, "reason_code", _required_string(self.reason_code, "reason_code"))
        object.__setattr__(self, "explanation", _required_string(self.explanation, "explanation"))
        fields = tuple(self.required_fields)
        options = tuple(self.options)
        if not all(isinstance(item, RecoveryField) for item in fields):
            raise ValueError("required_fields must contain RecoveryField values")
        if not all(isinstance(item, RecoveryOption) for item in options):
            raise ValueError("options must contain RecoveryOption values")
        object.__setattr__(self, "required_fields", fields)
        object.__setattr__(self, "options", options)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "reason_code": self.reason_code,
            "explanation": self.explanation,
            "required_fields": [field.to_dict() for field in self.required_fields],
            "options": [option.to_dict() for option in self.options],
        }
