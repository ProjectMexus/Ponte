import unittest

from MCP.errors import AdapterError, BackendInvalidResponse
from MCP.registry import build_registry
from MCP.rest_adapter import HttpResponse, RestAdapter


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def request(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


class RestAdapterTests(unittest.TestCase):
    def test_maps_medical_get_to_query_and_headers(self):
        transport = RecordingTransport(HttpResponse(200, {}, {"data": {"departments": []}}))
        adapter = RestAdapter("http://backend.test", transport)
        definition = build_registry().get("medical.search_registration_slots")

        result = adapter.invoke(
            definition,
            {
                "context": {
                    "authorization": "Bearer mock-user-token",
                    "patient_id": "P-10001",
                    "request_id": "REQ-1",
                },
                "input": {"department_id": "CARDIO", "date": "2026-08-10"},
            },
        )

        request, _ = transport.requests[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.path, "/mock/medical/v1/registration-slots")
        self.assertEqual(request.query["department_id"], "CARDIO")
        self.assertEqual(request.headers["Authorization"], "Bearer mock-user-token")
        self.assertEqual(request.headers["X-Patient-Id"], "P-10001")
        self.assertEqual(result["data"], {"departments": []})

    def test_maps_activity_post_body_without_context(self):
        transport = RecordingTransport(
            HttpResponse(201, {}, {"data": {"registration": {"registration_id": "REG-1"}}})
        )
        adapter = RestAdapter("http://backend.test/", transport)
        definition = build_registry().get("one_account.submit_activity_registration")

        adapter.invoke(
            definition,
            {
                "context": {
                    "mock_user_id": "USR-DEMO-001",
                    "request_id": "REQ-2",
                    "idempotency_key": "KEY-2",
                },
                "input": {
                    "activity_id": "ACT-1",
                    "form_id": "FORM-1",
                    "participant": {},
                    "consents": {"personal_data": True},
                    "confirmation": {"confirmed": True},
                },
            },
        )

        request, _ = transport.requests[0]
        self.assertEqual(request.headers["X-Mock-User-Id"], "USR-DEMO-001")
        self.assertEqual(request.headers["Idempotency-Key"], "KEY-2")
        self.assertEqual(request.body["activity_id"], "ACT-1")
        self.assertNotIn("context", request.body)

    def test_converts_backend_error_to_adapter_error(self):
        transport = RecordingTransport(
            HttpResponse(
                409,
                {},
                {
                    "error": {
                        "code": "SLOT_NOT_AVAILABLE",
                        "message": "所選時段已滿",
                        "retryable": False,
                    }
                },
            )
        )
        adapter = RestAdapter("http://backend.test", transport)
        with self.assertRaises(AdapterError) as raised:
            adapter.invoke(
                build_registry().get("medical.create_registration"),
                {
                    "context": {
                        "authorization": "Bearer mock-user-token",
                        "patient_id": "P-10001",
                        "idempotency_key": "KEY-3",
                    },
                    "input": {
                        "patient_id": "P-10001",
                        "department_id": "CARDIO",
                        "slot_id": "SLOT-1",
                        "consent": True,
                    },
                },
            )
        self.assertEqual(raised.exception.details["code"], "SLOT_NOT_AVAILABLE")
        self.assertEqual(raised.exception.status, 409)

    def test_rejects_non_object_success_response(self):
        transport = RecordingTransport(HttpResponse(200, {}, ["not", "an", "object"]))
        adapter = RestAdapter("http://backend.test", transport)
        with self.assertRaises(BackendInvalidResponse):
            adapter.invoke(
                build_registry().get("medical.list_departments"),
                {"context": {"authorization": "Bearer mock-user-token"}, "input": {}},
            )


if __name__ == "__main__":
    unittest.main()
