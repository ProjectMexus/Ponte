import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from mock_backends.core.clock import FixedClock, MACAU_TZ
from mock_backends.core.http import BackendRequest
from mock_backends.server import create_application


class PersistenceRestartTests(unittest.TestCase):
    def test_medical_booking_survives_restart_and_writes_txt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = FixedClock(datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ))
            first = create_application(root, clock=clock)
            registration = BackendRequest(
                method="POST",
                path="/mock/medical/v1/registrations",
                headers={
                    "Authorization": "Bearer mock-user-token",
                    "X-Patient-Id": "P-10001",
                    "Idempotency-Key": "MED-REG-RESTART",
                },
                body={
                    "patient_id": "P-10001",
                    "department_id": "DEPT-CARDIO",
                    "doctor_id": "DOC-001",
                    "slot_id": "SLOT-REG-20260812-CARDIO-1030",
                    "consent": True,
                },
                request_id="REQ-MED-RESTART-1",
            )
            first_created = first.dispatch(registration)
            self.assertEqual(first_created.status, 201)
            first_appointment_id = first_created.body["data"]["id"]
            first_task_id = first_created.body["task"]["id"]

            medical_root = root / "medical"
            for filename in ("appointments.txt", "tasks.txt", "idempotency.txt"):
                self.assertTrue((medical_root / filename).exists())

            second = create_application(root, clock=clock)
            listed = second.dispatch(
                BackendRequest(
                    method="GET",
                    path="/mock/medical/v1/appointments",
                    headers={
                        "Authorization": "Bearer mock-user-token",
                        "X-Patient-Id": "P-10001",
                    },
                    request_id="REQ-MED-RESTART-2",
                )
            )
            self.assertEqual(listed.status, 200)
            self.assertEqual(listed.body["meta"]["total"], 1)
            self.assertEqual(listed.body["data"][0]["id"], first_appointment_id)

            appointment = second.dispatch(
                BackendRequest(
                    method="POST",
                    path="/mock/medical/v1/appointments",
                    headers={
                        "Authorization": "Bearer mock-user-token",
                        "X-Patient-Id": "P-10001",
                        "Idempotency-Key": "MED-APT-RESTART",
                    },
                    body={
                        "patient_id": "P-10001",
                        "service_id": "SERVICE-US-001",
                        "slot_id": "SLOT-US-20260812-1400",
                        "referring_appointment_id": "APT-REF-1",
                        "consent": True,
                    },
                    request_id="REQ-MED-RESTART-3",
                )
            )
            self.assertEqual(appointment.status, 201)
            self.assertNotEqual(appointment.body["data"]["id"], first_appointment_id)
            self.assertNotEqual(appointment.body["task"]["id"], first_task_id)
            self.assertEqual(len((medical_root / "appointments.txt").read_text(encoding="utf-8").splitlines()), 2)
            self.assertEqual(len((medical_root / "tasks.txt").read_text(encoding="utf-8").splitlines()), 2)

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
