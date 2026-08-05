# Medical Appointment Body-check Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the medical mock catalog to three appointment services with three deterministic available slots per service so recovery flows can offer alternative times and services.

**Architecture:** Keep `mock_backends/medical/fixtures.py` as the single source of catalog data. Preserve the existing `MedicalService` availability and repository-consumption logic, because it already subtracts booked records from each slot and hides a service only when all its slots are full. Update the focused medical tests and the API document to describe the expanded fixture contract; do not modify middleware recovery.

**Tech Stack:** Python 3, `unittest`, FHIR-inspired static fixtures, Markdown API documentation.

## Global Constraints

- Preserve existing service IDs `SERVICE-US-001` and `SERVICE-PT-001`.
- Add `SERVICE-ECHO-001` under the active `DEPT-CARDIO` department.
- Provide exactly three distinct appointment slots for each active service.
- Keep every fixture slot within the fixed test clock's 14-day booking window from 2026-08-03 through 2026-08-17.
- Do not change middleware recovery behavior, persistence schema, or external dependencies.

---

### Task 1: Add regression coverage for the expanded appointment catalog

**Files:**
- Modify: `tests/medical/test_medical_backend.py`

**Interfaces:**
- Consumes: `MedicalBackend.handle()` through the existing `medical_request()` helper.
- Produces: A focused contract test proving the service list contains `SERVICE-US-001`, `SERVICE-PT-001`, and `SERVICE-ECHO-001`, and each service returns three unique slots.

- [x] **Step 1: Add the failing catalog test**

Add this method to `MedicalBackendTests`:

```python
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
```

Update `test_appointment_services_hide_full_services_but_keep_available_services`
so it fills every physical-therapy slot instead of only
`SLOT-PT-20260813-1000`:

```python
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
```

Keep the existing assertions that `SERVICE-PT-001` is absent and
`SERVICE-US-001` is present, and add:

```python
        self.assertIn("SERVICE-ECHO-001", service_ids)
```

- [x] **Step 2: Run the focused test and verify it fails for the old fixtures**

Run:

```powershell
python -m unittest tests.medical.test_medical_backend.MedicalBackendTests.test_appointment_catalog_exposes_three_services_and_three_slots_each -v
```

Expected: `FAIL`, with the service ID set missing `SERVICE-ECHO-001` and the
old fixture still returning only one slot per existing service.

- [x] **Step 3: Commit the regression test**

```powershell
git add tests/medical/test_medical_backend.py
git commit -m "test: cover expanded medical appointment catalog"
```

### Task 2: Expand the deterministic medical fixtures

**Files:**
- Modify: `mock_backends/medical/fixtures.py`

**Interfaces:**
- Consumes: Existing `DEPT-CARDIO`, `DEPT-IMAGING`, and `DEPT-REHAB` records.
- Produces: `appointment_services()` with three active services and `appointment_slots()` with three available slots for each service.

- [x] **Step 1: Add the third service record**

Append this record to `APPOINTMENT_SERVICES` without changing the existing two
records:

```python
    {"resourceType": "HealthcareService", "id": "SERVICE-ECHO-001", "name": "心臟超聲波檢查", "name_en": "Cardiac Ultrasound", "type": "examination", "department_id": "DEPT-CARDIO", "location_id": "LOC-MAIN-OPD", "duration_minutes": 30, "requires_referral": True, "active": True},
```

- [x] **Step 2: Add two slots to each existing service and three cardiac slots**

Keep the existing `SLOT-US-20260812-1400` and
`SLOT-PT-20260813-1000` records. Add these records to `APPOINTMENT_SLOTS`:

```python
    {"resourceType": "Slot", "id": "SLOT-US-20260813-0930", "status": "free", "slot_type": "examination", "service_id": "SERVICE-US-001", "department_id": "DEPT-IMAGING", "location_id": "LOC-IMAGING-CENTER", "start": "2026-08-13T09:30:00+08:00", "end": "2026-08-13T10:00:00+08:00", "capacity": 1, "remaining": 1},
    {"resourceType": "Slot", "id": "SLOT-US-20260814-1500", "status": "free", "slot_type": "examination", "service_id": "SERVICE-US-001", "department_id": "DEPT-IMAGING", "location_id": "LOC-IMAGING-CENTER", "start": "2026-08-14T15:00:00+08:00", "end": "2026-08-14T15:30:00+08:00", "capacity": 1, "remaining": 1},
    {"resourceType": "Slot", "id": "SLOT-PT-20260812-1000", "status": "free", "slot_type": "treatment", "service_id": "SERVICE-PT-001", "department_id": "DEPT-REHAB", "location_id": "LOC-REHAB-01", "start": "2026-08-12T10:00:00+08:00", "end": "2026-08-12T10:45:00+08:00", "capacity": 2, "remaining": 2},
    {"resourceType": "Slot", "id": "SLOT-PT-20260814-1400", "status": "free", "slot_type": "treatment", "service_id": "SERVICE-PT-001", "department_id": "DEPT-REHAB", "location_id": "LOC-REHAB-01", "start": "2026-08-14T14:00:00+08:00", "end": "2026-08-14T14:45:00+08:00", "capacity": 2, "remaining": 2},
    {"resourceType": "Slot", "id": "SLOT-ECHO-20260812-0900", "status": "free", "slot_type": "examination", "service_id": "SERVICE-ECHO-001", "department_id": "DEPT-CARDIO", "location_id": "LOC-MAIN-OPD", "start": "2026-08-12T09:00:00+08:00", "end": "2026-08-12T09:30:00+08:00", "capacity": 1, "remaining": 1},
    {"resourceType": "Slot", "id": "SLOT-ECHO-20260813-1500", "status": "free", "slot_type": "examination", "service_id": "SERVICE-ECHO-001", "department_id": "DEPT-CARDIO", "location_id": "LOC-MAIN-OPD", "start": "2026-08-13T15:00:00+08:00", "end": "2026-08-13T15:30:00+08:00", "capacity": 1, "remaining": 1},
    {"resourceType": "Slot", "id": "SLOT-ECHO-20260814-1100", "status": "free", "slot_type": "examination", "service_id": "SERVICE-ECHO-001", "department_id": "DEPT-CARDIO", "location_id": "LOC-MAIN-OPD", "start": "2026-08-14T11:00:00+08:00", "end": "2026-08-14T11:30:00+08:00", "capacity": 1, "remaining": 1},
```

