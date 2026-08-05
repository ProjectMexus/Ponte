import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from urllib.error import HTTPError
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from frontend.server import create_http_server as create_frontend_http_server
from middleware.intent import KeywordIntentRecognizer
from middleware.server import create_application, create_http_server
from middleware.task_manager.interpreter import DeterministicTaskRecoveryInterpreter
from mock_backends.server import create_http_server as create_backend_http_server
from mock_backends.core.clock import MACAU_TZ


def booking_window():
    today = datetime.now(MACAU_TZ).date()
    return today.isoformat(), (today + timedelta(days=14)).isoformat()


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

        self.assertIn("Ponte 語音服務", html)
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

    def test_duplicate_booking_recovery_offers_other_available_service(self):
        self.middleware_app.controller.recovery_interpreter = DeterministicTaskRecoveryInterpreter()
        date_from, date_to = booking_window()

        first = self.post_middleware(
            "/api/interactions/message",
            {
                "session_id": "FULL-ALT-FIRST",
                "message": "我想預約醫療服務",
                "source": "text",
            },
        )
        physical_therapy = next(
            service for service in first["data"]["services"] if service["id"] == "SERVICE-PT-001"
        )
        self.assertEqual(physical_therapy["name"], "物理治療")
        first_search = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-FIRST",
                "action": "search_slots",
                "payload": {
                    "service_id": "SERVICE-PT-001",
                    "date_from": date_from,
                    "date_to": date_to,
                },
            },
        )
        first_selected = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-FIRST",
                "action": "select_slot",
                "payload": {"slot_id": first_search["data"]["slots"][0]["id"]},
            },
        )
        self.assertEqual(first_selected["task_state"], "awaiting_confirmation")
        first_confirmed = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-FIRST",
                "action": "confirm",
                "payload": {"referring_appointment_id": "APT-REF-1"},
            },
        )
        self.assertEqual(first_confirmed["task_state"], "completed")

        second = self.post_middleware(
            "/api/interactions/message",
            {
                "session_id": "FULL-ALT-SECOND",
                "message": "我想預約醫療服務",
                "source": "text",
            },
        )
        second_search = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-SECOND",
                "action": "search_slots",
                "payload": {
                    "service_id": "SERVICE-PT-001",
                    "date_from": date_from,
                    "date_to": date_to,
                },
            },
        )
        second_selected = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-SECOND",
                "action": "select_slot",
                "payload": {"slot_id": second_search["data"]["slots"][0]["id"]},
            },
        )
        failed = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-SECOND",
                "action": "confirm",
                "payload": {"referring_appointment_id": "APT-REF-1"},
            },
        )

        self.assertEqual(second_selected["task_state"], "awaiting_confirmation")
        self.assertEqual(failed["recovery"]["reason_code"], "DUPLICATE_BOOKING")
        picker = next(
            action for action in failed["actions"]
            if action["kind"] == "select_service"
        )
        self.assertEqual(picker["payload"], {})

        reopened = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-SECOND",
                "action": "select_service",
                "payload": {},
            },
        )
        self.assertEqual(reopened["task_state"], "selecting_service")
        self.assertEqual(
            {service["id"] for service in reopened["data"]["services"]},
            {"SERVICE-PT-001", "SERVICE-US-001", "SERVICE-ECHO-001"},
        )

        continued = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-SECOND",
                "action": "search_slots",
                "payload": {
                    "service_id": "SERVICE-US-001",
                    "date_from": date_from,
                    "date_to": date_to,
                },
            },
        )
        self.assertEqual(continued["task_state"], "selecting_slot")
        self.assertEqual(continued["data"]["service_id"], "SERVICE-US-001")
        self.assertEqual(continued["data"]["slots"][0]["service_id"], "SERVICE-US-001")

        us_selected = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-SECOND",
                "action": "select_slot",
                "payload": {"slot_id": continued["data"]["slots"][0]["id"]},
            },
        )
        us_confirmed = self.post_middleware(
            "/api/interactions/action",
            {
                "session_id": "FULL-ALT-SECOND",
                "action": "confirm",
                "payload": {"referring_appointment_id": "APT-REF-1"},
            },
        )
        self.assertEqual(us_selected["task_state"], "awaiting_confirmation")
        self.assertEqual(us_confirmed["task_state"], "completed")
        create_event = [
            event for event in us_confirmed["tool_events"]
            if event["tool_name"] == "medical.create_appointment"
        ][-1]
        self.assertTrue(create_event["ok"])
        self.assertEqual(create_event["arguments"]["input"]["service_id"], "SERVICE-US-001")

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
