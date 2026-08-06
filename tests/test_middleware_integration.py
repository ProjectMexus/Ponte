import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from MCP.errors import AdapterError, BackendTimeout
from middleware.intent import KeywordIntentRecognizer
from middleware.server import create_application, create_http_server
from mock_backends.server import create_http_server as create_backend_http_server


def post_json(opener, url, body):
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with opener.open(request) as response:
        return json.loads(response.read())


def post_interaction(opener, base_url, session_id, interaction_id, event):
    return post_json(opener, base_url + "/api/interactions", {
        "routing": {"session_id": session_id, "interaction_id": interaction_id},
        "event": event,
    })


def action_event(response, *, decision=None):
    # First check for actions embedded in fields
    fields = response["workspace"].get("fields", [])
    if isinstance(fields, list):
        for field in fields:
            if isinstance(field, dict) and "action" in field:
                event = field["action"].get("event", {})
                if decision is None:
                    return event
                if event.get("decision") == decision:
                    return event
    # Fall back to workspace.actions
    actions = response["workspace"]["actions"]
    if decision is None:
        return actions[0]["event"]
    return next(item["event"] for item in actions if item["event"].get("decision") == decision)


def recovery_event(response, action):
    return next(
        item["event"]
        for item in response["workspace"]["actions"]
        if item["event"].get("type") == "recovery_action" and item["event"].get("action") == action
    )


def utterance(content):
    return {"type": "user_utterance", "task_id": None, "content": content}


def assert_no_legacy_fields(test_case, response):
    for removed in ("assistant_message", "task_state", "current_step", "tool_events"):
        test_case.assertNotIn(removed, response)


class MiddlewareBackendIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name)
        self.backend = create_backend_http_server("127.0.0.1", 0, self.data_dir)
        self.backend_thread = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.backend_thread.start()
        self.middleware = create_http_server(
            "127.0.0.1",
            0,
            create_application(
                f"http://127.0.0.1:{self.backend.server_port}",
                "PAT-DEMO-001",
                "Bearer mock-user-token",
                intent_recognizer=KeywordIntentRecognizer(),
            ),
        )
        self.middleware_thread = threading.Thread(target=self.middleware.serve_forever, daemon=True)
        self.middleware_thread.start()
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.middleware.shutdown()
        self.backend.shutdown()
        self.middleware.server_close()
        self.backend.server_close()
        self.tempdir.cleanup()

    def test_canonical_medical_booking_reaches_mock_backend(self):
        base_url = f"http://127.0.0.1:{self.middleware.server_port}"
        first = post_interaction(
            self.opener, base_url, "S-1", "INT-1", utterance("我想預約醫療服務"),
        )
        self.assertEqual(first["workspace"]["view"], "service_selection")
        # Actions are now embedded in fields for selection views
        fields = first["workspace"].get("fields", [])
        has_actions = any(isinstance(f, dict) and "action" in f for f in fields)
        self.assertTrue(has_actions or first["workspace"]["actions"])
        assert_no_legacy_fields(self, first)
        task_id = first["task"]["task_id"]

        second = post_interaction(self.opener, base_url, "S-1", "INT-2", action_event(first))
        self.assertEqual(second["workspace"]["view"], "slot_selection")

        third = post_interaction(self.opener, base_url, "S-1", "INT-3", action_event(second))
        self.assertEqual(third["workspace"]["view"], "appointment_confirmation")

        final = post_interaction(
            self.opener, base_url, "S-1", "INT-4", action_event(third, decision="approve"),
        )
        self.assertEqual(final["task"]["status"], "completed")
        self.assertEqual(final["task"]["task_id"], task_id)
        self.assertEqual(final["workspace"]["view"], "appointment_completed")
        self.assertTrue(final["receipt"]["receipt_id"].startswith("MED-APT-"))
        self.assertEqual(final["task"]["receipt"], final["receipt"])
        assert_no_legacy_fields(self, final)
        self.assertNotIn("patient_id", json.dumps(final, ensure_ascii=False))

        queried = post_interaction(
            self.opener, base_url, "S-1", "INT-5", utterance("我想查詢自己的醫療預約"),
        )
        self.assertEqual(queried["task"]["status"], "completed")
        self.assertEqual(queried["workspace"]["view"], "appointment_list")
        assert_no_legacy_fields(self, queried)
        appointments = queried["task"]["facts"]["appointments"]
        self.assertTrue(appointments)
        confirmed_dates = [
            item["start"][:10] for item in appointments if item.get("status") == "confirmed"
        ]
        self.assertIn(final["receipt"]["appointment"]["date"], confirmed_dates)

        cancelled_start = post_interaction(
            self.opener, base_url, "S-2", "INT-6", utterance("我想預約醫療服務"),
        )
        # Actions are now embedded in fields for selection views
        fields = cancelled_start["workspace"].get("fields", [])
        service_ids = {
            field["action"]["event"]["service_id"]
            for field in fields
            if isinstance(field, dict) and field.get("action", {}).get("event", {}).get("type") == "service_selected"
        }
        self.assertEqual(service_ids, {"SERVICE-US-001", "SERVICE-PT-001", "SERVICE-ECHO-001"})
        cancelled_slots = post_interaction(
            self.opener, base_url, "S-2", "INT-7", action_event(cancelled_start),
        )
        cancelled_confirmation = post_interaction(
            self.opener, base_url, "S-2", "INT-8", action_event(cancelled_slots),
        )
        cancelled = post_interaction(
            self.opener,
            base_url,
            "S-2",
            "INT-9",
            action_event(cancelled_confirmation, decision="reject"),
        )
        self.assertEqual(cancelled["task"]["status"], "cancelled")
        self.assertIsNone(cancelled["receipt"])

        direct = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/mcp/tools/call",
            {
                "name": "medical.list_departments",
                "arguments": {"context": {"authorization": "Bearer mock-user-token"}, "input": {}},
            },
        )
        self.assertTrue(direct["ok"])
        self.assertTrue(direct["data"]["data"])

        invalid_request = Request(
            f"http://127.0.0.1:{self.middleware.server_port}/api/mcp/tools/call",
            data=json.dumps({"name": "medical.not_a_tool", "arguments": {"context": {}, "input": {}}}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as raised:
            self.opener.open(invalid_request)
        self.assertEqual(raised.exception.code, 400)
        invalid_body = json.loads(raised.exception.read())
        self.assertEqual(invalid_body["error"]["code"], "UNKNOWN_TOOL")


class FailingOnceMcpClient:
    def __init__(self):
        self.calls = []
        self.slot_attempts = 0
        self.closed = False

    def start(self):
        return None

    def close(self):
        self.closed = True

    def call_tool(self, name, arguments):
        del arguments
        self.calls.append(name)
        if name == "medical.get_my_appointments":
            return {"request_id": "REQ-RECOVER-1", "data": []}
        if name == "medical.list_appointment_services":
            return {
                "request_id": "REQ-RECOVER-2",
                "data": [{"id": "SERVICE-US-001", "name": "超聲波檢查", "duration_minutes": 30}],
            }
        if name == "medical.search_appointment_slots":
            self.slot_attempts += 1
            if self.slot_attempts == 1:
                raise BackendTimeout(details={"operation": "appointment_slots"})
            return {
                "request_id": "REQ-RECOVER-3",
                "data": [{"id": "SLOT-US-20260812-1400", "start": "2026-08-12T14:00:00+08:00"}],
            }
        raise AssertionError(name)


class DuplicateBookingMcpClient(FailingOnceMcpClient):
    def call_tool(self, name, arguments):
        del arguments
        self.calls.append(name)
        if name == "medical.get_my_appointments":
            return {"request_id": "REQ-DUPLICATE-1", "data": []}
        if name == "medical.list_appointment_services":
            return {
                "request_id": "REQ-DUPLICATE-2",
                "data": [{"id": "SERVICE-US-001", "name": "超聲波檢查", "duration_minutes": 30}],
            }
        if name == "medical.search_appointment_slots":
            return {
                "request_id": "REQ-DUPLICATE-3",
                "data": [{"id": "SLOT-US-20260812-1400", "start": "2026-08-12T14:00:00+08:00"}],
            }
        if name == "medical.create_appointment":
            raise AdapterError(
                "DUPLICATE_BOOKING",
                "RAW BACKEND CONFLICT MESSAGE",
                status=409,
                details={"message": "RAW BACKEND CONFLICT MESSAGE"},
                retryable=False,
            )
        raise AssertionError(name)


class MiddlewareRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.mcp_client = FailingOnceMcpClient()
        self.application = create_application(
            "http://backend.test",
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            mcp_client=self.mcp_client,
            intent_recognizer=KeywordIntentRecognizer(),
        )
        self.middleware = create_http_server("127.0.0.1", 0, self.application)
        self.middleware_thread = threading.Thread(target=self.middleware.serve_forever, daemon=True)
        self.middleware_thread.start()
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.middleware.shutdown()
        self.middleware.server_close()

    def test_same_task_recovers_after_backend_timeout(self):
        base_url = f"http://127.0.0.1:{self.middleware.server_port}"
        booking = post_interaction(
            self.opener,
            base_url,
            "S-RECOVER-HTTP",
            "INT-RECOVER-1",
            utterance("我想預約醫療服務"),
        )
        self.assertEqual(booking["workspace"]["view"], "service_selection")
        failed = post_interaction(
            self.opener,
            base_url,
            "S-RECOVER-HTTP",
            "INT-RECOVER-2",
            action_event(booking),
        )
        self.assertEqual(failed["task"]["status"], "awaiting_input")
        self.assertEqual(failed["workspace"]["view"], "appointment_recovery")
        self.assertEqual(failed["recovery"]["reason"], "backend_unavailable")
        self.assertIsNone(failed["receipt"])
        assert_no_legacy_fields(self, failed)

        recovered = post_interaction(
            self.opener,
            base_url,
            "S-RECOVER-HTTP",
            "INT-RECOVER-3",
            recovery_event(failed, "retry"),
        )
        self.assertEqual(recovered["task"]["status"], "awaiting_input")
        self.assertEqual(recovered["workspace"]["view"], "slot_selection")
        self.assertEqual(
            [item["id"] for item in recovered["task"]["facts"]["slots"]],
            ["SLOT-US-20260812-1400"],
        )
        self.assertIsNone(recovered["recovery"])
        self.assertEqual(self.mcp_client.slot_attempts, 2)

    def test_same_task_exposes_recovery_after_mcp_duplicate_booking(self):
        self.middleware.shutdown()
        self.middleware.server_close()
        self.mcp_client = DuplicateBookingMcpClient()
        self.application = create_application(
            "http://backend.test",
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            mcp_client=self.mcp_client,
            intent_recognizer=KeywordIntentRecognizer(),
        )
        self.middleware = create_http_server("127.0.0.1", 0, self.application)
        self.middleware_thread = threading.Thread(target=self.middleware.serve_forever, daemon=True)
        self.middleware_thread.start()

        base_url = f"http://127.0.0.1:{self.middleware.server_port}"
        booking = post_interaction(
            self.opener,
            base_url,
            "S-DUPLICATE-HTTP",
            "INT-DUPLICATE-1",
            utterance("我想預約醫療服務"),
        )
        slots = post_interaction(
            self.opener,
            base_url,
            "S-DUPLICATE-HTTP",
            "INT-DUPLICATE-2",
            action_event(booking),
        )
        confirmation = post_interaction(
            self.opener,
            base_url,
            "S-DUPLICATE-HTTP",
            "INT-DUPLICATE-3",
            action_event(slots),
        )
        failed = post_interaction(
            self.opener,
            base_url,
            "S-DUPLICATE-HTTP",
            "INT-DUPLICATE-4",
            action_event(confirmation, decision="approve"),
        )

        self.assertEqual(failed["task"]["status"], "awaiting_input")
        self.assertEqual(failed["workspace"]["view"], "appointment_recovery")
        self.assertEqual(failed["recovery"]["reason"], "duplicate_booking")
        self.assertIsNone(failed["receipt"])
        self.assertEqual(
            [item["event"]["action"] for item in failed["workspace"]["actions"]],
            ["retry", "human_help", "cancel"],
        )
        self.assertNotIn("RAW BACKEND CONFLICT MESSAGE", str(failed))
        assert_no_legacy_fields(self, failed)

        retried = post_interaction(
            self.opener,
            base_url,
            "S-DUPLICATE-HTTP",
            "INT-DUPLICATE-5",
            recovery_event(failed, "retry"),
        )
        self.assertEqual(retried["task"]["status"], "awaiting_input")
        self.assertEqual(retried["recovery"]["reason"], "duplicate_booking")
        self.assertIsNone(retried["receipt"])


if __name__ == "__main__":
    unittest.main()
