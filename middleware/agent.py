"""Registry-driven LLM decision loop with risk-aware tool execution."""

from __future__ import annotations

import copy
import json
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from MCP.registry import ToolRegistry

from .contracts import AgentRunResult, PendingToolProposal, ToolCall, ToolExecutionResult
from .llm_transport import ChatCompletionClient, ChatCompletionError, assistant_message, strict_json_content


class ContextualExecutor(Protocol):
    def dispatch(
        self,
        call: ToolCall,
        context: Mapping[str, Any],
    ) -> ToolExecutionResult:
        ...


class AgentProtocolError(RuntimeError):
    """Raised when a model decision does not match the closed agent protocol."""


@dataclass(frozen=True)
class AgentDecision:
    action: Literal["respond", "clarify", "tool_call"]
    message: str | None = None
    tool_name: str | None = None
    arguments: Mapping[str, Any] | None = None


def project_registry_tools(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Project every fixed tool while withholding the trusted context schema."""

    projected: list[dict[str, Any]] = []
    for name in registry.names():
        definition = registry.get(name)
        envelope = definition.input_schema
        properties = envelope.get("properties")
        input_schema = properties.get("input") if isinstance(properties, Mapping) else None
        if not isinstance(input_schema, Mapping):
            raise ValueError(f"registry tool {name} has no input schema")
        projected.append({
            "type": "function",
            "function": {
                "name": name,
                "description": definition.description,
                "parameters": copy.deepcopy(dict(input_schema)),
            },
        })
    return projected


def _parse_direct_decision(payload: Mapping[str, Any]) -> AgentDecision:
    action = payload.get("action")
    if action in ("respond", "clarify"):
        if set(payload) != {"action", "message"}:
            raise AgentProtocolError("response decisions require only action and message")
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise AgentProtocolError("decision message must be a non-empty string")
        return AgentDecision(action, message=message.strip())
    if action == "tool_call":
        if set(payload) != {"action", "tool_name", "arguments"}:
            raise AgentProtocolError("tool decisions require action, tool_name, and arguments")
        name = payload.get("tool_name")
        arguments = payload.get("arguments")
        if not isinstance(name, str) or not name.strip():
            raise AgentProtocolError("tool_name must be a non-empty string")
        if not isinstance(arguments, Mapping):
            raise AgentProtocolError("tool arguments must be an object")
        return AgentDecision("tool_call", tool_name=name.strip(), arguments=dict(arguments))
    raise AgentProtocolError("unsupported agent action")


def parse_agent_decision(response: Mapping[str, Any]) -> AgentDecision:
    """Parse either a native single tool call or a strict JSON action."""

    if "action" in response:
        return _parse_direct_decision(response)
    message = assistant_message(response)
    tool_calls = message.get("tool_calls")
    if tool_calls is not None:
        if not isinstance(tool_calls, list) or len(tool_calls) != 1:
            raise AgentProtocolError("agent must request exactly one tool at a time")
        tool_call = tool_calls[0]
        function = tool_call.get("function") if isinstance(tool_call, Mapping) else None
        if not isinstance(function, Mapping):
            raise AgentProtocolError("tool call has no function")
        name = function.get("name")
        arguments_text = function.get("arguments")
        if not isinstance(name, str) or not name.strip() or not isinstance(arguments_text, str):
            raise AgentProtocolError("tool call function is invalid")
        try:
            arguments = json.loads(arguments_text)
        except json.JSONDecodeError as error:
            raise AgentProtocolError("tool arguments must be strict JSON") from error
        if not isinstance(arguments, Mapping):
            raise AgentProtocolError("tool arguments must be an object")
        return AgentDecision("tool_call", tool_name=name.strip(), arguments=dict(arguments))
    try:
        return _parse_direct_decision(strict_json_content(response))
    except ChatCompletionError as error:
        raise AgentProtocolError(str(error)) from error


class RegistryDrivenAgent:
    """Run up to four model decisions, auto-executing only R0 tools."""

    SYSTEM_PROMPT = (
        "You are Ponte's task agent. Return strict JSON with exactly one of: "
        '{"action":"respond","message":"..."}, '
        '{"action":"clarify","message":"..."}, or call exactly one provided tool. '
        "Never invent tools. Tool parameters contain user input only; trusted identity, "
        "authorization, locale, request IDs, and idempotency values are supplied by the server."
    )

    def __init__(
        self,
        registry: ToolRegistry,
        client: ChatCompletionClient,
        executor: ContextualExecutor,
        *,
        max_decisions: int = 4,
        clock: Any = time.time,
    ) -> None:
        if isinstance(max_decisions, bool) or not isinstance(max_decisions, int):
            raise ValueError("max_decisions must be an integer")
        if not 1 <= max_decisions <= 4:
            raise ValueError("max_decisions must be between 1 and 4")
        self.registry = registry
        self.client = client
        self.executor = executor
        self.max_decisions = max_decisions
        self.clock = clock
        self.tools = project_registry_tools(registry)

    def run(
        self,
        user_message: str,
        *,
        history: Sequence[Mapping[str, Any]] = (),
        context: Mapping[str, Any] | None = None,
    ) -> AgentRunResult:
        if not isinstance(user_message, str) or not user_message.strip():
            raise ValueError("user_message must be a non-empty string")
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        messages.extend(self._safe_history(history))
        messages.append({"role": "user", "content": user_message.strip()})
        trusted_context = dict(context or {})
        results: list[ToolExecutionResult] = []

        for decision_number in range(1, self.max_decisions + 1):
            try:
                response = self.client.complete(
                    messages,
                    tools=self.tools,
                    tool_choice="auto",
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                decision = parse_agent_decision(response)
            except (AgentProtocolError, ChatCompletionError, TypeError, ValueError):
                return AgentRunResult(
                    "clarify",
                    "I could not safely interpret that request. Please rephrase it.",
                    decision_number,
                    tuple(results),
                )

            if decision.action in ("respond", "clarify"):
                return AgentRunResult(
                    decision.action,
                    decision.message or "",
                    decision_number,
                    tuple(results),
                )

            assert decision.tool_name is not None and decision.arguments is not None
            try:
                definition = self.registry.get(decision.tool_name)
            except KeyError:
                return AgentRunResult(
                    "clarify",
                    "I could not safely match that request to an available service.",
                    decision_number,
                    tuple(results),
                )
            if definition.risk_level in ("R1", "R2"):
                proposal = PendingToolProposal.create(
                    definition.name,
                    decision.arguments,
                    definition.risk_level,
                    now=self.clock(),
                )
                return AgentRunResult(
                    "pending_approval",
                    f"Please confirm whether to execute {definition.name}.",
                    decision_number,
                    tuple(results),
                    proposal,
                )
            if definition.risk_level != "R0":
                return AgentRunResult(
                    "clarify",
                    "The requested service has an unsupported risk classification.",
                    decision_number,
                    tuple(results),
                )

            step_id = f"agent-{decision_number}-{uuid.uuid4().hex[:10]}"
            call = ToolCall(definition.name, decision.arguments, step_id)
            result = self.executor.dispatch(call, trusted_context)
            results.append(result)
            messages.extend(self._tool_exchange(call, result))

        return AgentRunResult(
            "limit_reached",
            "I reached the service-step limit. Please continue in a new message.",
            self.max_decisions,
            tuple(results),
        )

    @staticmethod
    def _safe_history(history: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        safe: list[dict[str, str]] = []
        for message in history:
            if not isinstance(message, Mapping):
                raise ValueError("history messages must be objects")
            if set(message) != {"role", "content"}:
                raise ValueError("history messages require only role and content")
            role = message.get("role")
            content = message.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                raise ValueError("history roles must be user or assistant")
            safe.append({"role": role, "content": content})
        return safe

    @staticmethod
    def _tool_exchange(call: ToolCall, result: ToolExecutionResult) -> list[dict[str, Any]]:
        tool_call_id = call.step_id
        return [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(dict(call.arguments), ensure_ascii=False),
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result.to_dict(), ensure_ascii=False),
            },
        ]
