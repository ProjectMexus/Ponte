# Medical Appointment Body-check Slots Design

## Context

The medical mock backend already supports service discovery, appointment-slot
search, slot consumption, and recovery actions for duplicate bookings. Its
catalog currently contains two appointment services, with only one slot for
each service. That is not enough for an LLM to demonstrate choosing another
time or another appointment service after a booking failure.

## Goal

Expand the deterministic mock catalog to three appointment services, each with
three distinct available appointment slots inside the configured 14-day
booking window. Preserve the existing physical-therapy service for backwards
compatibility and add a cardiac ultrasound examination as the third service.

The resulting service departments are:

| Service | Department | Type | Slots |
| --- | --- | --- | --- |
| 腹部超聲波檢查 | 影像科 | examination | 3 |
| 物理治療 | 復康治療科 | treatment | 3 |
| 心臟超聲波檢查 | 心臟科 | examination | 3 |

All slots remain explicit fixture records so tests and LLM demonstrations
receive stable IDs, dates, locations, and times.

## Scope

### In scope

- Extend `mock_backends/medical/fixtures.py` with the third service.
- Expand the two existing services from one slot to three slots each.
- Add three slots for the new cardiac ultrasound service.
- Keep slot capacity and repository-backed consumption behavior intact.
- Update medical backend tests to cover the three-service, three-slot catalog
  and the full-service filtering behavior.
- Update the medical API document's catalog and slot examples to match the
  fixture data.

### Out of scope

- No changes to the middleware recovery policy or frontend interaction model.
- No dynamic slot generation or new persistence schema.
- No removal or renaming of existing service IDs.
- No external dependencies or real medical-system integration.

## Design

The fixture layer remains the single source of truth. `MedicalService` will
continue to derive availability from each slot's base `remaining` value minus
appointments stored in `appointment_repository`. The existing
`available_only=true` behavior will therefore keep a service visible while at
least one of its three slots has capacity, and will hide it only after every
slot is full.

The new service will use the existing active `DEPT-CARDIO` department and its
`LOC-MAIN-OPD` location. Its three slot dates will be within the fixed clock's
14-day window used by the test suite. Existing service and slot IDs remain
unchanged; new IDs use the `SERVICE-ECHO-001` and `SLOT-ECHO-*` prefixes.

The failure flow remains:

1. The user selects a service and one of its slots.
2. Appointment creation can return `DUPLICATE_BOOKING` or
   `SLOT_NOT_AVAILABLE`.
3. Existing recovery logic offers another available service or another slot,
   alongside cancellation and human assistance where applicable.
4. The selected service ID and slot ID continue through the existing create
   request contract.

## Testing

Add focused assertions that:

- the default appointment-service list contains all three active services;
- each service returns exactly three available slots for a date range covering
  the fixtures;
- booking one slot reduces that slot's remaining capacity without affecting
  the other slots;
- filling every slot for a service removes that service from the default
  `available_only` catalog while other services remain available; and
- existing appointment creation, idempotency, referral validation, and
  conflict behavior continue to pass.

The implementation will be verified with the focused medical tests followed by
the complete unittest discovery suite. The design document itself is the only
change committed before implementation begins.
