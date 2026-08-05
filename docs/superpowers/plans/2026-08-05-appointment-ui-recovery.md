# Appointment UI Recovery Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicate appointment summaries and recovery text, preserve action history inside task steps, and replace hard-coded alternative-service recovery with a dynamic service/department picker.

**Architecture:** Keep the existing frontend task workspace and middleware response contract. Add one allowlisted `select_service` middleware action that refreshes the service catalogue and returns to the existing `selecting_service` UI. Make the latest recovery/terminal step snapshot the single visible source for its processed content, while task-level controls remain the single interactive action surface.

**Tech Stack:** Vanilla browser JavaScript modules, CSS, Python 3.13 standard library, existing middleware controller/task manager, `unittest`, static frontend contract tests, mock medical pipeline.

## Global Constraints

- Preserve the outer task card and keep the final `完成預約` step expanded when a completed task is opened.
- A `DUPLICATE_BOOKING` recovery must expose `select_service` labelled `重新選擇其他服務／科室`, plus the existing `cancel` and `human_help` choices; it must not embed a fixed service ID.
- `select_service` must refresh `medical.list_appointment_services`, clear stale appointment-selection fields, and reuse the existing service/date/slot/confirmation flow.
- Show each processed summary, conflict explanation, error, and recovery explanation once; action buttons appear only once and remain usable at task level.
- Historical step details must retain safe action labels/kinds and the user-selected action without rendering payload IDs or raw backend data.
- Keep the current `search_slots`, `select_slot`, `confirm`, `cancel`, and `human_help` payload contracts compatible.
- Do not add dependencies, browser storage, permanent task-history APIs, or changes to mock-backend appointment data.
- Preserve unrelated worktree changes, including `docs/superpowers/plans/2026-08-05-cantonese-auto-speech.md` if it remains untracked.

---

### Task 1: Add regression tests for generic recovery and UI history contracts

**Files:**
- Modify: `middleware/tests/test_recovery.py`
- Modify: `middleware/tests/test_controller.py`
- Modify: `tests/test_frontend_static.py`

**Interfaces:**
- Consumes: current `build_recovery_plan`, `InteractionController.handle_action`, and static frontend source checks.
- Produces: failing tests that define the `select_service` action, service refresh behavior, action-history snapshot markers, and final-step expansion behavior.

- [x] **Step 1: Change the recovery policy test to require a generic service picker**

In `middleware/tests/test_recovery.py`, change the duplicate-booking expectations so the plan contains `select_service`, `cancel`, and `human_help`, contains no `search_slots`, and has no `service_id` in the picker payload:

```python
    def test_duplicate_booking_returns_generic_service_picker(self):
        plan = build_recovery_plan(
            error={"code": "DUPLICATE_BOOKING"},
            step_id="create_appointment",
            workflow="medical_booking",
            data={
                "service_id": "SERVICE-PT-001",
                "date_from": "2026-08-05",
                "date_to": "2026-08-19",
            },
            result_data=None,
            retryable=False,
        )

        self.assertEqual(
            {option.action for option in plan.options},
            {"select_service", "cancel", "human_help"},
        )
        picker = next(option for option in plan.options if option.action == "select_service")
        self.assertEqual(picker.label, "重新選擇其他服務／科室")
        self.assertEqual(dict(picker.payload), {})
```

Replace the existing service-specific duplicate-booking test with a test that passes three services and asserts that only one generic picker is emitted, regardless of which service conflicted:

```python
    def test_duplicate_booking_does_not_choose_a_fixed_alternative_service(self):
        plan = build_recovery_plan(
            error={"code": "DUPLICATE_BOOKING"},
            step_id="create_appointment",
            workflow="medical_booking",
            data={
                "service_id": "SERVICE-PT-001",
                "date_from": "2026-08-05",
                "date_to": "2026-08-19",
                "services": [
                    {"id": "SERVICE-US-001", "name": "腹部超聲波檢查"},
                    {"id": "SERVICE-PT-001", "name": "物理治療"},
                    {"id": "SERVICE-CARDIO-001", "name": "心臟科門診"},
                ],
            },
            result_data=None,
            retryable=False,
        )

        self.assertEqual(
            [option.action for option in plan.options],
            ["select_service", "cancel", "human_help"],
        )
        self.assertNotIn("service_id", plan.options[0].payload)
```

