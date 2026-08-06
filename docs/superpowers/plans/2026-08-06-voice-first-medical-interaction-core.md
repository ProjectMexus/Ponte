# Voice-first Medical Interaction Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the medical enquiry and appointment Demo workflow onto one modality-neutral event path with canonical task results, deterministic workspace projections, verified receipts, and shared voice/JSON input handling.

**Status:** Implemented in the working tree; focused, middleware, application, MCP, and frontend verification suites pass independently. The combined multi-suite invocation still exceeds the test timeout because of existing cross-suite process behavior. Superseded in architecture by `docs/superpowers/plans/2026-08-06-medical-workflow-extraction-and-cash-sharing.md`, which extracted all medical domain behavior from the Core into `MedicalWorkflow`, added `CashSharingWorkflow`, and limited the legacy controller to elderly activities and MCP diagnostics. The task steps below are retained as the historical migration record.

**Architecture:** Add a small medical `InteractionCore` alongside the existing controller while cash sharing, elderly activities, and diagnostic tools remain on their current path until their own migrations. The new Core owns the simplified session/task/confirmation state and calls the existing `ExecutionPipeline`; `ResponseComposer`, `WorkspaceProjector`, and `DeliveryOrchestrator` convert the Core result into user-facing delivery data. `/api/interactions` and STT-backed `/api/voice/turn` enter the same Core from `EventEnvelope` onward. *(Post-extraction update: confirmation, execution, verification, recovery, and receipt ownership moved from the Core to `MedicalWorkflow`; the Core now only loads/saves the task and selects the workflow.)*

**Tech Stack:** Python standard-library dataclasses and HTTP server, existing MCP `ExecutionPipeline`, existing medical mock backend, browser JavaScript modules, `unittest`/pytest test suite.

## Global Constraints

- Core events use neutral `content`; do not put `language` or `source: voice` in the workflow event.
- `InteractionCore.handle(envelope)` requires `routing.interaction_id` and `routing.session_id`; audit metadata is observability-only.
- Session stores one `active_task_id`; task stores `status`, `current_step`, `facts`, and `pending_confirmation`.
- Confirmation states are only `pending`, `approved`, `rejected`, and `modified`.
- A non-pending confirmation never dispatches execution again.
- `ExecutionPipeline` reports tool execution only; the medical verifier owns business completion.
- Receipt construction uses verified safe facts and backend `receipt.reference` as canonical `receipt_id`.
- Invalid backend results become `awaiting_input` with recovery actions; only unrecoverable program errors become `failed`.
- Workspace actions contain complete server-issued events, including `action_id`; frontend submits them unchanged.
- Response wording cannot change task state, facts, actions, workspace, or receipt.
- TTS and browser speech synthesis are delivery concerns, not workflow concerns.
- Existing legacy routes remain only for not-yet-migrated cash/activity/diagnostic flows; medical traffic uses the new contract and does not pass through a legacy request/response adapter.

---

### Task 1: Add event, task, result, verification, and receipt contracts

**Files:**
- Create: `middleware/interaction_contracts.py`
- Modify: `middleware/session.py`
- Test: `middleware/tests/test_interaction_contracts.py`

**Interfaces:**
- Produces `EventEnvelope.from_json(value)`, `ConfirmationDecision.from_event(event)`, `MedicalTask`, `CanonicalInteractionResult`, `MedicalResultVerifier`, and `ActionReceiptBuilder` for Tasks 2–4.
- Extends `SessionState` with `active_task_id`, `task`, and `interaction_log` without removing fields used by the legacy controller.

- [ ] **Step 1: Write failing contract tests.** Test that an envelope requires `routing.interaction_id`, `routing.session_id`, and an authoritative event; a user utterance accepts `task_id: null`; a confirmation decision requires `action_id`, `task_id`, `confirmation_id`, and one of `approve | reject | modify`; and `language`/`source` are not copied into the domain event.

```python
def test_confirmation_event_keeps_complete_server_target():
    envelope = EventEnvelope.from_json({
        "routing": {"interaction_id": "INT-1", "session_id": "S-1"},
        "event": {
            "type": "confirmation_decision",
            "action_id": "ACT-1",
            "task_id": "TASK-1",
            "confirmation_id": "CONF-1",
            "decision": "approve",
        },
        "audit": {"source": "voice", "language": "yue"},
    })
    decision = ConfirmationDecision.from_event(envelope.event)
    assert decision.action_id == "ACT-1"
    assert decision.decision == "approve"
    assert "source" not in envelope.event
```

