# Medical Appointment Slot Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** When a patient already has a valid appointment for one medical service, the recovery flow must offer other currently available appointment services and their slots instead of searching only the conflicting service.

**Architecture:** Trace the recovery action from the middleware controller through the medical service catalog and slot search. Preserve the existing backend contract, but make the recovery search explicitly service-agnostic when the user is choosing an alternative after `DUPLICATE_BOOKING`; the selected service must still be passed to the final appointment creation step.

**Tech Stack:** Python 3, unittest, mock medical backend, middleware task manager, JSON Lines persistence.

## Global Constraints

- Do not mutate persisted mock appointment data as part of the fix.
- Keep the normal first-time booking flow service-specific.
- Keep the existing user-facing recovery actions and payload contract compatible.
- Do not add external dependencies.

### Task 1: Root-cause trace and regression test

**Files:**
- Inspect: `middleware/controller.py`, `middleware/task_manager/recovery.py`, `mock_backends/medical/service.py`, `mock_backends/medical/backend.py`
- Modify: the smallest existing test file covering the failing layer

- [x] Reproduce the current behavior with the persisted appointment/service fixture and record the exact request and response.
- [x] Add a regression test that fails because the recovery search keeps `SERVICE-PT-001` instead of exposing `SERVICE-US-001`.

### Task 2: Minimal implementation

**Files:**
- Modify: the middleware/controller or recovery boundary identified by Task 1
- Modify: the corresponding regression test if the confirmed contract requires an assertion adjustment

- [x] Make the recovery service-selection search omit the conflicting service filter while retaining the date window and patient context.
- [x] Preserve the selected alternative service id when building `create_appointment` input.

### Task 3: Verification and integration

**Files:**
- Update: this plan checklist with completed steps

- [x] Run focused medical and middleware tests.
- [x] Run the complete unittest suite and a direct API-level reproduction. The focused 51-test run and the real MCP/backend full-stack reproduction passed; the complete 217-test discovery reported only the two pre-existing environment/unrelated failures documented in the handoff.
- [x] Commit the implementation on the new branch (`4ddc7c0`, amended once after the final full-stack assertion).
- [ ] Merge the branch into `dev` and verify the resulting branch status and tests.