- [x] **Step 2: Add a controller regression for refresh-and-return-to-service-selection**

In `middleware/tests/test_controller.py`, add this test using `AlternativeServiceDuplicateBookingPipeline`:

```python
    def test_duplicate_booking_reopens_dynamic_service_picker(self):
        pipeline = AlternativeServiceDuplicateBookingPipeline()
        controller = InteractionController(
            pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        controller.handle_message(InteractionRequest("S-DYNAMIC", "我想預約醫療服務"))
        controller.handle_action(InteractionActionRequest("S-DYNAMIC", "search_slots", {
            "service_id": "SERVICE-PT-001",
            "date_from": "2026-08-05",
            "date_to": "2026-08-19",
        }))
        controller.handle_action(InteractionActionRequest("S-DYNAMIC", "select_slot", {
            "slot_id": "SLOT-PT-20260813-1000",
        }))
        failed = controller.handle_action(InteractionActionRequest("S-DYNAMIC", "confirm", {}))

        self.assertEqual(
            {action["kind"] for action in failed["actions"]},
            {"select_service", "cancel", "human_help"},
        )
        self.assertEqual(
            next(action for action in failed["actions"] if action["kind"] == "select_service")["payload"],
            {},
        )

        reopened = controller.handle_action(
            InteractionActionRequest("S-DYNAMIC", "select_service", {})
        )

        self.assertEqual(reopened["task_state"], "selecting_service")
        self.assertEqual(reopened["current_step"], "select_service")
        self.assertEqual(
            {item["id"] for item in reopened["data"]["services"]},
            {"SERVICE-PT-001", "SERVICE-US-001"},
        )
        self.assertEqual(reopened["actions"], [{"action": "cancel", "kind": "cancel", "label": "取消這次預約", "payload": {}}])
        service_calls = [call for call in pipeline.calls if call.name == "medical.list_appointment_services"]
        self.assertGreaterEqual(len(service_calls), 2)
```

- [x] **Step 3: Add static frontend regression markers before implementation**

In `tests/test_frontend_static.py`, extend the view contract test with exact markers for the new behavior:

```python
        for marker in (
            "selected_action",
            "renderActionHistory",
            "latestStepOwnsResponseContent",
            "重新選擇其他服務／科室",
            "entry.step_id === \"get_task_status\"",
        ):
            self.assertIn(marker, source)
```

Also assert that `renderActions` filters the service-selection placeholder before rendering the recovery cancel action:

```python
        self.assertIn('actionKind(action) !== "search_slots"', source)
```

- [x] **Step 4: Run the new focused tests and verify they fail for the missing behavior**

Run:

```powershell
python -m unittest middleware.tests.test_recovery middleware.tests.test_controller tests.test_frontend_static -v
```

Expected: FAIL because recovery still returns per-service `search_slots`, `select_service` is not an allowed controller action, and the frontend does not yet contain action-history/deduplication markers.

- [x] **Step 5: Commit the regression tests**

```powershell
git add middleware/tests/test_recovery.py middleware/tests/test_controller.py tests/test_frontend_static.py
git commit -m "test: cover appointment recovery UI contracts"
```

### Task 2: Implement the generic service recovery action in middleware

**Files:**
- Modify: `middleware/task_manager/recovery.py`
- Modify: `middleware/controller.py`
- Test: `middleware/tests/test_recovery.py`, `middleware/tests/test_controller.py`

**Interfaces:**
- Consumes: `RecoveryOption`, `build_response`, `_run_tool`, and the existing `medical.list_appointment_services` tool call.
- Produces: allowlisted `select_service` action; a response in `selecting_service` with refreshed `data.services` and a `cancel` action.

- [x] **Step 1: Replace per-service conflict options with the generic recovery option**

In `_booking_conflict_plan`, return the following option sequence and remove the `_other_service_search_options` call/function:

```python
    return RecoveryPlan(
        category="booking_conflict",
        reason_code="DUPLICATE_BOOKING",
        explanation="你已有同一時間的有效預約，這個時段不能再預約；可以重新查找其他可預約時段，或選擇其他協助方式。",
        options=(
            RecoveryOption("select_service", "重新選擇其他服務／科室", {}),
            RecoveryOption("cancel", "取消這次預約", {}),
            RecoveryOption("human_help", "轉接人工協助", {}),
        ),
    )
```