- [ ] **Step 2: Run the focused test to verify it fails.**

Run: `python -m pytest middleware/tests/test_interaction_contracts.py -q`

Expected: FAIL because the new contracts do not exist.

- [ ] **Step 3: Implement immutable input/result contracts.** Validate strings and mappings, retain only the allowed domain fields, and make `CanonicalInteractionResult.to_dict()` JSON-safe. Do not expose raw `ToolExecutionResult` data in the canonical result.

- [ ] **Step 4: Implement Demo task state and receipt verification.** `MedicalResultVerifier.verify(result)` must require `result.ok`, an appointment mapping, a task mapping with an ID, and a receipt mapping containing `reference` and `issued_at`. `ActionReceiptBuilder.build(task_id, verified_facts)` must emit `receipt_id`, `kind`, `status`, `issued_at`, `task_id`, and safe appointment fields only.

- [ ] **Step 5: Add the minimal session fields and event log.** Preserve the existing `task_state`, `data`, and legacy fields for non-migrated flows. New Core code uses `state.active_task_id`, `state.task`, and `state.interaction_log` as its authoritative storage.

- [ ] **Step 6: Run focused and existing contract tests.**

Run: `python -m pytest middleware/tests/test_interaction_contracts.py middleware/tests/test_contracts.py -q`

Expected: PASS with no regression in existing session serialization tests.

---

### Task 2: Implement the medical InteractionCore workflow

**Files:**
- Create: `middleware/interaction_core.py`
- Test: `middleware/tests/test_interaction_core.py`

**Interfaces:**
- Consumes `EventEnvelope`, `SessionStore`, `ExecutionPipeline`, `ToolRegistry`, `IntentRecognizer`, and the contracts from Task 1.
- Produces `InteractionCore.handle(envelope) -> CanonicalInteractionResult`.

- [ ] **Step 1: Write failing Core tests for task creation and selection.** Cover a first medical utterance, service selection, slot selection, and the canonical pending confirmation. Inject a fake pipeline returning safe medical tool results so these tests do not start MCP.

```python
def test_slot_selection_issues_server_targeted_confirmation():
    result = core.handle(user_event("select_slot", {
        "action_id": "ACT-SLOT-1",
        "task_id": "TASK-1",
        "slot_id": "SLOT-US-20260807-1500",
    }))
    action = result.allowed_actions[0]
    assert action["event"]["action_id"] == "ACT-CONF-1"
    assert action["event"]["confirmation_id"] == result.confirmation["confirmation_id"]
```

- [ ] **Step 2: Run the focused test to verify it fails.**

Run: `python -m pytest middleware/tests/test_interaction_core.py -q`

Expected: FAIL because `InteractionCore` is not implemented.

- [ ] **Step 3: Implement `InteractionCore.handle`.** Route only these medical events: `user_utterance`, `service_selected`, `slot_selected`, `confirmation_decision`, `recovery_action`, and `cancel_task`. Create one active task per session, record the major interaction log event, and return structured intent/facts/actions without final prose.

- [ ] **Step 4: Implement service and slot progression.** Call `medical.list_appointment_services` for a medical booking request, `medical.search_appointment_slots` for a server-issued service action, and store only safe service/slot facts needed by the workspace. Issue complete action targets with generated `action_id` values for each selectable service, slot, confirmation, and recovery action.

- [ ] **Step 5: Implement confirmation transitions.** Validate task ID, confirmation ID, pending status, and decision. `reject` cancels the task; `modify` marks the confirmation modified and returns to service/slot input; `approve` marks the confirmation approved, sets task status to `executing`, and dispatches `medical.create_appointment` with `idempotency_key` derived from the confirmation ID.

- [ ] **Step 6: Implement verified completion and recovery.** After create returns, verify appointment/task/receipt data before building the receipt. Build the receipt before marking the task `completed`, then attach it and record `execution_completed` and `receipt_created`. Tool failure or invalid backend shape sets `awaiting_input`, stores a safe recovery reason, emits retry/human-help/cancel actions, and creates no receipt.

- [ ] **Step 7: Implement the non-pending confirmation guard.** If the stored confirmation is not `pending`, return the current canonical task result without invoking the pipeline.

- [ ] **Step 8: Run Core tests and existing controller tests.**

Run: `python -m pytest middleware/tests/test_interaction_core.py middleware/tests/test_controller.py middleware/tests/test_recovery.py -q`

