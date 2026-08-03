import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from mock_backends.core.clock import FixedClock, MACAU_TZ
from mock_backends.core.http import BackendRequest, BackendResponse
from mock_backends.router import MockRouter
from mock_backends.server import create_application, make_request_handler


class HttpSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        clock = FixedClock(datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ))
        router = create_application(Path(self.temp_dir.name), clock=clock)
        self.server = __import__("http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(
            ("127.0.0.1", 0), make_request_handler(router)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def call(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_body = None if body is None else json.dumps(body, ensure_ascii=False)
        request_headers = dict(headers or {})
        if request_body is not None:
            request_headers["Content-Type"] = "application/json"
        connection.request(method, path, body=request_body, headers=request_headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, response.getheader("Content-Type"), payload

    def test_each_domain_is_mounted(self):
        status, content_type, body = self.call(
            "GET", "/mock/one-account/cash-sharing-plan?year=2026", headers={"X-Mock-User-Id": "USR-1"}
        )
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        self.assertEqual(body["data"]["plan"]["plan_id"], "CSP-2026")
        status, _, body = self.call("GET", "/mock/medical/v1/departments")
        self.assertEqual(status, 200)
        self.assertTrue(body["data"])
        status, _, body = self.call("GET", "/mock/social-welfare/services")
        self.assertEqual(status, 200)
        self.assertTrue(body["data"]["services"])

    def test_one_account_queue_and_medical_registration(self):
        queue_body = {
            "service_center_id": "GSC-MAIN",
            "service_type": "general_counter",
            "requested_date": "2026-08-04",
            "party_size": 1,
            "contact_phone": "+853-6234-5678",
            "confirmation": {"confirmation_id": "CONF-HTTP-Q"},
        }
        status, _, body = self.call(
            "POST",
            "/mock/one-account/queue-tickets/government-service-center",
            queue_body,
            {"X-Mock-User-Id": "USR-HTTP", "Idempotency-Key": "HTTP-Q-1"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["data"]["ticket"]["service_center_id"], "GSC-MAIN")

        registration_body = {
            "patient_id": "P-10001",
            "department_id": "DEPT-CARDIO",
            "doctor_id": "DOC-001",
            "slot_id": "SLOT-REG-20260812-CARDIO-1030",
            "consent": True,
        }
        status, _, body = self.call(
            "POST",
            "/mock/medical/v1/registrations",
            registration_body,
            {"Authorization": "Bearer mock-user-token", "X-Patient-Id": "P-10001", "Idempotency-Key": "HTTP-REG-1"},
        )
        self.assertEqual(status, 201)
        appointment_id = body["data"]["id"]
        status, _, detail = self.call(
            "GET",
            f"/mock/medical/v1/appointments/{appointment_id}",
            headers={"Authorization": "Bearer mock-user-token", "X-Patient-Id": "P-10001"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["data"]["id"], appointment_id)

    def test_bad_json_unknown_route_and_unexpected_exception(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("POST", "/mock/one-account/pension/applications", body="{bad", headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(response.status, 400)
        self.assertEqual(body["error"]["code"], "INVALID_JSON")

        status, _, body = self.call("GET", "/mock/unknown")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")

        router = MockRouter()

        class ExplodingBackend:
            def handle(self, request):
                raise RuntimeError("secret traceback")

        router.mount("/explode", ExplodingBackend())
        server = __import__("http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(
            ("127.0.0.1", 0), make_request_handler(router)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/explode/test")
            response = connection.getresponse()
            text = response.read().decode("utf-8")
            connection.close()
            self.assertEqual(response.status, 500)
            self.assertNotIn("secret traceback", text)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
