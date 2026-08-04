import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from middleware.server import create_application, create_http_server


class RecordingMcpClient:
    def __init__(self):
        self.closed = False
        self.calls = []

    def start(self):
        return None

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"request_id": "REQ-TEST", "data": {"departments": []}}

    def close(self):
        self.closed = True


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mcp_client = RecordingMcpClient()
        cls.application = create_application(
            "http://backend.test",
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            mcp_client=cls.mcp_client,
        )
        cls.server = create_http_server("127.0.0.1", 0, cls.application)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with self.opener.open(request) as response:
            return response.status, json.loads(response.read())

    def test_tools_endpoint_returns_registry(self):
        status, payload = self.request("GET", "/api/mcp/tools")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["tools"]), 21)

    def test_server_close_closes_mcp_client(self):
        self.application.close()
        self.assertTrue(self.mcp_client.closed)

    def test_diagnostic_read_message_returns_contract_and_tool_event(self):
        status, payload = self.request("POST", "/api/interactions/message", {
            "session_id": "S-SERVER-DIAG-GET",
            "message": "mcp medical.list_departments {}",
            "source": "text",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "mcp_diagnostic")
        self.assertEqual(payload["data"]["diagnostic"]["http_method"], "GET")
        self.assertEqual(payload["tool_events"][0]["tool_name"], "medical.list_departments")

    def test_diagnostic_post_requires_confirm_action(self):
        status, payload = self.request("POST", "/api/interactions/message", {
            "session_id": "S-SERVER-DIAG-POST",
            "message": (
                'mcp one_account.book_government_service_center_queue '
                '{"service_center_id":"GSC-MAIN",'
                '"service_type":"general_counter","requested_date":"2026-08-20",'
                '"confirmation":{"confirmation_id":"DEMO-CONF"}}'
            ),
            "source": "text",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["task_state"], "awaiting_confirmation")
        self.assertEqual(payload["tool_events"], [])
        self.assertEqual(payload["actions"][0]["kind"], "confirm_tool")

        status, confirmed = self.request("POST", "/api/interactions/action", {
            "session_id": "S-SERVER-DIAG-POST",
            "action": "confirm_tool",
            "payload": {"tool_name": "medical.list_departments"},
        })
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["task_state"], "completed")
        self.assertEqual(
            confirmed["tool_events"][0]["tool_name"],
            "one_account.book_government_service_center_queue",
        )

    def test_low_level_non_get_tool_call_requires_confirmation(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("POST", "/api/mcp/tools/call", {
                "name": "one_account.book_government_service_center_queue",
                "arguments": {"context": {}, "input": {}},
            })
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(
            json.loads(raised.exception.read())["error"]["code"],
            "CONFIRMATION_REQUIRED",
        )

    def test_malformed_diagnostic_command_is_client_error(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("POST", "/api/interactions/message", {
                "session_id": "S-SERVER-DIAG-BAD",
                "message": "mcp medical.list_departments {",
                "source": "text",
            })
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(
            json.loads(raised.exception.read())["error"]["code"],
            "INVALID_DIAGNOSTIC_COMMAND",
        )

    def test_message_workflow_passes_mock_user_id_to_mcp_context(self):
        status, payload = self.request("POST", "/api/interactions/message", {
            "session_id": "S-SERVER-CASH",
            "message": "我想查現金分享計劃",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["task_state"], "completed")
        self.assertEqual(self.mcp_client.calls[-1][0], "one_account.get_cash_sharing_plan")
        self.assertEqual(
            self.mcp_client.calls[-1][1]["context"]["mock_user_id"],
            "USR-DEMO-001",
        )

    def test_malformed_json_is_safe_client_error(self):
        request = Request(self.base_url + "/api/interactions/message", data=b"{", method="POST", headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as raised:
            self.opener.open(request)
        self.assertEqual(raised.exception.code, 400)
        error_body = json.loads(raised.exception.read())
        self.assertNotIn("traceback", json.dumps(error_body).lower())


if __name__ == "__main__":
    unittest.main()
