"""Shared data models for the Ponte MCP tool adapter layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any

from .errors import InvalidToolArguments


_CONTEXT_KEYS = frozenset(
    {
        "mock_user_id",
        "patient_id",
        "authorization",
        "accept_language",
        "request_id",
        "idempotency_key",
    }
)


@dataclass(frozen=True)
class ContextRequirements:
    """Context values a tool needs in order to build a backend request."""

    mock_user_id: bool = False
    patient_id: bool = False
    authorization: bool = False
    idempotency_key: bool = False
    request_id: bool = False
    accept_language: bool = False


@dataclass(frozen=True)
class ToolContext:
    """Validated MCP context and tool input envelope."""

    context: Mapping[str, Any] = field(default_factory=dict)
    input: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, Any]) -> "ToolContext":
        """Validate and copy a tool call's ``context``/``input`` envelope."""

        if not isinstance(arguments, Mapping):
            raise InvalidToolArguments(
                "Tool arguments must be an object",
                details={"field": "arguments"},
            )

        for key in ("context", "input"):
            if key not in arguments:
                raise InvalidToolArguments(
                    f"Missing required field: {key}",
                    details={"field": key},
                )

        context = arguments["context"]
        input_value = arguments["input"]
        if not isinstance(context, Mapping):
            raise InvalidToolArguments(
                "context must be an object",
                details={"field": "context"},
            )
        if not isinstance(input_value, Mapping):
            raise InvalidToolArguments(
                "input must be an object",
                details={"field": "input"},
            )

        unknown_keys = sorted(set(context) - _CONTEXT_KEYS)
        if unknown_keys:
            raise InvalidToolArguments(
                "Unknown context keys",
                details={"keys": unknown_keys},
            )

        return cls(context=dict(context), input=dict(input_value))

    def to_headers(
        self,
        requirements: ContextRequirements,
        *,
        method: str,
    ) -> dict[str, str]:
        """Build only the backend headers permitted by the tool contract."""

        method = method.upper()
        headers: dict[str, str] = {}
        self._add_required_header(
            headers,
            context_key="mock_user_id",
            header_name="X-Mock-User-Id",
            required=requirements.mock_user_id,
        )
        self._add_required_header(
            headers,
            context_key="patient_id",
            header_name="X-Patient-Id",
            required=requirements.patient_id,
        )
        self._add_required_header(
            headers,
            context_key="authorization",
            header_name="Authorization",
            required=requirements.authorization,
        )
        self._add_required_header(
            headers,
            context_key="idempotency_key",
            header_name="Idempotency-Key",
            required=requirements.idempotency_key,
        )
        self._add_required_header(
            headers,
            context_key="request_id",
            header_name="X-Request-Id",
            required=requirements.request_id,
        )

        if requirements.accept_language:
            accept_language = self.context.get("accept_language", "zh-TW")
            if not isinstance(accept_language, str) or not accept_language:
                raise InvalidToolArguments(
                    "context.accept_language must be a non-empty string",
                    details={"field": "context.accept_language"},
                )
            headers["Accept-Language"] = accept_language

        return headers

    def _add_required_header(
        self,
        headers: dict[str, str],
        *,
        context_key: str,
        header_name: str,
        required: bool,
    ) -> None:
        if not required:
            return

        value = self.context.get(context_key)
        if not isinstance(value, str) or not value:
            raise InvalidToolArguments(
                f"Missing required context field: {context_key}",
                details={"field": f"context.{context_key}"},
            )
        headers[header_name] = value


@dataclass(frozen=True)
class RestRequest:
    """A controlled HTTP request created by the adapter."""

    method: str
    path: str
    query: Mapping[str, str] = field(default_factory=dict)
    body: Mapping[str, Any] | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
