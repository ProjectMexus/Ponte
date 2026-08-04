import json
import os
import subprocess
import threading
import unittest

from MCP.errors import AdapterError
from middleware.mcp_client import McpClientError, McpStdioClient


class FakeProcess:
    def __init__(self, responses):
        self.responses = list(responses)
        self.writes = []
        self.returncode = None
        self.closed = False
        self._read_fd, self._write_fd = os.pipe()
        self.stdout = os.fdopen(self._read_fd, "r", encoding="utf-8")
        self.stdin = _FakeStdin(self)

    def factory(self, *args, **kwargs):
        self.args = args[0]
        self.kwargs = kwargs
        return self

    def respond_to(self, raw):
        message = json.loads(raw)
        if "id" not in message:
            return
        if not self.responses:
            return
        response = self.responses.pop(0)
        if response is None:
            os.close(self._write_fd)
            self._write_fd = -1
            return
        encoded = response if isinstance(response, str) else json.dumps(response)
        os.write(self._write_fd, (encoded + "\n").encode("utf-8"))

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self._close_pipe()

    def kill(self):
        self.returncode = -9
        self._close_pipe()

    def wait(self, timeout=None):
        del timeout
        if self.returncode is None:
            self.returncode = 0
        self._close_pipe()
        return self.returncode

    def _close_pipe(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.stdout.close()
        except OSError:
            pass
        if self._write_fd >= 0:
            os.close(self._write_fd)
            self._write_fd = -1


class _FakeStdin:
    def __init__(self, process):
        self.process = process
        self.closed = False

    def write(self, value):
        self.process.writes.append(value)
        self.process.respond_to(value)
        return len(value)

    def flush(self):
        return None

    def close(self):
        self.closed = True


def initialize_response(request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "ponte-mcp-adapter", "version": "0.1.0"},
        },
    }


