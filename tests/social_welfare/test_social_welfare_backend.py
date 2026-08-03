import unittest
from datetime import datetime

from mock_backends.core.clock import FixedClock, MACAU_TZ
from mock_backends.core.http import BackendRequest
from mock_backends.core.idempotency import RepositoryIdempotencyStore
from mock_backends.core.ids import SequentialIdGenerator
from mock_backends.core.persistence import MemoryRepository
from mock_backends.social_welfare.backend import SocialWelfareBackend
from mock_backends.social_welfare.service import SocialWelfareService


class SocialWelfareBackendTests(unittest.TestCase):
    def setUp(self):
        clock = FixedClock(datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ))
        self.service = SocialWelfareService(
            clock=clock,
            ids=SequentialIdGenerator(),
            referral_repository=MemoryRepository(),
            idempotency=RepositoryIdempotencyStore(MemoryRepository()),
        )
        self.backend = SocialWelfareBackend(self.service)

    def request(self, method, path, user="USR-DEMO-001", body=None, query=None, **headers):
        all_headers = {"X-Mock-User-Id": user} if user is not None else {}
        all_headers.update(headers)
        return BackendRequest(
            method=method,
            path=path,
            headers=all_headers,
            body=body,
            query=query or {},
            request_id="REQ-WELFARE-001",
        )

    def welfare_request(self, method, suffix, **kwargs):
        return self.request(method, f"/mock/social-welfare{suffix}", **kwargs)

    def referral_body(self):
        return {
            "service_id": "WELFARE-ESCORT-001",
            "subject": {"display_name": "陳美玲", "age": 80, "district": "氹仔"},
            "need_summary": "需要陪診及往返交通協助。",
            "preferred_contact": {"method": "phone", "time_window": "weekday_afternoon", "phone": "+853-6234-5678"},
            "consents": {"data_sharing": True},
            "confirmation": {"confirmation_id": "CONF-WELFARE-1"},
        }

    def test_service_search_filters_catalogue(self):
        response = self.backend.handle(
            self.welfare_request("GET", "/services", query={"keyword": ["陪診"], "district": ["氹仔"], "active_only": ["true"]})
        )
        self.assertEqual(response.status, 200)
        self.assertTrue(response.body["data"]["services"])
        self.assertTrue(all("氹仔" in item["districts"] for item in response.body["data"]["services"]))

    def test_referral_requires_user_consent_and_confirmation(self):
        no_user = self.backend.handle(
            self.welfare_request("POST", "/referrals", user=None, body=self.referral_body(), **{"Idempotency-Key": "REF-1"})
        )
        self.assertEqual(no_user.status, 401)
        no_consent = self.referral_body()
        no_consent["consents"]["data_sharing"] = False
        response = self.backend.handle(
            self.welfare_request("POST", "/referrals", body=no_consent, **{"Idempotency-Key": "REF-2"})
        )
        self.assertEqual(response.status, 422)
        self.assertEqual(response.body["error"]["code"], "CONSENT_REQUIRED")
        no_confirmation = self.referral_body()
        no_confirmation.pop("confirmation")
        response = self.backend.handle(
            self.welfare_request("POST", "/referrals", body=no_confirmation, **{"Idempotency-Key": "REF-3"})
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(response.body["error"]["code"], "CONFIRMATION_REQUIRED")

    def test_referral_is_created_idempotently_and_user_scoped(self):
        request = self.welfare_request("POST", "/referrals", body=self.referral_body(), **{"Idempotency-Key": "REF-1"})
        first = self.backend.handle(request)
        second = self.backend.handle(request)
        self.assertEqual(first.status, 201)
        self.assertEqual(first.body, second.body)
        referral_id = first.body["data"]["referral"]["referral_id"]
        self.assertEqual(first.body["data"]["referral"]["status"], "PENDING")
        found = self.backend.handle(self.welfare_request("GET", f"/referrals/{referral_id}"))
        self.assertEqual(found.status, 200)
        hidden = self.backend.handle(self.welfare_request("GET", f"/referrals/{referral_id}", user="USR-OTHER"))
        self.assertEqual(hidden.status, 404)

    def test_assign_referral_adds_mock_case_worker(self):
        created = self.backend.handle(
            self.welfare_request("POST", "/referrals", body=self.referral_body(), **{"Idempotency-Key": "REF-1"})
        )
        referral_id = created.body["data"]["referral"]["referral_id"]
        assigned = self.backend.handle(
            self.welfare_request(
                "POST",
                f"/referrals/{referral_id}/assign",
                body={"case_worker_id": "CW-001"},
                **{"Idempotency-Key": "ASSIGN-1"},
            )
        )
        self.assertEqual(assigned.status, 200)
        self.assertEqual(assigned.body["data"]["referral"]["status"], "ASSIGNED")
        self.assertEqual(assigned.body["data"]["referral"]["assigned_worker"]["case_worker_id"], "CW-001")
        repeated = self.backend.handle(
            self.welfare_request(
                "POST", f"/referrals/{referral_id}/assign", body={"case_worker_id": "CW-001"}, **{"Idempotency-Key": "ASSIGN-1"}
            )
        )
        self.assertEqual(repeated.body, assigned.body)

    def test_assign_unknown_or_already_assigned_is_rejected(self):
        unknown = self.backend.handle(
            self.welfare_request("POST", "/referrals/REF-UNKNOWN/assign", body={}, **{"Idempotency-Key": "ASSIGN-X"})
        )
        self.assertEqual(unknown.status, 404)
        created = self.backend.handle(
            self.welfare_request("POST", "/referrals", body=self.referral_body(), **{"Idempotency-Key": "REF-1"})
        )
        referral_id = created.body["data"]["referral"]["referral_id"]
        self.backend.handle(
            self.welfare_request("POST", f"/referrals/{referral_id}/assign", body={}, **{"Idempotency-Key": "ASSIGN-1"})
        )
        duplicate = self.backend.handle(
            self.welfare_request("POST", f"/referrals/{referral_id}/assign", body={}, **{"Idempotency-Key": "ASSIGN-2"})
        )
        self.assertEqual(duplicate.status, 409)
        self.assertEqual(duplicate.body["error"]["code"], "REFERRAL_ALREADY_ASSIGNED")


if __name__ == "__main__":
    unittest.main()