- [x] **Step 3: Run the focused medical tests**

Run:

```powershell
python -m unittest tests.medical.test_medical_backend -v
```

Expected: all medical backend tests pass, including the new three-service and
three-slot assertions. Existing appointment creation and slot-race tests must
continue to use `SLOT-US-20260812-1400` unchanged.

- [ ] **Step 4: Commit the fixture expansion**

```powershell
git add mock_backends/medical/fixtures.py tests/medical/test_medical_backend.py
git commit -m "feat: expand medical appointment slot fixtures"
```

### Task 3: Synchronize the medical API documentation

**Files:**
- Modify: `docs/api/jinghu-medical-mock-api.md`

**Interfaces:**
- Consumes: The service and slot IDs from `mock_backends/medical/fixtures.py`.
- Produces: Documentation examples that show all three services and the three abdominal-ultrasound slots returned by the documented date range.

- [ ] **Step 1: Update the service catalog example**

In section 7.1, add the `SERVICE-ECHO-001` object after the existing
`SERVICE-PT-001` object and change the metadata from `{"total": 2}` to
`{"total": 3}`. Use the exact service shape:

```json
{
  "resourceType": "HealthcareService",
  "id": "SERVICE-ECHO-001",
  "name": "心臟超聲波檢查",
  "name_en": "Cardiac Ultrasound",
  "type": "examination",
  "department_id": "DEPT-CARDIO",
  "location_id": "LOC-MAIN-OPD",
  "duration_minutes": 30,
  "requires_referral": true,
  "active": true
}
```

- [ ] **Step 2: Update the documented abdominal-ultrasound slot response**

In section 7.2, keep the request range `2026-08-10` through `2026-08-14`
and add the fixture records `SLOT-US-20260813-0930` and
`SLOT-US-20260814-1500` to the response. Change `meta.total` from `1` to
`3`; the three records must retain the exact `start`, `end`, and capacity
values from the fixture.

- [ ] **Step 3: Check documentation references**

Run:

```powershell
rg -n "SERVICE-ECHO-001|SLOT-US-20260813-0930|SLOT-US-20260814-1500|total.*3" docs/api/jinghu-medical-mock-api.md
```

Expected: the new service, both new ultrasound slots, and the updated total
are present in the service/slot examples.

- [ ] **Step 4: Commit the documentation update**

```powershell
git add docs/api/jinghu-medical-mock-api.md
git commit -m "docs: describe expanded medical appointment slots"
```

### Task 4: Full verification and handoff

**Files:**
- Inspect: `mock_backends/medical/fixtures.py`, `tests/medical/test_medical_backend.py`, `docs/api/jinghu-medical-mock-api.md`

**Interfaces:**
- Consumes: All changes from Tasks 1–3.
- Produces: Fresh test evidence and a clean, reviewable branch diff.

- [ ] **Step 1: Run focused medical verification**

```powershell
python -m unittest tests.medical.test_medical_backend -v
```

Expected: exit code 0 and no failed tests.

- [ ] **Step 2: Run the complete unittest suite**

```powershell
python -m unittest discover -v
```

Expected: the suite completes; report any pre-existing unrelated environment
failures separately instead of treating them as proof that this change passed.

- [ ] **Step 3: Check the final diff and repository state**

```powershell
git diff --check
git status --short --branch
git log -4 --oneline --decorate
```

Expected: no whitespace errors, the current branch is
`codex/medical-body-check-slots`, and only the intentional commits are ahead
of the starting point.

- [ ] **Step 4: Review each requirement against evidence**

Confirm from the focused test output and fixture inspection that:

1. The catalog has three services.
2. Each service has three distinct available slots.
3. Existing slot-consumption and full-service filtering behavior still works.
4. The API examples name the new service and its stable slot IDs.
5. No middleware recovery code was changed.