class McpStdioClientTests(unittest.TestCase):
    def make_client(self, process, timeout=0.2):
        client = McpStdioClient(
            "http://127.0.0.1:8080",
            project_root=os.getcwd(),
            timeout=timeout,
            process_factory=process.factory,
        )
        self.addCleanup(client.close)
        return client

    def test_start_performs_initialize_and_initialized_notification(self):
        process = FakeProcess([initialize_response()])
        client = self.make_client(process)

        with self.assertLogs("ponte", level="INFO") as captured:
            client.start()

        self.assertEqual(json.loads(process.writes[0])["method"], "initialize")
        self.assertEqual(
            json.loads(process.writes[1])["method"],
            "notifications/initialized",
        )
        self.assertEqual(process.kwargs["env"]["PONTE_BACKEND_URL"], "http://127.0.0.1:8080")
        self.assertIs(process.kwargs["stderr"], subprocess.DEVNULL)
        output = "\n".join(captured.output)
        self.assertIn("operation=initialize", output)
        self.assertIn("request_id=MCP-1", output)
        self.assertIn("input_keys=capabilities,clientInfo,protocolVersion", output)
        self.assertIn("outcome=success", output)
        self.assertIn("latency_ms=", output)
        self.assertNotIn('"jsonrpc"', output)
        self.assertNotIn("2025-03-26", output)

    def test_call_tool_returns_structured_content(self):
        process = FakeProcess([
            initialize_response(),
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "content": [{"type": "text", "text": "{}"}],
                    "structuredContent": {
                        "request_id": "REQ-1",
                        "data": {"departments": []},
                    },
                },
            },
        ])
        client = self.make_client(process)

        with self.assertLogs("ponte", level="INFO") as captured:
            result = client.call_tool(
                "medical.list_departments",
                {
                    "context": {"authorization": "PATIENT_SECRET"},
                    "input": {"marker": "PATIENT_INPUT_SECRET"},
                },
            )

        self.assertEqual(result, {"request_id": "REQ-1", "data": {"departments": []}})
        self.assertEqual(json.loads(process.writes[2])["params"]["name"], "medical.list_departments")
        output = "\n".join(captured.output)
        self.assertIn("operation=tools/call", output)
        self.assertIn("request_id=2", output)
        self.assertIn("tool=medical.list_departments", output)
        self.assertIn("input_keys=context,input", output)
        self.assertIn("outcome=success", output)
        self.assertIn("latency_ms=", output)
        self.assertNotIn("PATIENT_SECRET", output)
        self.assertNotIn("PATIENT_INPUT_SECRET", output)
        self.assertNotIn('"jsonrpc"', output)
        self.assertNotIn("arguments=", output)
        self.assertNotIn("response=", output)
        self.assertNotIn("details=", output)

    def test_call_tool_maps_mcp_tool_error_to_adapter_error(self):
        process = FakeProcess([
            initialize_response(),
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "isError": True,
                    "structuredContent": {
                        "error": {
                            "code": "SLOT_NOT_AVAILABLE",
                            "message": "所選時段已滿",
                            "status": 409,
                            "retryable": False,
                        },
                    },
                },
            },
        ])
        client = self.make_client(process)

        with self.assertLogs("ponte", level="INFO") as captured:
            with self.assertRaises(AdapterError) as raised:
                client.call_tool(
                    "medical.create_registration",
                    {
                        "context": {},
                        "input": {"marker": "PATIENT_SECRET"},
                    },
                )

        self.assertEqual(raised.exception.code, "SLOT_NOT_AVAILABLE")
        self.assertEqual(raised.exception.status, 409)
        output = "\n".join(captured.output)
        self.assertIn("operation=tools/call", output)
        self.assertIn("request_id=2", output)
        self.assertIn("tool=medical.create_registration", output)
        self.assertIn("input_keys=context,input", output)
        self.assertIn("outcome=error", output)
        self.assertIn("error_code=SLOT_NOT_AVAILABLE", output)
        self.assertIn("latency_ms=", output)
        self.assertNotIn("PATIENT_SECRET", output)
        self.assertNotIn("所選時段已滿", output)
        self.assertNotIn('"jsonrpc"', output)
        self.assertNotIn("arguments=", output)
        self.assertNotIn("response=", output)
        self.assertNotIn("details=", output)

    def test_start_logs_unexpected_error_type_without_exception_message(self):
        def failing_factory(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("PATIENT_STARTUP_SECRET")

        client = McpStdioClient(
            "http://127.0.0.1:8080",
            project_root=os.getcwd(),
            process_factory=failing_factory,
        )
        self.addCleanup(client.close)

        with self.assertLogs("ponte", level="INFO") as captured:
            with self.assertRaises(RuntimeError):
                client.start()

        output = "\n".join(captured.output)
        self.assertIn("operation=initialize", output)
        self.assertIn("request_id=MCP-1", output)
        self.assertIn("outcome=error", output)
        self.assertIn("error_type=RuntimeError", output)
        self.assertIn("latency_ms=", output)
        self.assertNotIn("PATIENT_STARTUP_SECRET", output)
        self.assertNotIn('"jsonrpc"', output)
        self.assertNotIn("details=", output)

    def test_client_rejects_malformed_response(self):
        process = FakeProcess([initialize_response(), "not-json"])
        client = self.make_client(process)

        with self.assertRaises(McpClientError) as raised:
            client.call_tool("medical.list_departments", {"context": {}, "input": {}})

        self.assertEqual(raised.exception.code, "MCP_PROTOCOL_ERROR")

    def test_client_rejects_mismatched_response_id(self):
        process = FakeProcess([
            initialize_response(),
            {"jsonrpc": "2.0", "id": 999, "result": {}},
        ])
        client = self.make_client(process)

        with self.assertRaises(McpClientError) as raised:
            client.call_tool("medical.list_departments", {"context": {}, "input": {}})

        self.assertEqual(raised.exception.code, "MCP_PROTOCOL_ERROR")

    def test_client_rejects_eof(self):
        process = FakeProcess([initialize_response(), None])
        client = self.make_client(process)

        with self.assertRaises(McpClientError) as raised:
            client.call_tool("medical.list_departments", {"context": {}, "input": {}})

        self.assertEqual(raised.exception.code, "MCP_PROTOCOL_ERROR")

    def test_client_times_out_when_process_does_not_reply(self):
        process = FakeProcess([initialize_response()])
        client = self.make_client(process, timeout=0.03)

        with self.assertRaises(McpClientError) as raised:
            client.call_tool("medical.list_departments", {"context": {}, "input": {}})

        self.assertEqual(raised.exception.code, "MCP_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
