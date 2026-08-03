import unittest
from datetime import datetime

from mock_backends.core.clock import FixedClock, MACAU_TZ
from mock_backends.core.http import BackendRequest
from mock_backends.core.idempotency import RepositoryIdempotencyStore
from mock_backends.core.ids import SequentialIdGenerator
from mock_backends.core.persistence import MemoryRepository
from mock_backends.one_account.backend import OneAccountBackend
from mock_backends.one_account.service import OneAccountService


class OneAccountBackendTests(unittest.TestCase):
    def setUp(self):
        clock = FixedClock(datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ))
        self.service = OneAccountService(
            clock=clock,
            ids=SequentialIdGenerator(),
            application_repository=MemoryRepository(),
            ticket_repository=MemoryRepository(),
            idempotency=RepositoryIdempotencyStore(MemoryRepository()),
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
            request_id="REQ-TEST-001",
        )

    def pension_body(self):
        return {
            "applicant": {
                "full_name": "陳美玲",
                "id_document_number": "MOCK-1234567(8)",
                "date_of_birth": "1946-05-22",
                "phone": "+853-6234-5678",
            },
            "payment_account": {"account_type": "bank_account", "account_number": "MOCK-000123"},
            "documents": [
                {"document_type": "identity_document", "file_id": "FILE-1"},
                {"document_type": "bank_account_proof", "file_id": "FILE-2"},
            ],
            "consents": {"data_processing": True},
            "confirmation": {"confirmation_id": "CONF-1", "confirmed_at": "2026-08-03T09:00:00+08:00"},
        }

    def test_pension_requires_user_context(self):
        response = self.backend.handle(
            self.request(
                "POST",
                "/mock/one-account/pension/applications",
                user=None,
                body=self.pension_body(),
                **{"Idempotency-Key": "PEN-1"},
            )
        )
        self.assertEqual(response.status, 401)
        self.assertEqual(response.body["error"]["code"], "AUTH_REQUIRED")

    def test_pension_validates_documents_and_consent(self):
        missing = self.pension_body()
        missing["documents"] = []
        response = self.backend.handle(
            self.request("POST", "/mock/one-account/pension/applications", body=missing, **{"Idempotency-Key": "PEN-1"})
        )
        self.assertEqual(response.status, 422)
        self.assertEqual(response.body["error"]["code"], "MISSING_DOCUMENT")

        not_consented = self.pension_body()
        not_consented["consents"]["data_processing"] = False
        response = self.backend.handle(
            self.request(
                "POST", "/mock/one-account/pension/applications", body=not_consented, **{"Idempotency-Key": "PEN-2"}
            )
        )
        self.assertEqual(response.status, 422)
        self.assertEqual(response.body["error"]["code"], "CONSENT_REQUIRED")

    def test_pension_is_idempotent(self):
        request = self.request(
            "POST",
            "/mock/one-account/pension/applications",
            body=self.pension_body(),
            **{"Idempotency-Key": "PEN-1"},
        )
        first = self.backend.handle(request)
        second = self.backend.handle(request)
        self.assertEqual(first.status, 201)
        self.assertEqual(first.body, second.body)
        self.assertEqual(len(self.service.application_repository.list()), 1)

        changed = self.pension_body()
        changed["applicant"]["full_name"] = "李美玲"
        conflict = self.backend.handle(
            self.request(
                "POST",
                "/mock/one-account/pension/applications",
                body=changed,
                **{"Idempotency-Key": "PEN-1"},
            )
        )
        self.assertEqual(conflict.status, 409)
        self.assertEqual(conflict.body["error"]["code"], "IDEMPOTENCY_KEY_REUSED")

    def test_cash_sharing_plan_and_missing_year(self):
        response = self.backend.handle(
            self.request("GET", "/mock/one-account/cash-sharing-plan", query={"year": ["2026"]})
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["data"]["plan"]["plan_id"], "CSP-2026")

        missing = self.backend.handle(
            self.request("GET", "/mock/one-account/cash-sharing-plan", query={"year": ["2025"]})
        )
        self.assertEqual(missing.status, 404)
        self.assertEqual(missing.body["error"]["code"], "PLAN_NOT_FOUND")

    def queue_body(self, kind="gsc"):
        if kind == "gsc":
            return {
                "service_center_id": "GSC-MAIN",
                "service_type": "general_counter",
                "requested_date": "2026-08-04",
                "party_size": 1,
                "contact_phone": "+853-6234-5678",
                "confirmation": {"confirmation_id": "CONF-Q-1"},
            }
        return {
            "service_center_id": "IDB-MAIN",
            "service_type": "identity_card_replacement",
            "requested_date": "2026-08-05",
            "document_type": "MACAU_ID",
            "contact_phone": "+853-6234-5678",
            "confirmation": {"confirmation_id": "CONF-Q-2"},
        }

    def test_queue_ticket_requires_confirmation_and_is_user_scoped(self):
        missing_confirmation = self.queue_body()
        missing_confirmation.pop("confirmation")
        response = self.backend.handle(
            self.request(
                "POST",
                "/mock/one-account/queue-tickets/government-service-center",
                body=missing_confirmation,
                **{"Idempotency-Key": "Q-1"},
            )
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(response.body["error"]["code"], "CONFIRMATION_REQUIRED")

        created = self.backend.handle(
            self.request(
                "POST",
                "/mock/one-account/queue-tickets/government-service-center",
                body=self.queue_body(),
                **{"Idempotency-Key": "Q-1"},
            )
        )
        self.assertEqual(created.status, 201)
        listed = self.backend.handle(self.request("GET", "/mock/one-account/my/queue-tickets"))
        self.assertEqual(len(listed.body["data"]["tickets"]), 1)

        other_user = self.backend.handle(
            self.request("GET", "/mock/one-account/my/queue-tickets", user="USR-OTHER")
        )
        self.assertEqual(other_user.body["data"]["tickets"], [])

    def test_idb_queue_ticket_uses_idb_catalogue(self):
        response = self.backend.handle(
            self.request(
                "POST",
                "/mock/one-account/queue-tickets/identification-services-bureau",
                body=self.queue_body("idb"),
                **{"Idempotency-Key": "Q-IDB-1"},
            )
        )
        self.assertEqual(response.status, 201)
        self.assertEqual(response.body["data"]["ticket"]["service_center_id"], "IDB-MAIN")


if __name__ == "__main__":
    unittest.main()
