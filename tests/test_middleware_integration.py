import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

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
            {"session_id": "S-1", "message": "我想查詢醫療預約", "source": "text"},
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

        cancelled = post_json(
            self.opener,
            f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/message",
            {"session_id": "S-2", "message": "我想預約醫療服務", "source": "text"},
        )
        service_id_2 = cancelled["data"]["services"][1]["id"]
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


if __name__ == "__main__":
    unittest.main()