Expected: PASS; legacy controller behavior remains available for non-migrated workflows.

---

### Task 3: Add deterministic response, workspace, and delivery projections

**Files:**
- Create: `middleware/interaction_delivery.py`
- Test: `middleware/tests/test_interaction_delivery.py`

**Interfaces:**
- Consumes `CanonicalInteractionResult` from Task 2.
- Produces `ResponseComposer.compose(result)`, `WorkspaceProjector.project(result)`, and `DeliveryOrchestrator.deliver(result, speech_adapter=None, speech_settings=None)`.

- [ ] **Step 1: Write failing projection tests.** Assert that workspace action events preserve complete `action_id`, task ID, confirmation ID, and decision; response text is not used to choose the view; receipt projection contains canonical receipt data only; and TTS failure yields `speech_audio.status == "unavailable"` without mutating the result.

- [ ] **Step 2: Run the focused test to verify it fails.**

Run: `python -m pytest middleware/tests/test_interaction_delivery.py -q`

Expected: FAIL because the projection classes do not exist.

- [ ] **Step 3: Implement deterministic `ResponseComposer`.** Return `display_text` and `speech_text` from `response_intent`, safe facts, status, and allowed actions. Use fixed Cantonese/traditional-Chinese templates for confirmation, recovery, completion, and cancellation. No LLM is required for the Demo; keep the interface replaceable.

- [ ] **Step 4: Implement deterministic `WorkspaceProjector`.** Produce `view`, `title`, formatted `fields`, complete labeled `actions`, and optional `artifact`. Support `appointment_list`, `service_selection`, `slot_selection`, `appointment_confirmation`, `appointment_recovery`, and `appointment_completed`.

- [ ] **Step 5: Implement `DeliveryOrchestrator`.** Combine task, response, workspace, confirmation, receipt, and speech metadata. Catch only TTS provider errors for `speech_audio.status`; never turn an execution result into a failed task because speech is unavailable.

- [ ] **Step 6: Run projection tests.**

Run: `python -m pytest middleware/tests/test_interaction_delivery.py -q`

Expected: PASS.

---

### Task 4: Route JSON and voice input through the shared Core

**Files:**
- Modify: `middleware/server.py`
- Create: `middleware/interaction_voice.py`
- Modify: `middleware/voice_transport.py`
- Modify: `frontend/mcp-client.js`
- Test: `middleware/tests/test_server.py`
- Test: `middleware/tests/test_voice_transport.py`
- Create: `middleware/tests/test_interaction_http.py`

**Interfaces:**
- Adds `POST /api/interactions` accepting an `EventEnvelope` and returning a unified interaction response.
- Makes `/api/voice/turn` use STT → `user_utterance` envelope → `InteractionCore` → `DeliveryOrchestrator` when the configured provider is the new Core voice adapter.
- Keeps the existing injected voice test provider contract intact.

- [ ] **Step 1: Write failing HTTP tests.** Post a normalized utterance envelope to `/api/interactions`; assert response contains `task`, `response`, `workspace`, and no legacy `assistant_message`/`task_state` fields. Add a voice adapter test proving the transcript becomes `event.content` and not a voice-specific event.

- [ ] **Step 2: Run the focused HTTP tests to verify they fail.**

Run: `python -m pytest middleware/tests/test_interaction_http.py middleware/tests/test_server.py middleware/tests/test_voice_transport.py -q`

Expected: FAIL because the new route and adapter are not wired.

- [ ] **Step 3: Add the Core to `MiddlewareApplication`.** Construct it with the existing registry, pipeline, sessions, and patient context. Add a delivery orchestrator and a Core-backed voice provider that uses existing STT/TTS adapters but passes only normalized `content` into the Core.

- [ ] **Step 4: Add `/api/interactions` and update known paths.** Validate the envelope, call the Core, deliver the canonical result, and map expected validation errors to `400`. Keep `/api/interactions/message` and `/api/interactions/action` only for current non-medical/diagnostic callers during this incremental migration; do not route medical events through those contracts.

- [ ] **Step 5: Update voice envelope metadata.** Keep transport details under `voice_turn` and delivery details under `speech_audio`; return the canonical interaction result under `result`. Browser fallback is handled later by frontend code, not by the Core.

- [ ] **Step 6: Update `MiddlewareClient`.** Add `sendInteraction(envelope)` and leave `sendVoiceTurn` as the audio transport method. Remove new medical calls to `sendMessage` and `sendAction`.

