import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from frontend.server import create_http_server as create_frontend_http_server
from middleware.intent import KeywordIntentRecognizer
from middleware.server import create_application, create_http_server
from mock_backends.server import create_http_server as create_backend_http_server


class FullStackIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.backend = create_backend_http_server(
            "127.0.0.1",
            0,
            Path(self.tempdir.name),
        )
        self.backend_thread = threading.Thread(
            target=self.backend.serve_forever,
            daemon=True,
        )
        self.backend_thread.start()

        self.middleware_app = create_application(
            f"http://127.0.0.1:{self.backend.server_port}",
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        self.middleware = create_http_server(
            "127.0.0.1",
            0,
            self.middleware_app,
        )
        self.middleware_thread = threading.Thread(
            target=self.middleware.serve_forever,
            daemon=True,
        )
        self.middleware_thread.start()

        self.frontend = create_frontend_http_server("127.0.0.1", 0, Path("frontend"))
        self.frontend_thread = threading.Thread(
            target=self.frontend.serve_forever,
            daemon=True,
        )
        self.frontend_thread.start()
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        for server, thread in (
            (self.frontend, self.frontend_thread),
            (self.middleware, self.middleware_thread),
            (self.backend, self.backend_thread),
        ):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.tempdir.cleanup()

    def get(self, path):
        with self.opener.open(
            f"http://127.0.0.1:{self.frontend.server_port}{path}"
        ) as response:
            return response.read().decode("utf-8")

    def get_middleware(self, path):
        with self.opener.open(
            f"http://127.0.0.1:{self.middleware.server_port}{path}"
        ) as response:
            return json.loads(response.read())

    def post_middleware(self, path, body):
        request = Request(
            f"http://127.0.0.1:{self.middleware.server_port}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.opener.open(request) as response:
            return json.loads(response.read())

    def test_frontend_to_mcp_to_backend_message_flow(self):
        html = self.get("/")
        client_js = self.get("/mcp-client.js")
        health = self.get_middleware("/api/health")
        response = self.post_middleware(
            "/api/interactions/message",
            {
                "session_id": "BROWSER-SMOKE-1",
                "message": "我想查詢自己的醫療預約",
                "source": "text",
            },
        )

        self.assertIn("公共服務助手", html)
        self.assertIn("MiddlewareClient", client_js)
        self.assertTrue(health["backend_reachable"])
        self.assertEqual(response["task_state"], "completed")
        self.assertEqual(
            [event["tool_name"] for event in response["tool_events"]],
            ["medical.get_my_appointments"],
        )

        process = self.middleware_app.mcp_client.process
        self.assertIsNotNone(process)
        self.assertIsNone(process.poll())
        self.assertEqual(process.args[1:3], ["-m", "MCP"])

    def test_natural_language_cash_sharing_reaches_backend(self):
        response = self.post_middleware(
            "/api/interactions/message",
            {
                "session_id": "FULL-CASH-1",
                "message": "我想查現金分享計劃",
                "source": "text",
            },
        )
        self.assertEqual(response["task_state"], "completed")
        self.assertEqual(
            [event["tool_name"] for event in response["tool_events"]],
            ["one_account.get_cash_sharing_plan"],
        )
        self.assertEqual(response["data"]["cash_sharing_plan"]["plan"]["year"], 2026)

    def test_natural_language_activity_search_reaches_backend(self):
        response = self.post_middleware(
            "/api/interactions/message",
            {
                "session_id": "FULL-ACTIVITY-1",
                "message": "我想找長者文娛活動",
                "source": "text",
            },
        )
        self.assertEqual(response["task_state"], "completed")
        self.assertEqual(
            [event["tool_name"] for event in response["tool_events"]],
            ["one_account.search_elderly_activities"],
        )
        self.assertIn("activities", response["data"]["activities"])

    def test_diagnostic_read_command_returns_mcp_contract_and_backend_data(self):
        response = self.post_middleware(
            "/api/interactions/message",
            {
                "session_id": "FULL-DIAG-GET",
                "message": "mcp medical.list_departments {}",
                "source": "text",
            },
        )
        self.assertEqual(response["mode"], "mcp_diagnostic")
        self.assertEqual(response["task_state"], "completed")
        self.assertEqual(
            response["data"]["diagnostic"],
            {
                "tool_name": "medical.list_departments",
                "http_method": "GET",
                "path": "/mock/medical/v1/departments",
                "risk_level": "R0",
            },
        )
        self.assertEqual(
            response["tool_events"][0]["tool_name"],
            "medical.list_departments",
        )
        self.assertTrue(response["data"]["backend_response"]["data"])

    def test_diagnostic_post_requires_confirmation_before_backend_write(self):
        pending = self.post_middleware(
            "/api/interactions/message",
            {
                "session_id": "FULL-DIAG-POST",
                "message": (
                    "mcp one_account.book_government_service_center_queue "
                    '{"service_center_id":"GSC-MAIN",'
                    '"service_type":"general_counter","requested_date":"2026-08-20",'
                    '"confirmation":{"confirmation_id":"DEMO-CONF"}}'
                ),
                "source": "text",
            },
        )
        self.assertEqual(pending["task_state"], "awaiting_confirmation")
        self.assertEqual(pending["tool_events"], [])
        self.assertEqual(pending["actions"][0]["kind"], "confirm_tool")

        confirmed = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-DIAG-POST",
                "action": "confirm_tool",
                "payload": {"name": "medical.list_departments"},
            },
        )
        self.assertEqual(confirmed["task_state"], "completed")
        self.assertEqual(
            confirmed["tool_events"][0]["tool_name"],
            "one_account.book_government_service_center_queue",
        )
        self.assertTrue(confirmed["data"]["backend_response"]["data"]["ticket"]["ticket_id"])

    def test_malformed_diagnostic_command_is_rejected_before_mcp(self):
        request = Request(
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/message",
            data=json.dumps({
                "session_id": "FULL-DIAG-BAD",
                "message": "mcp medical.list_departments {",
                "source": "text",
            }).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as raised:
            self.opener.open(request)
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(
            json.loads(raised.exception.read())["error"]["code"],
            "INVALID_DIAGNOSTIC_COMMAND",
        )


if __name__ == "__main__":
    unittest.main()