Keep `_same_service_search_option` and `_alternative_options` unchanged because they serve `SLOT_NOT_AVAILABLE` and no-slot recovery, not duplicate-booking recovery.

- [x] **Step 2: Add and route the `select_service` controller action**

Add `"select_service"` to `_ACTION_NAMES`, route it before `search_slots`, and add this method:

```python
    def _select_service(self, state: SessionState) -> dict[str, Any]:
        for key in (
            "service_id",
            "date_from",
            "date_to",
            "slots",
            "slot_id",
            "selected_slot",
            "task_id",
            "task_status",
        ):
            state.data.pop(key, None)
        state.confirmation_record = None

        manager = self._task_manager(state)
        manager.transition("querying", "load_services")
        services_result = self._run_tool(
            state,
            "medical.list_appointment_services",
            "load_services",
            {},
        )
        services = self._result_data(state, services_result, "load_services")
        if services is None:
            return build_response(state, "暫時無法載入可預約服務，請稍後再試。", [])

        state.data["services"] = services
        manager.transition("selecting_service", "select_service")
        return build_response(
            state,
            "請重新選擇你想預約的服務或科室。",
            [{"action": "cancel", "label": "取消這次預約"}],
        )
```

Route it with:

```python
        if action == "select_service":
            return self._select_service(state)
```

- [x] **Step 3: Run the focused middleware tests**

Run:

```powershell
python -m unittest middleware.tests.test_recovery middleware.tests.test_controller -v
```

Expected: PASS, including the generic recovery plan, refreshed service list, stale-field clearing, and the existing slot/confirmation tests.

- [x] **Step 4: Commit the middleware unit**

```powershell
git add middleware/task_manager/recovery.py middleware/controller.py middleware/tests/test_recovery.py middleware/tests/test_controller.py
git commit -m "fix: reopen dynamic medical service selection after conflict"
```

### Task 3: Deduplicate task content and preserve action history in the frontend

**Files:**
- Modify: `frontend/interaction-view.js`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend_static.py`

**Interfaces:**
- Consumes: response `steps`, `actions`, `recovery`, `data`, and the action object passed through `continueTask`.
- Produces: safe step snapshots with `actions` and `selected_action`, one visible processed-content source, read-only action history, and a dynamic service selector with cancel.

- [x] **Step 1: Add safe action snapshot helpers and attach the clicked action to the resulting step**

Keep `actionKind` as the shared action-kind reader and add a helper that stores only a display-safe kind/label:

```javascript
function snapshotAction(action) {
  const kind = actionKind(action);
  const label = typeof action?.label === "string" && action.label.trim()
    ? action.label.trim()
    : kind;
  return kind && label ? { kind, label } : null;
}
```

Extend `snapshotResponse(response, stepId, selectedAction = null)` to include:

```javascript
actions: Array.isArray(response?.actions)
  ? response.actions.map(snapshotAction).filter(Boolean)
  : [],
