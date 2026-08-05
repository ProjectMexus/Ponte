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

    def test_message_to_medical_tool_reaches_mock_backend(self):
        response = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/message",
            {"session_id": "S-1", "message": "我想預約醫療服務", "source": "text"},
        )
        self.assertEqual(response["session_id"], "S-1")
        self.assertEqual(response["task_state"], "selecting_service")
        self.assertTrue(response["tool_events"])
        self.assertEqual(response["tool_events"][0]["tool_name"], "medical.get_my_appointments")

        service_id = response["data"]["services"][0]["id"]
        slots_response = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/action",
            {
                "session_id": "S-1",
                "action": "search_slots",
                "payload": {
                    "service_id": service_id,
                    "date_from": "2026-08-10",
                    "date_to": "2026-08-14",
                },
            },
        )
        slot_id = slots_response["data"]["slots"][0]["id"]
        post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/action",
            {"session_id": "S-1", "action": "select_slot", "payload": {"slot_id": slot_id}},
        )
        final_response = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/action",
            {
                "session_id": "S-1",
                "action": "confirm",
                "payload": {"referring_appointment_id": "APT-REF-1"},
            },
        )
        self.assertIn(final_response["task_state"], {"submitted", "completed"}, final_response)
        event_names = [event["tool_name"] for event in final_response["tool_events"]]
        self.assertIn("medical.create_appointment", event_names)
        self.assertIn("medical.get_task_status", event_names)
        create_event = next(event for event in final_response["tool_events"] if event["tool_name"] == "medical.create_appointment")
        self.assertTrue(create_event["arguments"]["input"]["consent"])
        self.assertNotIn("confirmation", create_event["arguments"]["input"])
        appointment_id = create_event["data"]["data"]["id"]

        queried = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/message",
            {
                "session_id": "S-1",
                "message": "我想查詢自己的醫療預約",
                "source": "text",
            },
        )
        self.assertEqual(queried["task_state"], "completed")
        self.assertEqual(
            [event["tool_name"] for event in queried["tool_events"]],
            ["medical.get_my_appointments"],
        )
        self.assertNotIn("selected_slot", queried["data"])
        self.assertNotIn("slots", queried["data"])
        self.assertIn(appointment_id, [item["id"] for item in queried["data"]["appointments"]])

        cancelled = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/message",
            {"session_id": "S-2", "message": "我想預約醫療服務", "source": "text"},
        )
        self.assertEqual(
            [service["id"] for service in cancelled["data"]["services"]],
            ["SERVICE-PT-001"],
        )
        service_id_2 = cancelled["data"]["services"][0]["id"]
        cancelled = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/action",
            {
                "session_id": "S-2",
                "action": "search_slots",
                "payload": {"service_id": service_id_2, "date_from": "2026-08-10", "date_to": "2026-08-14"},
            },
        )
        cancelled = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/action",
            {"session_id": "S-2", "action": "select_slot", "payload": {"slot_id": cancelled["data"]["slots"][0]["id"]}},
        )
        cancelled = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/action",
            {"session_id": "S-2", "action": "cancel", "payload": {}},
        )
        self.assertEqual(cancelled["task_state"], "cancelled")
        self.assertNotIn("medical.create_appointment", [event["tool_name"] for event in cancelled["tool_events"]])

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
        booking = post_json(
            self.opener,
            f"{base_url}/api/interactions/message",
            {"session_id": "S-RECOVER-HTTP", "message": "我想預約醫療服務", "source": "text"},
        )
        failed = post_json(
            self.opener,
            f"{base_url}/api/interactions/action",
            {
                "session_id": "S-RECOVER-HTTP",
                "action": "search_slots",
                "payload": {
                    "service_id": booking["data"]["services"][0]["id"],
                    "date_from": "2026-08-10",
                    "date_to": "2026-08-14",
                },
            },
        )
        self.assertEqual(failed["task_state"], "awaiting_user_input")
        self.assertEqual(failed["recovery"]["reason_code"], "BACKEND_TIMEOUT")

        recovered = post_json(
            self.opener,
            f"{base_url}/api/interactions/action",
            {"session_id": "S-RECOVER-HTTP", "action": "retry", "payload": {}},
        )
        self.assertEqual(recovered["task_state"], "selecting_slot")
        self.assertEqual(recovered["data"]["service_id"], "SERVICE-US-001")
        self.assertEqual(
            [event["step_id"] for event in recovered["tool_events"]],
            ["load_appointments", "load_services", "search_slots", "search_slots"],
        )
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
        booking = post_json(
            self.opener,
            f"{base_url}/api/interactions/message",
            {"session_id": "S-DUPLICATE-HTTP", "message": "我想預約醫療服務", "source": "text"},
        )
        post_json(
            self.opener,
            f"{base_url}/api/interactions/action",
            {
                "session_id": "S-DUPLICATE-HTTP",
                "action": "search_slots",
                "payload": {
                    "service_id": booking["data"]["services"][0]["id"],
                    "date_from": "2026-08-10",
                    "date_to": "2026-08-14",
                },
            },
        )
        post_json(
            self.opener,
            f"{base_url}/api/interactions/action",
            {
                "session_id": "S-DUPLICATE-HTTP",
                "action": "select_slot",
                "payload": {"slot_id": "SLOT-US-20260812-1400"},
            },
        )
        failed = post_json(
            self.opener,
            f"{base_url}/api/interactions/action",
            {"session_id": "S-DUPLICATE-HTTP", "action": "confirm", "payload": {}},
        )

        self.assertEqual(failed["task_state"], "awaiting_user_input")
        self.assertEqual(failed["recovery"]["reason_code"], "DUPLICATE_BOOKING")
        self.assertIn("其他可預約時段", failed["recovery"]["explanation"])
        picker = next(
            action for action in failed["actions"]
            if action["kind"] == "select_service"
        )
        self.assertEqual(picker["payload"], {})
        self.assertNotIn("RAW BACKEND CONFLICT MESSAGE", str(failed))


if __name__ == "__main__":
    unittest.main()
