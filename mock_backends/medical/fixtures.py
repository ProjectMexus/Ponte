"""FHIR-inspired read-only catalogues for the medical demo."""

from __future__ import annotations

from copy import deepcopy


DEPARTMENTS = [
    {"resourceType": "Organization", "id": "DEPT-CARDIO", "name": "心臟科", "name_en": "Cardiology", "location_id": "LOC-MAIN-OPD", "active": True},
    {"resourceType": "Organization", "id": "DEPT-IMAGING", "name": "影像科", "name_en": "Imaging", "location_id": "LOC-IMAGING-CENTER", "active": True},
    {"resourceType": "Organization", "id": "DEPT-REHAB", "name": "復康治療科", "name_en": "Rehabilitation", "location_id": "LOC-REHAB-01", "active": True},
]

DOCTORS = [
    {"resourceType": "Practitioner", "id": "DOC-001", "name": "陳醫生", "name_en": "Dr. Chan", "department_id": "DEPT-CARDIO", "specialty": "心臟科", "active": True},
    {"resourceType": "Practitioner", "id": "DOC-002", "name": "李醫生", "name_en": "Dr. Lee", "department_id": "DEPT-CARDIO", "specialty": "心臟科", "active": True},
    {"resourceType": "Practitioner", "id": "DOC-003", "name": "周醫生", "name_en": "Dr. Chow", "department_id": "DEPT-REHAB", "specialty": "復康治療", "active": True},
]

REGISTRATION_SLOTS = [
    {"resourceType": "Slot", "id": "SLOT-REG-20260812-CARDIO-1030", "status": "free", "slot_type": "outpatient_registration", "department_id": "DEPT-CARDIO", "doctor_id": "DOC-001", "location_id": "LOC-MAIN-OPD", "start": "2026-08-12T10:30:00+08:00", "end": "2026-08-12T10:45:00+08:00", "capacity": 10, "remaining": 6, "session": "morning"},
    {"resourceType": "Slot", "id": "SLOT-REG-20260812-CARDIO-1100", "status": "free", "slot_type": "outpatient_registration", "department_id": "DEPT-CARDIO", "doctor_id": "DOC-001", "location_id": "LOC-MAIN-OPD", "start": "2026-08-12T11:00:00+08:00", "end": "2026-08-12T11:15:00+08:00", "capacity": 10, "remaining": 3, "session": "morning"},
    {"resourceType": "Slot", "id": "SLOT-REG-20260812-CARDIO-1400", "status": "free", "slot_type": "outpatient_registration", "department_id": "DEPT-CARDIO", "doctor_id": "DOC-002", "location_id": "LOC-MAIN-OPD", "start": "2026-08-12T14:00:00+08:00", "end": "2026-08-12T14:15:00+08:00", "capacity": 8, "remaining": 8, "session": "afternoon"},
    {"resourceType": "Slot", "id": "SLOT-REG-20260812-CARDIO-FULL", "status": "busy", "slot_type": "outpatient_registration", "department_id": "DEPT-CARDIO", "doctor_id": "DOC-001", "location_id": "LOC-MAIN-OPD", "start": "2026-08-12T15:00:00+08:00", "end": "2026-08-12T15:15:00+08:00", "capacity": 1, "remaining": 0, "session": "afternoon"},
]

APPOINTMENT_SERVICES = [
    {"resourceType": "HealthcareService", "id": "SERVICE-US-001", "name": "腹部超聲波檢查", "name_en": "Abdominal Ultrasound", "type": "examination", "department_id": "DEPT-IMAGING", "location_id": "LOC-IMAGING-CENTER", "duration_minutes": 30, "requires_referral": True, "active": True},
    {"resourceType": "HealthcareService", "id": "SERVICE-PT-001", "name": "物理治療", "name_en": "Physical Therapy", "type": "treatment", "department_id": "DEPT-REHAB", "location_id": "LOC-REHAB-01", "duration_minutes": 45, "requires_referral": True, "active": True},
    {"resourceType": "HealthcareService", "id": "SERVICE-ECHO-001", "name": "心臟超聲波檢查", "name_en": "Cardiac Ultrasound", "type": "examination", "department_id": "DEPT-CARDIO", "location_id": "LOC-MAIN-OPD", "duration_minutes": 30, "requires_referral": True, "active": True},
]

