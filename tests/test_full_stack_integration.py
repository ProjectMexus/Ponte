import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from frontend.server import create_http_server as create_frontend_http_server
from middleware.intent import KeywordIntentRecognizer
from middleware.server import create_application, create_http_server
from mock_backends.server import create_http_server as create_backend_http_server


def interaction_body(session_id, interaction_id, event):
    return {
        "routing": {"session_id": session_id, "interaction_id": interaction_id},
        "event": event,
    }


def utterance(content):
    return {"type": "user_utterance", "task_id": None, "content": content}


def action_event(response, *, decision=None, service_id=None):
    # First check for actions embedded in fields
    fields = response["workspace"].get("fields", [])
    if isinstance(fields, list):
        for field in fields:
            if isinstance(field, dict) and "action" in field:
                event = field["action"].get("event", {})
                if decision is not None and event.get("decision") == decision:
                    return event
                if service_id is not None and event.get("service_id") == service_id:
                    return event
                if decision is None and service_id is None:
                    return event
    # Fall back to workspace.actions
    actions = response["workspace"]["actions"]
    if decision is not None:
        return next(item["event"] for item in actions if item["event"].get("decision") == decision)
    if service_id is not None:
        return next(item["event"] for item in actions if item["event"].get("service_id") == service_id)
    return actions[0]["event"]


def recovery_event(response, action):
    return next(
        item["event"]
        for item in response["workspace"]["actions"]
        if item["event"].get("type") == "recovery_action" and item["event"].get("action") == action
    )


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
            "/api/interactions",
            interaction_body(
                "BROWSER-SMOKE-1",
                "FULL-SMOKE-1",
                utterance("我想查詢自己的醫療預約"),
            ),
        )

        self.assertIn("Ponte 語音服務", html)
        self.assertIn("MiddlewareClient", client_js)
        self.assertTrue(health["backend_reachable"])
        self.assertEqual(response["task"]["status"], "completed")
        self.assertEqual(response["workspace"]["view"], "appointment_list")
        self.assertEqual(response["task"]["facts"]["appointments"], [])
        for removed in ("assistant_message", "task_state", "current_step", "tool_events"):
            self.assertNotIn(removed, response)

        process = self.middleware_app.mcp_client.process
        self.assertIsNotNone(process)
        self.assertIsNone(process.poll())
        self.assertEqual(process.args[1:3], ["-m", "MCP"])

    def test_natural_language_cash_sharing_reaches_backend(self):
        response = self.post_middleware(
            "/api/interactions",
            interaction_body(
                "FULL-CASH-1",
                "FULL-CASH-INT-1",
                utterance("我想查現金分享計劃"),
            ),
        )
        self.assertEqual(response["task"]["type"], "cash_sharing_query")
        self.assertEqual(response["task"]["status"], "completed")
        self.assertEqual(response["task"]["current_step"], "complete")
        self.assertEqual(response["workspace"]["view"], "cash_sharing_summary")
        self.assertEqual(response["task"]["facts"]["plan"]["year"], 2026)
        self.assertEqual(response["task"]["facts"]["plan"]["payout"]["amount"], 10000)
        self.assertEqual(response["workspace"]["actions"], [])
        self.assertIsNone(response["receipt"])
        self.assertNotIn("appointment", response["workspace"]["view"])
        for removed in ("assistant_message", "task_state", "current_step", "tool_events"):
            self.assertNotIn(removed, response)

    def test_duplicate_booking_recovery_then_alternative_service_books(self):
        def interact(session_id, interaction_id, event):
            return self.post_middleware(
                "/api/interactions",
                interaction_body(session_id, interaction_id, event),
            )

        first = interact("FULL-ALT-FIRST", "FULL-INT-01", utterance("我想預約醫療服務"))
        self.assertEqual(first["workspace"]["view"], "service_selection")
        # New structure: one field per service with human-readable label and value
        service_fields = [f for f in first["workspace"]["fields"] if f["key"].startswith("service_")]
        self.assertTrue(len(service_fields) > 0, "Should have at least one service field")
        # Find the physical therapy service by label (name)
        physical_therapy_field = next(
            (f for f in service_fields if f["label"] == "物理治療"),
            None,
        )
        self.assertIsNotNone(physical_therapy_field, "Should find physical therapy service")
        self.assertIn("45 分鐘", physical_therapy_field["value"])

        first_slots = interact(
            "FULL-ALT-FIRST", "FULL-INT-02", action_event(first, service_id="SERVICE-PT-001"),
        )
        first_confirmation = interact("FULL-ALT-FIRST", "FULL-INT-03", action_event(first_slots))
        first_confirmed = interact(
            "FULL-ALT-FIRST", "FULL-INT-04", action_event(first_confirmation, decision="approve"),
        )
        self.assertEqual(first_confirmed["task"]["status"], "completed")
        self.assertEqual(first_confirmed["workspace"]["view"], "appointment_completed")

        second = interact("FULL-ALT-SECOND", "FULL-INT-05", utterance("我想預約醫療服務"))
        second_slots = interact(
            "FULL-ALT-SECOND", "FULL-INT-06", action_event(second, service_id="SERVICE-PT-001"),
        )
        second_confirmation = interact("FULL-ALT-SECOND", "FULL-INT-07", action_event(second_slots))
        failed = interact(
            "FULL-ALT-SECOND", "FULL-INT-08", action_event(second_confirmation, decision="approve"),
        )
        self.assertEqual(failed["task"]["status"], "awaiting_input")
        self.assertEqual(failed["workspace"]["view"], "appointment_recovery")
        self.assertEqual(failed["recovery"]["reason"], "duplicate_booking")
        self.assertIsNone(failed["receipt"])

        cancelled = interact("FULL-ALT-SECOND", "FULL-INT-09", recovery_event(failed, "cancel"))
        self.assertEqual(cancelled["task"]["status"], "cancelled")
        self.assertIsNone(cancelled["receipt"])

        reopened = interact("FULL-ALT-SECOND", "FULL-INT-10", utterance("我想預約醫療服務"))
        self.assertEqual(reopened["workspace"]["view"], "service_selection")
        continued = interact(
            "FULL-ALT-SECOND", "FULL-INT-11", action_event(reopened, service_id="SERVICE-US-001"),
        )
        self.assertEqual(continued["workspace"]["view"], "slot_selection")
        us_confirmation = interact("FULL-ALT-SECOND", "FULL-INT-12", action_event(continued))
        us_confirmed = interact(
            "FULL-ALT-SECOND", "FULL-INT-13", action_event(us_confirmation, decision="approve"),
        )
        self.assertEqual(us_confirmed["task"]["status"], "completed")
        self.assertEqual(us_confirmed["workspace"]["view"], "appointment_completed")
        self.assertTrue(us_confirmed["receipt"]["receipt_id"].startswith("MED-APT-"))

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
