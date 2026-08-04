"""Managed newline-delimited JSON-RPC client for Ponte's MCP server."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from MCP.errors import AdapterError
from ponte_logging import log_event


ProcessFactory = Callable[..., Any]


class McpClientError(AdapterError):
    """A safe error raised while communicating with the MCP child process."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int,
        details: Any = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status=status,
            details=details,
            retryable=retryable,
        )


class McpStdioClient:
    """Own one MCP server process and issue serialized JSON-RPC requests."""

    def __init__(
        self,
        backend_url: str,
        *,
        python_executable: str | None = None,
        project_root: str | Path | None = None,
        timeout: float = 10.0,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        if not isinstance(backend_url, str) or not backend_url.strip():
            raise ValueError("backend_url must be a non-empty string")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.backend_url = backend_url.rstrip("/")
        self.python_executable = python_executable or sys.executable
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
        self.timeout = timeout
        self._process_factory = process_factory or subprocess.Popen
        self._process: Any | None = None
        self._next_id = 1
        self._lock = Lock()

    @property
    def process(self) -> Any | None:
        """Return the managed process for diagnostics and integration tests."""

        return self._process

    def start(self) -> None:
        """Start the child and complete the MCP initialization handshake."""

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            command = [self.python_executable, "-m", "MCP"]
            environment = os.environ.copy()
            environment["PONTE_BACKEND_URL"] = self.backend_url
            initialize_id = self._next_id
            initialize_request_id = f"MCP-{initialize_id}"
            started_at = time.monotonic()
            try:
                process = self._process_factory(
                    command,
                    cwd=str(self.project_root),
                    env=environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                self._process = process
                log_event(
                    "mcp",
                    "send",
                    request_id=initialize_request_id,
                    operation="initialize",
                    input_keys="capabilities,clientInfo,protocolVersion",
                )
                response = self._request(
                    {
                        "jsonrpc": "2.0",
                        "id": initialize_id,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "ponte-middleware", "version": "0.1.0"},
                        },
                    },
                    expected_id=initialize_id,
                )
                self._next_id += 1
                result = response.get("result")
                if not isinstance(result, Mapping) or result.get("protocolVersion") != "2025-03-26":
                    raise self._protocol_error(
                        "MCP initialize response has an unsupported protocol version.",
                        details={"result": result},
                    )
                self._write({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                })
                log_event(
                    "mcp",
                    "receive",
                    request_id=initialize_request_id,
                    operation="initialize",
                    outcome="success",
                    latency_ms=self._latency_ms(started_at),
                )
            except AdapterError as error:
                log_event(
                    "mcp",
                    "error",
                    request_id=initialize_request_id,
                    operation="initialize",
                    outcome="error",
                    error_code=error.code,
                    latency_ms=self._latency_ms(started_at),
                )
                self._stop_process()
                raise
            except (OSError, ValueError, TypeError) as error:
                log_event(
                    "mcp",
                    "error",
                    request_id=initialize_request_id,
                    operation="initialize",
                    outcome="error",
                    error_type=type(error).__name__,
                    latency_ms=self._latency_ms(started_at),
                )
                self._stop_process()
                raise McpClientError(
                    "MCP_UNAVAILABLE",
                    "MCP server process could not be started.",
                    status=503,
                    details={"type": type(error).__name__, "message": str(error)},
                    retryable=True,
                ) from error
            except Exception as error:
                log_event(
                    "mcp",
                    "error",
                    request_id=initialize_request_id,
                    operation="initialize",
                    outcome="error",
                    error_type=type(error).__name__,
                    latency_ms=self._latency_ms(started_at),
                )
                self._stop_process()
                raise

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Call one MCP tool and return its structured content."""

        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        if not isinstance(arguments, Mapping):
            raise ValueError("arguments must be an object")
        if self._process is None:
            self.start()

        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                raise self._unavailable_error()
            request_id = self._next_id
            self._next_id += 1
            started_at = time.monotonic()
            try:
                log_event(
                    "mcp",
                    "send",
                    request_id=request_id,
                    operation="tools/call",
                    tool=name,
                    input_keys=",".join(sorted(str(key) for key in arguments)),
                )
                response = self._request(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": dict(arguments)},
                    },
                    expected_id=request_id,
                )
                result = response.get("result")
                if not isinstance(result, Mapping):
                    raise self._protocol_error(
                        "MCP tool response is missing result.",
                        details={"response": response},
                    )
                structured = result.get("structuredContent")
                if result.get("isError"):
                    raise self._tool_error(structured)
                if not isinstance(structured, dict):
                    raise self._protocol_error(
                        "MCP tool response is missing structuredContent.",
                        details={"result": dict(result)},
                    )
                log_event(
                    "mcp",
                    "receive",
                    request_id=request_id,
                    operation="tools/call",
                    tool=name,
                    outcome="success",
                    latency_ms=self._latency_ms(started_at),
                )
                return structured
            except BrokenPipeError as error:
                unavailable = self._unavailable_error()
                log_event(
                    "mcp",
                    "error",
                    request_id=request_id,
                    operation="tools/call",
                    tool=name,
                    outcome="error",
                    error_code=unavailable.code,
                    latency_ms=self._latency_ms(started_at),
                )
                raise unavailable from error
            except AdapterError as error:
                log_event(
                    "mcp",
                    "error",
                    request_id=request_id,
                    operation="tools/call",
                    tool=name,
                    outcome="error",
                    error_code=error.code,
                    latency_ms=self._latency_ms(started_at),
                )
                raise
            except Exception as error:
                log_event(
                    "mcp",
                    "error",
                    request_id=request_id,
                    operation="tools/call",
                    tool=name,
                    outcome="error",
                    error_type=type(error).__name__,
                    latency_ms=self._latency_ms(started_at),
                )
                raise

    def _latency_ms(self, started_at: float) -> float:
        return round((time.monotonic() - started_at) * 1000, 3)

    def close(self) -> None:
        """Stop the MCP child process; safe to call more than once."""

        with self._lock:
            self._stop_process()

    def _request(self, message: dict[str, Any], *, expected_id: int) -> dict[str, Any]:
        self._write(message)
        response = self._read_response()
        if not isinstance(response, dict):
            raise self._protocol_error("MCP response must be a JSON object.")
        if response.get("jsonrpc") != "2.0" or response.get("id") != expected_id:
            raise self._protocol_error(
                "MCP response did not match the request.",
                details={"expected_id": expected_id, "response": response},
            )
        if "error" in response:
            raise self._protocol_error(
                "MCP returned a JSON-RPC error.",
                details={"error": response.get("error")},
            )
        return response

    def _write(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise self._unavailable_error()
        process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def _read_response(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise self._unavailable_error()
        selector = selectors.DefaultSelector()
        try:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(self.timeout):
                raise McpClientError(
                    "MCP_TIMEOUT",
                    "MCP server did not respond before the timeout.",
                    status=504,
                    retryable=True,
                )
            raw = process.stdout.readline()
        except McpClientError:
            raise
        except (OSError, ValueError) as error:
            raise self._unavailable_error(
                details={"type": type(error).__name__, "message": str(error)},
            ) from error
        finally:
            selector.close()
        if raw == "":
            raise self._protocol_error("MCP server closed stdout unexpectedly.")
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise self._protocol_error(
                "MCP returned malformed JSON.",
                details={"message": str(error)},
            ) from error
        if not isinstance(value, dict):
            raise self._protocol_error("MCP response must be a JSON object.")
        return value

    def _tool_error(self, structured: Any) -> AdapterError:
        if not isinstance(structured, Mapping):
            return self._protocol_error(
                "MCP tool error is missing structured error content.",
                details={"structuredContent": structured},
            )
        error = structured.get("error")
        if not isinstance(error, Mapping):
            return self._protocol_error(
                "MCP tool error is missing an error object.",
                details={"structuredContent": dict(structured)},
            )
        code = error.get("code") if isinstance(error.get("code"), str) else "MCP_TOOL_ERROR"
        message = error.get("message") if isinstance(error.get("message"), str) else "MCP tool execution failed."
        status = error.get("status") if isinstance(error.get("status"), int) else 502
        return AdapterError(
            code=code,
            message=message,
            status=status,
            details=dict(error),
            retryable=bool(error.get("retryable", False)),
        )

    @staticmethod
    def _protocol_error(message: str, *, details: Any = None) -> McpClientError:
        return McpClientError(
            "MCP_PROTOCOL_ERROR",
            message,
            status=502,
            details=details,
            retryable=False,
        )

    @staticmethod
    def _unavailable_error(*, details: Any = None) -> McpClientError:
        return McpClientError(
            "MCP_UNAVAILABLE",
            "MCP server process is unavailable.",
            status=503,
            details=details,
            retryable=True,
        )

    def _stop_process(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        try:
            if process.stdout is not None:
                process.stdout.close()
        except (OSError, ValueError):
            pass