APPOINTMENT_SLOTS = [
    {"resourceType": "Slot", "id": "SLOT-US-20260812-1400", "status": "free", "slot_type": "examination", "service_id": "SERVICE-US-001", "department_id": "DEPT-IMAGING", "location_id": "LOC-IMAGING-CENTER", "start": "2026-08-12T14:00:00+08:00", "end": "2026-08-12T14:30:00+08:00", "capacity": 1, "remaining": 1},
    {"resourceType": "Slot", "id": "SLOT-PT-20260813-1000", "status": "free", "slot_type": "treatment", "service_id": "SERVICE-PT-001", "department_id": "DEPT-REHAB", "location_id": "LOC-REHAB-01", "start": "2026-08-13T10:00:00+08:00", "end": "2026-08-13T10:45:00+08:00", "capacity": 2, "remaining": 2},
    {"resourceType": "Slot", "id": "SLOT-US-20260813-0930", "status": "free", "slot_type": "examination", "service_id": "SERVICE-US-001", "department_id": "DEPT-IMAGING", "location_id": "LOC-IMAGING-CENTER", "start": "2026-08-13T09:30:00+08:00", "end": "2026-08-13T10:00:00+08:00", "capacity": 1, "remaining": 1},
    {"resourceType": "Slot", "id": "SLOT-US-20260814-1500", "status": "free", "slot_type": "examination", "service_id": "SERVICE-US-001", "department_id": "DEPT-IMAGING", "location_id": "LOC-IMAGING-CENTER", "start": "2026-08-14T15:00:00+08:00", "end": "2026-08-14T15:30:00+08:00", "capacity": 1, "remaining": 1},
    {"resourceType": "Slot", "id": "SLOT-PT-20260812-1000", "status": "free", "slot_type": "treatment", "service_id": "SERVICE-PT-001", "department_id": "DEPT-REHAB", "location_id": "LOC-REHAB-01", "start": "2026-08-12T10:00:00+08:00", "end": "2026-08-12T10:45:00+08:00", "capacity": 2, "remaining": 2},
    {"resourceType": "Slot", "id": "SLOT-PT-20260814-1400", "status": "free", "slot_type": "treatment", "service_id": "SERVICE-PT-001", "department_id": "DEPT-REHAB", "location_id": "LOC-REHAB-01", "start": "2026-08-14T14:00:00+08:00", "end": "2026-08-14T14:45:00+08:00", "capacity": 2, "remaining": 2},
    {"resourceType": "Slot", "id": "SLOT-ECHO-20260812-0900", "status": "free", "slot_type": "examination", "service_id": "SERVICE-ECHO-001", "department_id": "DEPT-CARDIO", "location_id": "LOC-MAIN-OPD", "start": "2026-08-12T09:00:00+08:00", "end": "2026-08-12T09:30:00+08:00", "capacity": 1, "remaining": 1},
    {"resourceType": "Slot", "id": "SLOT-ECHO-20260813-1500", "status": "free", "slot_type": "examination", "service_id": "SERVICE-ECHO-001", "department_id": "DEPT-CARDIO", "location_id": "LOC-MAIN-OPD", "start": "2026-08-13T15:00:00+08:00", "end": "2026-08-13T15:30:00+08:00", "capacity": 1, "remaining": 1},
    {"resourceType": "Slot", "id": "SLOT-ECHO-20260814-1100", "status": "free", "slot_type": "examination", "service_id": "SERVICE-ECHO-001", "department_id": "DEPT-CARDIO", "location_id": "LOC-MAIN-OPD", "start": "2026-08-14T11:00:00+08:00", "end": "2026-08-14T11:30:00+08:00", "capacity": 1, "remaining": 1},
]


def departments() -> list[dict]:
    return deepcopy(DEPARTMENTS)


def doctors() -> list[dict]:
    return deepcopy(DOCTORS)


def registration_slots() -> list[dict]:
    return deepcopy(REGISTRATION_SLOTS)


def appointment_services() -> list[dict]:
    return deepcopy(APPOINTMENT_SERVICES)


def appointment_slots() -> list[dict]:
    return deepcopy(APPOINTMENT_SLOTS)
