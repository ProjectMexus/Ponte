"""Composable execution pipeline for fixed MCP registry tools."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from MCP.errors import AdapterError
from MCP.registry import ToolRegistry
from MCP.rest_adapter import RestAdapter

from .contracts import ToolCall, ToolExecutionResult
from .mcp_client import McpStdioClient


class ExecutionStage(Protocol):
    """One composable stage in the middleware execution chain."""

    def handle(
        self,
        call: ToolCall,
        next_stage: Callable[[ToolCall], ToolExecutionResult],
    ) -> ToolExecutionResult:
        ...


class ExecutionPipeline:
    """Run stages in order using nested continuation calls."""

    def __init__(self, stages: Sequence[ExecutionStage]):
        self._stages = tuple(stages)

    def dispatch(self, call: ToolCall) -> ToolExecutionResult:
        def run(index: int, current_call: ToolCall) -> ToolExecutionResult:
            if index >= len(self._stages):
                raise RuntimeError("execution pipeline has no terminal stage")
            stage = self._stages[index]
            return stage.handle(
                current_call,
                lambda next_call: run(index + 1, next_call),
            )

        return run(0, call)


class DirectMcpExecutionStage:
    """Resolve a fixed tool definition and invoke the existing REST adapter."""

    def __init__(self, registry: ToolRegistry, adapter: RestAdapter):
        self._registry = registry
        self._adapter = adapter

    def handle(
        self,
        call: ToolCall,
        next_stage: Callable[[ToolCall], ToolExecutionResult],
    ) -> ToolExecutionResult:
        del next_stage
        try:
            definition = self._registry.get(call.name)
        except KeyError:
            request_id = _middleware_request_id()
            return ToolExecutionResult(
                tool_name=call.name,
                step_id=call.step_id,
                ok=False,
                request_id=request_id,
                error={
                    "code": "UNKNOWN_TOOL",
                    "message": "Tool is not present in the fixed registry.",
                    "status": 400,
                    "details": {"tool_name": call.name},
                    "retryable": False,
                },
            )

        try:
            payload = self._adapter.invoke(definition, call.arguments)
            if not isinstance(payload, dict):
                request_id = _middleware_request_id()
                return ToolExecutionResult(
                    tool_name=call.name,
                    step_id=call.step_id,
                    ok=False,
                    request_id=request_id,
                    error={
                        "code": "BACKEND_INVALID_RESPONSE",
                        "message": "Backend returned an invalid response.",
                        "status": 502,
                        "details": {"body_type": type(payload).__name__},
                        "retryable": False,
                    },
                )
            return ToolExecutionResult(
                tool_name=call.name,
                step_id=call.step_id,
                ok=True,
                request_id=_payload_request_id(payload),
                data=payload,
            )
        except AdapterError as error:
            return ToolExecutionResult(
                tool_name=call.name,
                step_id=call.step_id,
                ok=False,
                request_id=_error_request_id(error),
                error=error.to_dict(),
            )


class McpExecutionStage:
    """Resolve a fixed tool and invoke the real MCP stdio client."""

    def __init__(self, registry: ToolRegistry, client: McpStdioClient):
        self._registry = registry
        self._client = client

    def handle(
        self,
        call: ToolCall,
        next_stage: Callable[[ToolCall], ToolExecutionResult],
    ) -> ToolExecutionResult:
        del next_stage
        try:
            self._registry.get(call.name)
        except KeyError:
            request_id = _middleware_request_id()
            return ToolExecutionResult(
                tool_name=call.name,
                step_id=call.step_id,
                ok=False,
                request_id=request_id,
                error={
                    "code": "UNKNOWN_TOOL",
                    "message": "Tool is not present in the fixed registry.",
                    "status": 400,
                    "details": {"tool_name": call.name},
                    "retryable": False,
                },
            )

        try:
            payload = self._client.call_tool(call.name, call.arguments)
            if not isinstance(payload, dict):
                error = AdapterError(
                    code="MCP_PROTOCOL_ERROR",
                    message="MCP returned an invalid tool payload.",
                    status=502,
                    details={"body_type": type(payload).__name__},
                    retryable=False,
                )
                return ToolExecutionResult(
                    tool_name=call.name,
                    step_id=call.step_id,
                    ok=False,
                    request_id=_error_request_id(error),
                    error=error.to_dict(),
                )
            return ToolExecutionResult(
                tool_name=call.name,
                step_id=call.step_id,
                ok=True,
                request_id=_payload_request_id(payload),
                data=payload,
            )
        except AdapterError as error:
            return ToolExecutionResult(
                tool_name=call.name,
                step_id=call.step_id,
                ok=False,
                request_id=_error_request_id(error),
                error=error.to_dict(),
            )
        except Exception as error:
            internal_error = AdapterError(
                code="MCP_CLIENT_ERROR",
                message="MCP tool execution failed.",
                status=502,
                details={"type": type(error).__name__},
                retryable=False,
            )
            return ToolExecutionResult(
                tool_name=call.name,
                step_id=call.step_id,
                ok=False,
                request_id=_error_request_id(internal_error),
                error=internal_error.to_dict(),
            )


def _middleware_request_id() -> str:
    return f"REQ-MW-{uuid.uuid4().hex[:12].upper()}"


def _payload_request_id(payload: Mapping[str, Any]) -> str:
    request_id = payload.get("request_id")
    return request_id if isinstance(request_id, str) and request_id else _middleware_request_id()


def _error_request_id(error: AdapterError) -> str:
    details = error.details
    if isinstance(details, Mapping):
        request_id = details.get("request_id")
        if isinstance(request_id, str) and request_id:
            return request_id
    return _middleware_request_id()
