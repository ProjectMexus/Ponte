"""Newline-delimited JSON-RPC server for the Ponte MCP adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, TextIO

from .errors import AdapterError
from .registry import ToolRegistry


PROTOCOL_VERSION = "2025-03-26"


class MCPServer:
    """Handle the small MCP JSON-RPC surface used by Ponte clients."""

    def __init__(
        self,
        registry: ToolRegistry,
        adapter: Any,
        server_name: str = "ponte-mcp-adapter",
        server_version: str = "0.1.0",
    ) -> None:
        self.registry = registry
        self.adapter = adapter
        self.server_name = server_name
        self.server_version = server_version

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """Handle one decoded JSON-RPC message.

        Notifications are executed when applicable but never produce a response.
        Protocol and parameter errors are JSON-RPC errors; adapter failures are
        returned as MCP tool results with ``isError`` set to true.
        """

        if not isinstance(message, Mapping):
            return self._jsonrpc_error(None, -32602, "Invalid request")

        request_id = message.get("id")
        notification = "id" not in message

        def finish(response: dict[str, Any]) -> dict[str, Any] | None:
            return None if notification else response

        if message.get("jsonrpc") != "2.0":
            return finish(self._jsonrpc_error(request_id, -32602, "Invalid request"))

        method = message.get("method")
        if not isinstance(method, str):
            return finish(self._jsonrpc_error(request_id, -32602, "Invalid request"))

        if method == "notifications/initialized":
            return None

        if method == "initialize":
            params = message.get("params", {})
            if not isinstance(params, Mapping):
                return finish(self._jsonrpc_error(request_id, -32602, "Invalid params"))
            return finish(
                self._jsonrpc_result(
                    request_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {
                            "name": self.server_name,
                            "version": self.server_version,
                        },
                    },
                )
            )

        if method == "tools/list":
            params = message.get("params", {})
            if not isinstance(params, Mapping):
                return finish(self._jsonrpc_error(request_id, -32602, "Invalid params"))
            return finish(
                self._jsonrpc_result(
                    request_id,
                    {"tools": self.registry.list_mcp_tools()},
                )
            )

        if method == "tools/call":
            return finish(self._handle_tool_call(request_id, message))

        return finish(self._jsonrpc_error(request_id, -32601, "Method not found"))

    def run(self, stdin: TextIO, stdout: TextIO) -> None:
        """Process newline-delimited JSON-RPC messages from ``stdin``."""

        for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._write_response(
                    stdout,
                    self._jsonrpc_error(None, -32700, "Parse error"),
                )
                continue

            if not isinstance(message, Mapping):
                self._write_response(
                    stdout,
                    self._jsonrpc_error(None, -32602, "Invalid request"),
                )
                continue

            response = self.handle(message)
            if response is not None:
                self._write_response(stdout, response)

    def _handle_tool_call(
        self,
        request_id: Any,
        message: Mapping[str, Any],
    ) -> dict[str, Any]:
        params = message.get("params")
        if not isinstance(params, Mapping):
            return self._jsonrpc_error(request_id, -32602, "Invalid params")

        name = params.get("name")
        arguments = params.get("arguments")
        if not isinstance(name, str) or not name:
            return self._jsonrpc_error(request_id, -32602, "Invalid params")
        if not isinstance(arguments, Mapping):
            return self._jsonrpc_error(request_id, -32602, "Invalid params")

        try:
            definition = self.registry.get(name)
        except (KeyError, TypeError):
            return self._jsonrpc_error(request_id, -32602, "Unknown tool")

        try:
            payload = self.adapter.invoke(definition, arguments)
        except AdapterError as error:
            return self._jsonrpc_result(request_id, self._tool_error(error))
        except Exception as error:  # Keep implementation details out of JSON-RPC.
            internal_error = AdapterError(
                code="ADAPTER_INTERNAL_ERROR",
                message="Tool execution failed",
                status=500,
                details={
                    "type": type(error).__name__,
                    "message": str(error),
                },
                retryable=False,
            )
            return self._jsonrpc_result(request_id, self._tool_error(internal_error))

        return self._jsonrpc_result(request_id, self._tool_success(payload))

    @staticmethod
    def _tool_success(payload: Any) -> dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False),
                }
            ],
            "structuredContent": payload,
        }

    @staticmethod
    def _tool_error(error: AdapterError) -> dict[str, Any]:
        structured_content = {"error": error.to_dict()}
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(structured_content, ensure_ascii=False),
                }
            ],
            "structuredContent": structured_content,
            "isError": True,
        }

    @staticmethod
    def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _jsonrpc_error(
        request_id: Any,
        code: int,
        message: str,
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    @staticmethod
    def _write_response(stdout: TextIO, response: Mapping[str, Any]) -> None:
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
