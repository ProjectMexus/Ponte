"""Strict, registry-bound MCP diagnostic command helpers."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from MCP.registry import ToolRegistry

from .contracts import ToolCall


class DiagnosticCommandError(ValueError):
    """A safe, stable error raised while handling a diagnostic command."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class DiagnosticCommand:
    """An immutable diagnostic invocation parsed from frontend text."""

    tool_name: str
    input_data: dict[str, Any]

    @classmethod
    def parse(cls, message: str) -> "DiagnosticCommand | None":
        """Parse exactly ``mcp <tool-name> [<JSON object>]``.

        Ordinary messages are left for the natural-language recognizer. Once a
        message begins with the diagnostic prefix, malformed syntax is an
        explicit client error rather than a natural-language fallback.
        """

        if not isinstance(message, str):
            raise DiagnosticCommandError(
                "INVALID_DIAGNOSTIC_COMMAND",
                "診斷指令格式無效。",
            )
        if not message.startswith("mcp"):
            return None

        tokens = message.split(None, 2)
        if not tokens or tokens[0] != "mcp" or len(tokens) < 2:
            raise DiagnosticCommandError(
                "INVALID_DIAGNOSTIC_COMMAND",
                "診斷指令必須是 mcp <tool-name> [JSON object]。",
            )

        tool_name = tokens[1]
        if not tool_name:
            raise DiagnosticCommandError(
                "INVALID_DIAGNOSTIC_COMMAND",
                "診斷指令缺少 tool name。",
            )

        raw_input = tokens[2].strip() if len(tokens) == 3 else ""
        if not raw_input:
            input_data: dict[str, Any] = {}
        else:
            try:
                parsed_input = json.loads(raw_input)
            except (TypeError, json.JSONDecodeError):
                raise DiagnosticCommandError(
                    "INVALID_DIAGNOSTIC_COMMAND",
                    "診斷指令的 JSON input 無效。",
                ) from None
            if not isinstance(parsed_input, dict):
                raise DiagnosticCommandError(
                    "INVALID_DIAGNOSTIC_COMMAND",
                    "診斷指令的 JSON input 必須是 object。",
                )
            input_data = parsed_input

        return cls(tool_name, input_data)


def _definition_for(registry: ToolRegistry, tool_name: str):
    try:
        return registry.get(tool_name)
    except (KeyError, TypeError):
        raise DiagnosticCommandError(
            "UNKNOWN_DIAGNOSTIC_TOOL",
            "診斷 tool 不在固定 registry 內。",
        ) from None


def describe_diagnostic_command(
    registry: ToolRegistry,
    command: DiagnosticCommand,
) -> dict[str, Any]:
    """Validate a command against the fixed registry and expose its route."""

    definition = _definition_for(registry, command.tool_name)
    try:
        path = definition.path_for(command.input_data)
        method = definition.method.upper()
        risk_level = definition.risk_level
        input_schema = definition.input_schema["properties"]["input"]
        required_fields = input_schema.get("required", ())
    except (AttributeError, KeyError, TypeError, ValueError):
        raise DiagnosticCommandError(
            "INVALID_DIAGNOSTIC_ROUTE",
            "診斷 tool 的路徑參數無效。",
        ) from None

    missing_fields = [
        field_name
        for field_name in required_fields
        if field_name not in command.input_data
    ]
    if missing_fields:
        raise DiagnosticCommandError(
            "INVALID_DIAGNOSTIC_INPUT",
            "診斷 tool 缺少必要的 input 欄位。",
        )

    return {
        "tool_name": command.tool_name,
        "http_method": method,
        "path": path,
        "risk_level": risk_level,
    }


def diagnostic_requires_confirmation(
    registry: ToolRegistry,
    command: DiagnosticCommand,
) -> bool:
    """Return whether the registry method is state-changing."""

    definition = _definition_for(registry, command.tool_name)
    try:
        return definition.method.upper() != "GET"
    except AttributeError:
        raise DiagnosticCommandError(
            "INVALID_DIAGNOSTIC_TOOL",
            "診斷 tool metadata 無效。",
        ) from None


def build_diagnostic_call(
    command: DiagnosticCommand,
    context: Mapping[str, Any],
    step_id: str,
) -> ToolCall:
    """Build the existing controlled MCP envelope for a diagnostic call."""

    return ToolCall(
        command.tool_name,
        {
            "context": dict(context),
            "input": deepcopy(command.input_data),
        },
        step_id,
    )
