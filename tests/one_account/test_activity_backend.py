import unittest
from datetime import datetime

from mock_backends.core.clock import FixedClock, MACAU_TZ
from mock_backends.core.http import BackendRequest
from mock_backends.core.idempotency import RepositoryIdempotencyStore
from mock_backends.core.ids import SequentialIdGenerator
from mock_backends.core.persistence import MemoryRepository
from mock_backends.one_account.backend import OneAccountBackend
from mock_backends.one_account.service import OneAccountService


class ActivityBackendTests(unittest.TestCase):
    def setUp(self):
        clock = FixedClock(datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ))
        self.service = OneAccountService(
            clock=clock,
            ids=SequentialIdGenerator(),
            application_repository=MemoryRepository(),
            ticket_repository=MemoryRepository(),
            idempotency=RepositoryIdempotencyStore(MemoryRepository()),
            activity_registration_repository=MemoryRepository(),
            phone_assistance_repository=MemoryRepository(),
        )
        self.backend = OneAccountBackend(self.service)

    def request(self, method, path, user="USR-DEMO-001", body=None, query=None, **headers):
        all_headers = {"X-Mock-User-Id": user} if user is not None else {}
        all_headers.update(headers)
        return BackendRequest(
            method=method,
            path=path,
            headers=all_headers,
            body=body,
            query=query or {},
            request_id="REQ-ACTIVITY-001",
        )

    def activity_request(self, method, suffix, **kwargs):
        return self.request(method, f"/mock/elderly-activities/v1{suffix}", **kwargs)

    def form_body(self, activity_id="ACT-ORG-A-20260808-001"):
        return {
            "activity_id": activity_id,
            "form_id": "FORM-ORG-A-001",
            "participant": {"full_name": "陳美玲", "phone": "+853-6234-5678", "age": 80},
            "consents": {"personal_data": True},
            "confirmation": {"confirmation_id": "CONF-ACT-1"},
        }

    def phone_body(self):
        return {
            "activity_id": "ACT-ORG-B-20260816-002",
            "participant": {"full_name": "陳美玲", "phone": "+853-6234-5678", "age": 80, "library_reader_card": True},
            "preferred_call_window": {"date": "2026-08-04", "from": "10:00", "to": "11:30"},
            "confirmation": {"confirmation_id": "CONF-PHONE-1"},
        }

    def test_search_filters_available_organizations_and_method(self):
        response = self.backend.handle(
            self.activity_request(
                "GET",
                "/activities",
                query={"organization_id": ["ORG-B"], "registration_method": ["phone"]},
            )
        )
        self.assertEqual(response.status, 200)
        activities = response.body["data"]["activities"]
        self.assertTrue(activities)
        self.assertTrue(all(item["organization"]["organization_id"] == "ORG-B" for item in activities))
        self.assertTrue(all(item["registration"]["method"] == "phone" for item in activities))
        self.assertTrue(all(item["availability"]["remaining"] > 0 for item in activities))

    def test_search_keyword_and_district(self):
        response = self.backend.handle(
            self.activity_request(
                "GET",
                "/activities",
                query={"keyword": ["手機"], "district": ["氹仔"], "available_only": ["true"]},
            )
        )
        self.assertEqual(response.status, 200)
        self.assertTrue(all("手機" in item["title"] or "手機" in item["summary"] for item in response.body["data"]["activities"]))

    def test_form_endpoint_rejects_phone_activity(self):
        response = self.backend.handle(
            self.activity_request("GET", "/activities/ACT-ORG-B-20260816-002/registration-form")
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(response.body["error"]["code"], "PHONE_REGISTRATION_REQUIRED")

        form = self.backend.handle(
            self.activity_request("GET", "/activities/ACT-ORG-A-20260808-001/registration-form", user="USR-DEMO-001")
        )
        self.assertEqual(form.status, 200)
        self.assertEqual(form.body["data"]["method"], "form")
        self.assertEqual(form.body["data"]["form_id"], "FORM-ORG-A-001")

    def test_form_registration_is_confirmed_and_user_scoped(self):
        response = self.backend.handle(
            self.activity_request("POST", "/registrations", body=self.form_body(), **{"Idempotency-Key": "ACT-REG-1"})
        )
        self.assertEqual(response.status, 201)
        registration_id = response.body["data"]["registration"]["registration_id"]
        self.assertEqual(response.body["data"]["registration"]["status"], "confirmed")
        repeated = self.backend.handle(
            self.activity_request("POST", "/registrations", body=self.form_body(), **{"Idempotency-Key": "ACT-REG-1"})
        )
        self.assertEqual(repeated.body, response.body)
        found = self.backend.handle(
            self.activity_request("GET", f"/registrations/{registration_id}")
        )
        self.assertEqual(found.status, 200)
        hidden = self.backend.handle(
            self.activity_request("GET", f"/registrations/{registration_id}", user="USR-OTHER")
        )
        self.assertEqual(hidden.status, 404)

    def test_form_registration_requires_user_and_confirmation(self):
        no_user = self.backend.handle(
            self.activity_request("POST", "/registrations", user=None, body=self.form_body(), **{"Idempotency-Key": "ACT-REG-2"})
        )
        self.assertEqual(no_user.status, 401)
        body = self.form_body()
        body.pop("confirmation")
        no_confirmation = self.backend.handle(
            self.activity_request("POST", "/registrations", body=body, **{"Idempotency-Key": "ACT-REG-3"})
        )
        self.assertEqual(no_confirmation.status, 422)
        self.assertEqual(no_confirmation.body["error"]["code"], "CONFIRMATION_REQUIRED")

    def test_phone_assistance_is_not_official_registration(self):
        response = self.backend.handle(
            self.activity_request(
                "POST",
                "/phone-registration-assists",
                body=self.phone_body(),
                **{"Idempotency-Key": "PHONE-1"},
            )
        )
        self.assertEqual(response.status, 202)
        assistance = response.body["data"]["assistance"]
        self.assertIn(assistance["status"], {"ready_for_call", "waiting_for_phone_call"})
        self.assertIn("尚未完成", assistance["next_action"])

    def test_activity_full_returns_conflict(self):
        response = self.backend.handle(
            self.activity_request(
                "POST",
                "/registrations",
                body=self.form_body("ACT-ORG-A-20260808-003"),
                **{"Idempotency-Key": "ACT-FULL-1"},
            )
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(response.body["error"]["code"], "ACTIVITY_FULL")


if __name__ == "__main__":
    unittest.main()