selected_action: selectedAction ? snapshotAction(selectedAction) : null,
```

Update `updateStepHistory(previousHistory, response, selectedAction = null)` so the new selected action is assigned only to the newly introduced step that caused the response. Use this exact target mapping: `select_service` → `load_services`, `search_slots` → `search_slots`, `select_slot` → `select_slot`, `confirm` → the newest `create_appointment` step or, if absent, the newest `get_task_status` step; use the newest step for `retry`, `cancel`, and `human_help`. Preserve an existing snapshot unchanged for an existing `stepHistory` key.

Initialize `pendingAction: null` in `startTask`. In `continueTask`, set `task.pendingAction = snapshotAction(input.value)` when the value is an action object. In `updateTask`, call `updateStepHistory(task.stepHistory, nextResponse, task.pendingAction)` and then clear `task.pendingAction` after the snapshot has been captured.

- [x] **Step 2: Make the final completed step and current recovery step the visible historical content source**

Update `stepIsActive` so a latest `select_slot` step with `response.task_state === "awaiting_confirmation"` is active. In `updateStepHistory`, initialize a new entry as expanded when it is active or when it is the final `get_task_status` entry of a completed response; preserve a user-toggled value on later renders.

Add the exact helper used by task rendering:

```javascript
function latestStepOwnsResponseContent(task) {
  const response = task.response || {};
  const historyStates = new Set([
    "completed",
    "cancelled",
    "failed",
    "human_handoff",
    "awaiting_user_input",
    "awaiting_confirmation",
  ]);
  if (!historyStates.has(response.task_state)) return false;
  const snapshot = task.stepHistory?.at(-1)?.snapshot;
  if (!snapshot) return false;
  return Boolean(
    (snapshot.data && Object.keys(snapshot.data).length)
    || snapshot.error
    || snapshot.recovery,
  );
}
```

In `renderTaskList`, compute `const historyOwnsContent = latestStepOwnsResponseContent(task)` after `renderSteps`. Render `renderData`, `response.error`, and `response.recovery` only when `historyOwnsContent` is false. Always keep the task-level `renderActions` call for non-terminal responses so recovery buttons remain usable exactly once.

- [x] **Step 3: Deduplicate the recovery explanation and render read-only historical actions**

Change `renderRecovery` to accept `{ showExplanation = true }` and append the explanation paragraph only when `showExplanation` is true. In `renderStepSnapshot`, append the snapshot assistant message, then call `renderRecovery` with `showExplanation` false when the two strings are equal.

Add `renderActionHistory(container, snapshot)` that renders:

- a `section` with class `action-history` when either `snapshot.actions` or `snapshot.selected_action` exists;
- a `p` with class `action-history-selected` reading `你選擇了：${snapshot.selected_action.label}` when selected;
- a list with class `action-history-list` containing each safe action label under `當時可選：`;
- no `<button>` elements and no action payload values.

Call `renderActionHistory` at the end of `renderStepSnapshot`.

- [x] **Step 4: Render the dynamic service picker’s cancel action without duplicating the placeholder**

In the `selectingService` branch of `renderActions`, after the service-choice list is appended, render only response actions that are not the service-list placeholder:

```javascript
    renderGenericActions(
      container,
      (response?.actions || []).filter((action) => actionKind(action) !== "search_slots"),
      onAction,
    );
```

This keeps the existing dynamically generated service buttons and adds the middleware-provided cancel button under them.

- [x] **Step 5: Add minimal styles for read-only action history**

Append styles to `frontend/styles.css` for `.action-history`, `.action-history-label`, `.action-history-list`, and `.action-history-selected`, using the existing muted text, border, rounded-card, and teal palette. The history list must not look like an enabled action-button group, and existing 56px interactive controls must remain unchanged.

- [x] **Step 6: Run frontend syntax and static contract checks**

Run:

```powershell
node --check frontend/app.js
node --check frontend/interaction-view.js
node --check frontend/mcp-client.js
node --check frontend/speech.js
python -m unittest tests.test_frontend_static -v
```

Expected: PASS with no JavaScript syntax errors, one dynamic service cancel path, action-history markers, and deduplication markers present.

- [x] **Step 7: Commit the frontend unit**

```powershell
git add frontend/interaction-view.js frontend/styles.css tests/test_frontend_static.py
git commit -m "fix: deduplicate appointment task history content"
```

### Task 4: Run integration verification and hand off the branch

**Files:**
- Inspect: `git diff`, `git status`, all modified files
- Modify: none unless a verification failure identifies a required correction

**Interfaces:**
- Consumes: completed middleware and frontend behavior from Tasks 2–3.
- Produces: verified branch state with no unrelated files staged or modified.

- [x] **Step 1: Run all focused regression suites together**

```powershell
python -m unittest middleware.tests.test_recovery middleware.tests.test_controller tests.test_frontend_static -v
```

Expected: PASS.

- [x] **Step 2: Run the complete repository test suites**

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s MCP/tests -v
python -m unittest discover -s middleware/tests -v
python -m compileall -q MCP middleware mock_backends frontend scripts tests
```

Expected: all relevant tests pass; any pre-existing environment-only failure must be identified by its exact test name and not hidden.

- [x] **Step 3: Verify the final diff and worktree scope**

```powershell
git diff --check
git diff dev...HEAD --stat
git status --short
```

Confirm that the branch contains only the approved design, implementation, and tests. Leave `docs/superpowers/plans/2026-08-05-cantonese-auto-speech.md` untouched if it remains an unrelated untracked file.

- [x] **Step 4: Report the branch, commits, tests, and any unrelated preserved worktree state**

Include the branch name `codex/fix-appointment-ui-recovery`, the implementation commit IDs, exact verification commands, and any pre-existing unrelated test/environment failures.
