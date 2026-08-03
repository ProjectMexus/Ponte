import json
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path

from MCP.tests.fixture_backend import FixtureBackend


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MCPProcess:
    def __init__(self, backend_url: str):
        env = os.environ.copy()
        env["PONTE_BACKEND_URL"] = backend_url
        self.process = subprocess.Popen(
            [sys.executable, "-m", "MCP"],
            cwd=PROJECT_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def call(self, message: dict) -> dict:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        response = self.process.stdout.readline()
        if not response:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise AssertionError(f"MCP process exited without response: {stderr}")
        return json.loads(response)

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


class MCPStdioSmokeTests(unittest.TestCase):
    def test_initialize_list_and_post_tool_reach_backend(self):
        with FixtureBackend() as backend:
            process = MCPProcess(backend.base_url)
            try:
                initialize = process.call({
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}},
                })
                self.assertEqual(initialize["result"]["serverInfo"]["name"], "ponte-mcp-adapter")

                listed = process.call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                self.assertEqual(len(listed["result"]["tools"]), 21)

                called = process.call({
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {
                        "name": "one_account.submit_activity_registration",
                        "arguments": {
                            "context": {"mock_user_id": "USR-DEMO-001", "request_id": "REQ-SMOKE-1", "idempotency_key": "KEY-SMOKE-1"},
                            "input": {"activity_id": "ACT-1", "form_id": "FORM-1", "participant": {}, "consents": {"personal_data": True}, "confirmation": {"confirmed": True}},
                        },
                    },
                })
                self.assertFalse(called["result"].get("isError", False))
                request = backend.requests[-1]
                self.assertEqual(request["method"], "POST")
                self.assertEqual(request["path"], "/mock/elderly-activities/v1/registrations")
                self.assertEqual(request["headers"]["X-Mock-User-Id"], "USR-DEMO-001")
                self.assertEqual(request["headers"]["Idempotency-Key"], "KEY-SMOKE-1")
                self.assertEqual(request["body"]["activity_id"], "ACT-1")
            finally:
                process.close()

    def test_backend_conflict_is_returned_as_mcp_tool_error(self):
        with FixtureBackend() as backend:
            process = MCPProcess(backend.base_url)
            try:
                response = process.call({
                    "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {
                        "name": "medical.create_registration",
                        "arguments": {
                            "context": {"authorization": "Bearer mock-user-token", "patient_id": "P-10001", "idempotency_key": "KEY-CONFLICT"},
                            "input": {"patient_id": "P-10001", "department_id": "CARDIO", "slot_id": "SLOT-CONFLICT", "consent": True},
                        },
                    },
                })
                self.assertTrue(response["result"]["isError"])
                self.assertEqual(response["result"]["structuredContent"]["error"]["code"], "SLOT_NOT_AVAILABLE")
            finally:
                process.close()

    def test_malformed_backend_response_is_reported(self):
        with FixtureBackend() as backend:
            backend.return_malformed_once()
            process = MCPProcess(backend.base_url)
            try:
                response = process.call({
                    "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {"name": "medical.list_departments", "arguments": {"context": {"authorization": "Bearer mock-user-token"}, "input": {}}},
                })
                self.assertTrue(response["result"]["isError"])
                self.assertEqual(response["result"]["structuredContent"]["error"]["code"], "BACKEND_INVALID_RESPONSE")
            finally:
                process.close()

    def test_unavailable_backend_is_reported(self):
        process = MCPProcess(f"http://127.0.0.1:{_unused_port()}")
        try:
            response = process.call({
                "jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {"name": "medical.list_departments", "arguments": {"context": {"authorization": "Bearer mock-user-token"}, "input": {}}},
            })
            self.assertTrue(response["result"]["isError"])
            self.assertEqual(response["result"]["structuredContent"]["error"]["code"], "BACKEND_UNAVAILABLE")
        finally:
            process.close()


if __name__ == "__main__":
    unittest.main()
