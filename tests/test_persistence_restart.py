import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from mock_backends.core.clock import FixedClock, MACAU_TZ
from mock_backends.core.http import BackendRequest
from mock_backends.server import create_application


class PersistenceRestartTests(unittest.TestCase):
    def test_referral_survives_new_application_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = FixedClock(datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ))
            first = create_application(Path(directory), clock=clock)
            body = {
                "service_id": "WELFARE-ESCORT-001",
                "subject": {"display_name": "陳美玲", "age": 80},
                "need_summary": "需要陪診協助。",
                "preferred_contact": {"method": "phone"},
                "consents": {"data_sharing": True},
                "confirmation": {"confirmation_id": "CONF-RESTART"},
            }
            request = BackendRequest(
                method="POST",
                path="/mock/social-welfare/referrals",
                headers={"X-Mock-User-Id": "USR-RESTART", "Idempotency-Key": "REF-RESTART"},
                body=body,
                request_id="REQ-RESTART-1",
            )
            created = first.dispatch(request)
            self.assertEqual(created.status, 201)
            referral_id = created.body["data"]["referral"]["referral_id"]

            second = create_application(Path(directory), clock=clock)
            found = second.dispatch(
                BackendRequest(
                    method="GET",
                    path=f"/mock/social-welfare/referrals/{referral_id}",
                    headers={"X-Mock-User-Id": "USR-RESTART"},
                    request_id="REQ-RESTART-2",
                )
            )
            self.assertEqual(found.status, 200)
            self.assertEqual(found.body["data"]["referral"]["referral_id"], referral_id)


if __name__ == "__main__":
    unittest.main()
