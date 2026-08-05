import unittest
from datetime import datetime

from mock_backends.core.clock import FixedClock, MACAU_TZ
from mock_backends.core.http import BackendRequest
from mock_backends.core.idempotency import RepositoryIdempotencyStore
from mock_backends.core.ids import SequentialIdGenerator
from mock_backends.core.persistence import MemoryRepository
from mock_backends.medical.backend import MedicalBackend
from mock_backends.medical.service import MedicalService


class MedicalBackendTests(unittest.TestCase):
    def setUp(self):
        clock = FixedClock(datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ))
        self.service = MedicalService(
            clock=clock,
            ids=SequentialIdGenerator(),
            appointment_repository=MemoryRepository(),
            task_repository=MemoryRepository(),
            idempotency=RepositoryIdempotencyStore(MemoryRepository()),
        )
        self.backend = MedicalBackend(self.service)

    def request(self, method, path, patient="P-10001", body=None, query=None, **headers):
        all_headers = {"Authorization": "Bearer mock-user-token"}
        if patient is not None:
            all_headers["X-Patient-Id"] = patient
        all_headers.update(headers)
        return BackendRequest(
            method=method,
            path=path,
            headers=all_headers,
            body=body,
            query=query or {},
            request_id="REQ-MEDICAL-001",
        )

    def medical_request(self, method, suffix, **kwargs):
        return self.request(method, f"/mock/medical/v1{suffix}", **kwargs)

    def registration_body(self, slot_id="SLOT-REG-20260812-CARDIO-1030"):
        return {
            "patient_id": "P-10001",
            "department_id": "DEPT-CARDIO",
            "doctor_id": "DOC-001",
            "slot_id": slot_id,
            "visit_reason": "覆診",
            "consent": True,
        }

    def appointment_body(self, slot_id="SLOT-US-20260812-1400", referral="APT-REF-1"):
        return {
            "patient_id": "P-10001",
            "service_id": "SERVICE-US-001",
            "slot_id": slot_id,
            "referring_appointment_id": referral,
            "administrative_note": "請按指示提前報到",
            "consent": True,
        }

    def test_patient_context_is_required(self):
        response = self.backend.handle(self.medical_request("GET", "/appointments", patient=None))
        self.assertEqual(response.status, 401)
        self.assertEqual(response.body["error"]["code"], "AUTH_REQUIRED")

    def test_department_and_doctor_lookup(self):
        departments = self.backend.handle(
            self.medical_request("GET", "/departments", patient=None, query={"keyword": ["心臟"]})
        )
        self.assertEqual(departments.status, 200)
        self.assertEqual(departments.body["data"][0]["id"], "DEPT-CARDIO")
        doctors = self.backend.handle(
            self.medical_request("GET", "/departments/DEPT-CARDIO/doctors", patient="P-10001")
        )
        self.assertEqual(doctors.status, 200)
        self.assertEqual(doctors.body["meta"]["total"], 2)

    def test_registration_slots_filter_and_booking_window(self):
        response = self.backend.handle(
            self.medical_request(
                "GET",
                "/registration-slots",
                query={"department_id": ["DEPT-CARDIO"], "date": ["2026-08-12"], "session": ["morning"]},
            )
        )
        self.assertEqual(response.status, 200)
        self.assertTrue(response.body["data"])
        self.assertTrue(all(item["department_id"] == "DEPT-CARDIO" for item in response.body["data"]))
        outside = self.backend.handle(
            self.medical_request(
                "GET", "/registration-slots", query={"department_id": ["DEPT-CARDIO"], "date": ["2026-09-01"]}
            )
        )
        self.assertEqual(outside.status, 422)
        self.assertEqual(outside.body["error"]["code"], "BOOKING_WINDOW_EXCEEDED")

    def test_registration_validates_patient_consent_and_slot(self):
        mismatch = self.backend.handle(
            self.medical_request(
                "POST", "/registrations", body={**self.registration_body(), "patient_id": "P-OTHER"}, **{"Idempotency-Key": "REG-1"}
            )
        )
        self.assertEqual(mismatch.status, 403)
        self.assertEqual(mismatch.body["error"]["code"], "PATIENT_CONTEXT_MISMATCH")
        no_consent = self.registration_body()
        no_consent["consent"] = False
        response = self.backend.handle(
            self.medical_request("POST", "/registrations", body=no_consent, **{"Idempotency-Key": "REG-2"})
        )
        self.assertEqual(response.status, 422)
        self.assertEqual(response.body["error"]["code"], "CONSENT_REQUIRED")
        unknown_slot = self.backend.handle(
            self.medical_request(
                "POST", "/registrations", body=self.registration_body("SLOT-UNKNOWN"), **{"Idempotency-Key": "REG-3"}
            )
        )
        self.assertEqual(unknown_slot.status, 404)
        self.assertEqual(unknown_slot.body["error"]["code"], "SLOT_NOT_FOUND")

    def test_registration_returns_appointment_task_and_consumes_slot(self):
        request = self.medical_request(
            "POST", "/registrations", body=self.registration_body(), **{"Idempotency-Key": "REG-1"}
        )
        first = self.backend.handle(request)
        repeated = self.backend.handle(request)
        self.assertEqual(first.status, 201)
        self.assertEqual(first.body, repeated.body)
        self.assertEqual(first.body["data"]["resourceType"], "Appointment")
        self.assertEqual(first.body["task"]["status"], "completed")
        self.assertIn("registration_number", first.body["data"])
        refreshed = self.backend.handle(
            self.medical_request(
                "GET", "/registration-slots", query={"department_id": ["DEPT-CARDIO"], "date": ["2026-08-12"]}
            )
        )
        self.assertEqual(refreshed.body["data"][0]["remaining"], 5)

    def test_appointment_services_require_referral_and_are_patient_scoped(self):
        services = self.backend.handle(
            self.medical_request("GET", "/appointment-services", patient=None, query={"type": ["examination"]})
        )
        self.assertEqual(services.status, 200)
        self.assertEqual(services.body["data"][0]["id"], "SERVICE-US-001")
        no_referral = self.appointment_body()
        no_referral.pop("referring_appointment_id")
        response = self.backend.handle(
            self.medical_request("POST", "/appointments", body=no_referral, **{"Idempotency-Key": "APT-1"})
        )
        self.assertEqual(response.status, 422)
        self.assertEqual(response.body["error"]["code"], "REFERRAL_REQUIRED")

    def test_appointment_catalog_exposes_three_services_and_three_slots_each(self):
        services = self.backend.handle(
            self.medical_request("GET", "/appointment-services", patient=None)
        )
        service_ids = {item["id"] for item in services.body["data"]}
        self.assertEqual(
            service_ids,
            {"SERVICE-US-001", "SERVICE-PT-001", "SERVICE-ECHO-001"},
        )

        for service_id in service_ids:
            slots = self.backend.handle(
                self.medical_request(
                    "GET",
                    "/appointment-slots",
                    query={
                        "service_id": [service_id],
                        "date_from": ["2026-08-10"],
                        "date_to": ["2026-08-14"],
                    },
                )
            )
            self.assertEqual(slots.body["meta"]["total"], 3)
            self.assertEqual(len(slots.body["data"]), 3)
            self.assertEqual(
                {item["service_id"] for item in slots.body["data"]},
                {service_id},
            )
            self.assertEqual(
                len({item["start"] for item in slots.body["data"]}),
                3,
            )

    def test_appointment_services_hide_full_services_but_keep_available_services(self):
        for slot_id in (
            "SLOT-PT-20260813-1000",
            "SLOT-PT-20260812-1000",
            "SLOT-PT-20260814-1400",
        ):
            for index in range(2):
                self.service.appointment_repository.insert({
                    "id": f"APT-PT-FULL-{slot_id}-{index}",
                    "patient_id": f"P-OTHER-{slot_id}-{index}",
                    "slot_id": slot_id,
                    "status": "confirmed",
                })

        services = self.backend.handle(
            self.medical_request("GET", "/appointment-services", patient=None)
        )

        self.assertEqual(services.status, 200)
        service_ids = {item["id"] for item in services.body["data"]}
        self.assertNotIn("SERVICE-PT-001", service_ids)
        self.assertIn("SERVICE-US-001", service_ids)
        self.assertIn("SERVICE-ECHO-001", service_ids)

    def test_appointment_create_list_detail_and_task_do_not_leak_patient_data(self):
        created = self.backend.handle(
            self.medical_request("POST", "/appointments", body=self.appointment_body(), **{"Idempotency-Key": "APT-1"})
        )
        self.assertEqual(created.status, 201)
        appointment_id = created.body["data"]["id"]
        task_id = created.body["task"]["id"]
        self.assertEqual(created.body["data"]["status"], "confirmed")
        listed = self.backend.handle(self.medical_request("GET", "/appointments"))
        self.assertEqual(listed.body["meta"]["total"], 1)
        detail = self.backend.handle(self.medical_request("GET", f"/appointments/{appointment_id}"))
        self.assertEqual(detail.body["data"]["id"], appointment_id)
        task = self.backend.handle(self.medical_request("GET", f"/tasks/{task_id}"))
        self.assertEqual(task.body["data"]["status"], "completed")
        hidden_detail = self.backend.handle(
            self.medical_request("GET", f"/appointments/{appointment_id}", patient="P-OTHER")
        )
        self.assertEqual(hidden_detail.status, 404)
        hidden_task = self.backend.handle(
            self.medical_request("GET", f"/tasks/{task_id}", patient="P-OTHER")
        )
        self.assertEqual(hidden_task.status, 404)

    def test_slot_not_available_returns_conflict(self):
        first = self.backend.handle(
            self.medical_request(
                "POST", "/registrations", body=self.registration_body("SLOT-REG-20260812-CARDIO-FULL"), **{"Idempotency-Key": "REG-FULL"}
            )
        )
        self.assertEqual(first.status, 409)
        self.assertEqual(first.body["error"]["code"], "SLOT_NOT_AVAILABLE")

    def test_appointment_slot_can_be_taken_between_search_and_create(self):
        searched = self.backend.handle(
            self.medical_request(
                "GET",
                "/appointment-slots",
                query={
                    "service_id": ["SERVICE-US-001"],
                    "date_from": ["2026-08-10"],
                    "date_to": ["2026-08-14"],
                },
            )
        )
        self.assertEqual(searched.status, 200)
        self.assertEqual(searched.body["data"][0]["remaining"], 1)

        self.service.appointment_repository.insert({
            "id": "APT-OTHER-US-001",
            "patient_id": "P-OTHER",
            "slot_id": "SLOT-US-20260812-1400",
            "status": "confirmed",
        })

        created = self.backend.handle(
            self.medical_request(
                "POST",
                "/appointments",
                body=self.appointment_body(),
                **{"Idempotency-Key": "APT-RACE-1"},
            )
        )

        self.assertEqual(created.status, 409)
        self.assertEqual(created.body["error"]["code"], "SLOT_NOT_AVAILABLE")


if __name__ == "__main__":
    unittest.main()