- [ ] **Step 7: Run HTTP, voice, and full middleware tests.**

Run: `python -m pytest middleware/tests/test_interaction_http.py middleware/tests/test_server.py middleware/tests/test_voice_transport.py tests/test_middleware_integration.py -q`

Expected: PASS, with legacy tests unchanged for not-yet-migrated flows.

---

### Task 5: Replace frontend medical parsing with canonical workspace rendering

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/mcp-client.js`
- Modify: `frontend/interaction-view.js`
- Modify: `frontend/voice-exceptions.js`
- Modify: `tests/test_frontend_static.py`
- Create: `tests/test_frontend_interaction_contract.py`

**Interfaces:**
- Consumes the unified interaction response from Task 4.
- Submits `workspace.actions[].event` unchanged through `sendInteraction`.
- Plays server audio when ready; when unavailable, passes `response.speech_text` to the existing browser speech controller.

- [ ] **Step 1: Write failing static contract tests.** Assert the frontend references `workspace.view`, `workspace.actions`, `response.display_text`, `response.speech_text`, `speech_audio.status`, and `sendInteraction`; assert it no longer constructs `search_slots`, `select_slot`, or confirmation events from parsed response data.

- [ ] **Step 2: Run focused frontend tests to verify they fail.**

Run: `python -m pytest tests/test_frontend_interaction_contract.py tests/test_frontend_static.py -q`

Expected: FAIL because the current renderer still reads legacy `task_state`, `current_step`, `data`, and `actions`.

- [ ] **Step 3: Implement one generic workspace renderer.** Render only the server-provided view, fields, labels, artifact, and actions. The click handler passes the complete event object unchanged. Keep the existing visual shell and receipt drawer, adapting receipt rendering to the canonical medical receipt shape.

- [ ] **Step 4: Update app delivery.** Show `response.display_text`; if `speech_audio.status` is `ready`, play the server URL; otherwise use `response.speech_text` with browser speech synthesis. Do not pass `source: voice` or a legacy message body for browser STT.

- [ ] **Step 5: Reduce `voice-exceptions.js` to delivery/error surface.** Remove business workflow inference and duplicated action construction; retain transport error rendering and canonical receipt opening.

- [ ] **Step 6: Run frontend tests.**

Run: `python -m pytest tests/test_frontend_interaction_contract.py tests/test_frontend_static.py -q`

Expected: PASS.

---

### Task 6: Verify the complete medical workflow and commit the implementation

**Files:**
- Test: `tests/test_full_stack_integration.py`
- Test: `tests/test_http_smoke.py`
- Modify: only files changed by Tasks 1–5

- [ ] **Step 1: Add an end-to-end medical contract test.** Exercise normalized utterance → service action → slot action → confirmation action → verified appointment creation. Assert the final result is `completed`, contains a canonical `receipt_id` from backend `receipt.reference`, and produces a printable receipt artifact without exposing raw backend data.

- [ ] **Step 2: Add failure-path assertions.** Cover slot unavailable and malformed backend receipt data. Assert `awaiting_input`, a deterministic recovery view/actions, and `receipt is None`.

- [ ] **Step 3: Run the complete verification suite.**

Run: `python -m pytest middleware/tests tests tests/medical tests/one_account tests/social_welfare MCP/tests -q`

Expected: PASS with zero failures. If unrelated dirty-worktree tests fail, report the exact failures separately and do not alter those changes.

- [ ] **Step 4: Run whitespace and diff-scope checks.**

Run: `git diff --check` and `git status --short`

Expected: no whitespace errors; only intended implementation files are modified in addition to the user's pre-existing dirty files.

- [ ] **Step 5: Commit only implementation files.**

```bash
git add middleware/interaction_contracts.py middleware/interaction_core.py middleware/interaction_delivery.py middleware/session.py middleware/server.py middleware/voice_services.py middleware/voice_transport.py frontend/app.js frontend/mcp-client.js frontend/interaction-view.js frontend/voice-exceptions.js middleware/tests/test_interaction_contracts.py middleware/tests/test_interaction_core.py middleware/tests/test_interaction_delivery.py middleware/tests/test_interaction_http.py tests/test_frontend_static.py tests/test_frontend_interaction_contract.py tests/test_full_stack_integration.py tests/test_http_smoke.py
git commit -m "feat: route medical workflow through voice-first interaction core"
```
