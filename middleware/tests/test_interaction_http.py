import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from middleware.intent import KeywordIntentRecognizer
from middleware.server import create_application, create_http_server
from mock_backends.server import create_http_server as create_backend_http_server


def post_json(opener, url, body):
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST", headers={"Content-Type": "application/json"})
    with opener.open(request) as response:
        return json.loads(response.read())


class InteractionHttpTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.backend = create_backend_http_server("127.0.0.1", 0, Path(self.tempdir.name))
        self.backend_thread = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.backend_thread.start()
        application = create_application(
            f"http://127.0.0.1:{self.backend.server_port}",
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        self.middleware = create_http_server("127.0.0.1", 0, application)
        self.middleware_thread = threading.Thread(target=self.middleware.serve_forever, daemon=True)
        self.middleware_thread.start()
        self.opener = build_opener(ProxyHandler({}))
        self.url = f"http://127.0.0.1:{self.middleware.server_port}"

    def tearDown(self):
        self.middleware.shutdown()
        self.backend.shutdown()
        self.middleware.server_close()
        self.backend.server_close()
        self.tempdir.cleanup()

    def event(self, interaction_id, event):
        return {
            "routing": {"interaction_id": interaction_id, "session_id": "S-CORE-HTTP"},
            "event": event,
            "audit": {"source": "voice", "language": "yue"},
        }

    def test_normalized_medical_events_return_one_canonical_response(self):
        first = post_json(self.opener, self.url + "/api/interactions", self.event("INT-1", {
            "type": "user_utterance",
            "task_id": None,
            "content": "我想預約醫療服務",
        }))
        self.assertIn("task", first)
        self.assertIn("response", first)
        self.assertIn("workspace", first)
        self.assertNotIn("assistant_message", first)
        self.assertNotIn("task_state", first)
        self.assertEqual(first["workspace"]["view"], "service_selection")
        self.assertTrue(first["workspace"]["actions"])
        task_id = first["task"]["task_id"]
        service_event = first["workspace"]["actions"][0]["event"]
        self.assertTrue(service_event["action_id"])
        self.assertEqual(service_event["task_id"], task_id)

        second = post_json(self.opener, self.url + "/api/interactions", self.event("INT-2", service_event))
        self.assertEqual(second["workspace"]["view"], "slot_selection")
        slot_event = second["workspace"]["actions"][0]["event"]
        third = post_json(self.opener, self.url + "/api/interactions", self.event("INT-3", slot_event))
        self.assertEqual(third["workspace"]["view"], "appointment_confirmation")
        approve_event = next(item["event"] for item in third["workspace"]["actions"] if item["event"].get("decision") == "approve")
        self.assertEqual(approve_event["task_id"], task_id)
        self.assertTrue(approve_event["action_id"])

        final = post_json(self.opener, self.url + "/api/interactions", self.event("INT-4", approve_event))
        self.assertEqual(final["task"]["status"], "completed")
        self.assertEqual(final["workspace"]["view"], "appointment_completed")
        self.assertTrue(final["receipt"]["receipt_id"].startswith("MED-APT-"))
        for removed in ("assistant_message", "task_state", "current_step", "tool_events"):
            self.assertNotIn(removed, final)
        self.assertNotIn("patient_id", json.dumps(final, ensure_ascii=False))

    def test_voice_cash_utterance_returns_read_only_summary(self):
        response = post_json(self.opener, self.url + "/api/interactions", self.event("INT-CASH-1", {
            "type": "user_utterance",
            "task_id": None,
            "content": "我想查現金分享計劃",
        }))
        self.assertEqual(response["task"]["type"], "cash_sharing_query")
        self.assertEqual(response["task"]["status"], "completed")
        self.assertEqual(response["task"]["current_step"], "complete")
        self.assertEqual(response["workspace"]["view"], "cash_sharing_summary")
        self.assertEqual(response["workspace"]["actions"], [])
        self.assertIsNone(response["receipt"])
        self.assertIsNone(response["confirmation"])
        self.assertEqual(response["task"]["facts"]["plan"]["year"], 2026)
        for removed in ("assistant_message", "task_state", "current_step", "tool_events"):
            self.assertNotIn(removed, response)


if __name__ == "__main__":
    unittest.main()
