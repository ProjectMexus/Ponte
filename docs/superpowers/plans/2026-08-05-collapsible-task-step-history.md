# Collapsible Task Step History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make each processed task step collapse by default while preserving independent historical step details that users can reopen, including repeated steps created by retries.

**Architecture:** Keep the existing middleware response contract. Extend the frontend TaskRecord with stepHistory, keyed by step_id plus occurrence, and capture a JSON-safe snapshot the first time each step occurrence appears. Render each history item as a nested native details element inside the task card; preserve its expanded state across task list rerenders and auto-collapse only when an active step becomes processed.

**Tech Stack:** Browser ES modules, native HTML details, existing frontend user-safe data renderers, Python unittest static contract tests, Node syntax checks.

## Global Constraints

- Do not change middleware, mock backend, or response data formats.
- Do not expose raw JSON, tool names, request IDs, or internal IDs in the step detail UI.
- Preserve the existing outer task-card expand/collapse behavior, ARIA labels, keyboard operation, large controls, focus-visible styles, and mobile layout.
- Completed and historical failed steps default to collapsed; the current step and current recovery step default to expanded.
- Repeated occurrences of the same step_id remain separate history entries.
- Do not add browser storage or a durable step-history API.

---

### Task 1: Extend frontend static contracts for step history

**Files:**
- Modify: tests/test_frontend_static.py in the frontend view contract tests
- Test: existing tests/test_frontend_static.py

**Interfaces:**
- Consumes: the existing source-string contract style used by FrontendStaticTests.
- Produces: explicit checks that the renderer has independent step history, snapshots, native step details, preserved expanded state, and step-specific safe data projection.

- [x] Step 1: Add a failing contract test for step-history rendering markers

Add this method to FrontendStaticTests:

~~~python
    def test_view_supports_collapsible_step_history(self):
        source = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        for marker in (
            "stepHistory",
            "updateStepHistory",
            "stepHistoryKey",
            "snapshotResponse",
            "stepDataForSnapshot",
            'createElement("details", "task-step-details")',
            "task-step-summary",
            "task-step-detail",
            "entry.expanded",
        ):
            self.assertIn(marker, source)
        self.assertIn("task.stepHistory = updateStepHistory", source)
        self.assertNotIn("renderSteps(steps, response.steps", source)
~~~

- [x] Step 2: Run the focused test and verify it fails

Run:

~~~powershell
python -m unittest tests.test_frontend_static.FrontendStaticTests.test_view_supports_collapsible_step_history -v
~~~

Expected: FAIL because the current renderer has no stepHistory, snapshot helpers, or nested step details.

- [x] Step 3: Keep the test as the regression contract

Do not weaken the markers after implementation. Later tasks must make this exact test pass while retaining the existing task lifecycle markers.

### Task 2: Add step-history normalization and snapshot helpers

**Files:**
- Modify: frontend/interaction-view.js near renderSteps and the task view helpers

**Interfaces:**
- Consumes: response.steps, response.current_step, response.task_state, and existing safe renderers.
- Produces:
  - stepHistoryKey(stepId, occurrence) returns a stable string key.
  - snapshotResponse(response, stepId) returns { assistant_message, task_state, data, error, recovery } with step-specific JSON-safe data.
  - updateStepHistory(previousHistory, response) returns an ordered array of history entries with { key, step, status, snapshot, expanded, active }.

- [x] Step 1: Implement JSON-safe cloning and status helpers

Add these helpers before the step renderer:

~~~js
const TERMINAL_STEP_STATUSES = new Set(["completed", "failed"]);

function cloneJsonValue(value) {
  if (value === undefined || value === null) return value;
  return JSON.parse(JSON.stringify(value));
}

function stepStatus(step, currentStep) {
  const rawStatus = step?.status || (
    step?.ok === false ? "failed" : step?.ok === true ? "completed" : "pending"
  );
  return rawStatus === "pending" && step?.step_id === currentStep ? "current" : rawStatus;
}

function stepHistoryKey(stepId, occurrence) {
  return String(stepId || "service_step") + ":" + occurrence;
}

function stepIsActive(status, step, response) {
  return status === "current"
    || (
      status === "failed"
      && step?.step_id === response?.current_step
      && response?.task_state === "awaiting_user_input"
    );
}
~~~

- [x] Step 2: Implement step-specific safe data selection

Add stepDataForSnapshot(stepId, data) so historical details do not reuse unrelated later data:

~~~js
function stepDataForSnapshot(stepId, data) {
  const source = data && typeof data === "object" ? data : {};
  const pick = (...keys) => Object.fromEntries(
    keys.filter((key) => Object.prototype.hasOwnProperty.call(source, key))
      .map((key) => [key, source[key]])
  );
  if (stepId === "load_appointments") return pick("intent", "appointments");
  if (stepId === "load_services" || stepId === "select_service") return pick("services");
  if (stepId === "search_slots") return pick("services", "slots", "service_id", "date_from", "date_to");
  if (["select_slot", "confirm_appointment", "create_appointment", "get_task_status"].includes(stepId)) {
    return pick("services", "selected_slot", "service_id", "slot_id", "task_status");
  }
  return source;
}
~~~

- [x] Step 3: Implement response snapshots and history reconciliation

Add these functions:

~~~js
function snapshotResponse(response, stepId) {
  return {
    assistant_message: typeof response?.assistant_message === "string" ? response.assistant_message : "",
    task_state: response?.task_state,
    data: cloneJsonValue(stepDataForSnapshot(stepId, response?.data)),
    error: cloneJsonValue(response?.error),
    recovery: cloneJsonValue(response?.recovery),
  };
}

function updateStepHistory(previousHistory, response) {
  const previousByKey = new Map((previousHistory || []).map((entry) => [entry.key, entry]));
  const occurrences = new Map();
  const steps = Array.isArray(response?.steps) ? response.steps : [];

  return steps.map((step) => {
    const stepId = step?.step_id || "service_step";
    const occurrence = (occurrences.get(stepId) || 0) + 1;
    occurrences.set(stepId, occurrence);
    const key = stepHistoryKey(stepId, occurrence);
    const status = stepStatus(step, response?.current_step);
    const active = stepIsActive(status, step, response);
    const previous = previousByKey.get(key);
    let expanded = previous ? previous.expanded : active;
    if (previous?.active && !active) expanded = false;
    if (previous && !previous.active && active && previous.status !== status) expanded = true;
    return {
      key,
      step: cloneJsonValue(step),
      status,
      snapshot: previous?.snapshot || snapshotResponse(response, stepId),
      expanded: Boolean(expanded),
      active,
    };
  });
}
~~~

- [x] Step 4: Run the focused contract test

Run:

~~~powershell
python -m unittest tests.test_frontend_static.FrontendStaticTests.test_view_supports_collapsible_step_history -v
~~~

Expected: FAIL until the task record and renderer consume the helpers in Task 3; this confirms the helper markers are present and identifies the remaining integration marker.

### Task 3: Render each step as an independently reopenable detail

**Files:**
- Modify: frontend/interaction-view.js replacing the current flat renderSteps implementation and integrating the task record lifecycle

**Interfaces:**
- Consumes: updateStepHistory, existing renderData, renderRecovery, STEP_LABELS, and STEP_STATUS_LABELS.
- Produces: nested details elements whose toggle event updates the matching history entry without changing other entries.

- [x] Step 1: Replace flat step rows with detail rows

Implement renderStepSnapshot(container, entry) with this behavior:

~~~js
function renderStepSnapshot(container, entry) {
  const snapshot = entry.snapshot || {};
  if (snapshot.assistant_message) {
    container.append(createElement("p", "task-step-message", snapshot.assistant_message));
  }
  const data = createElement("div", "task-step-content");
  renderData(data, snapshot.data, snapshot);
  container.append(data);
  if (snapshot.error?.message) {
    container.append(createElement("div", "alert alert-error", snapshot.error.message));
  }
  if (snapshot.recovery) {
    const recovery = createElement("div", "recovery-content");
    renderRecovery(recovery, snapshot.recovery);
    container.append(recovery);
  }
}
~~~

Then implement renderSteps(container, stepHistory) by creating a li with class task-step is-status for each entry, containing:

~~~js
const details = createElement("details", "task-step-details");
details.open = Boolean(entry.expanded);
details.addEventListener("toggle", () => {
  entry.expanded = details.open;
});
const summary = createElement("summary", "task-step-summary");
summary.append(
  createElement("span", "task-step-marker", entry.status === "completed" ? "✓" : String(index + 1)),
  createElement("span", "task-step-label", STEP_LABELS[entry.step.step_id] || "服務步驟"),
  createElement("span", "task-step-status", STEP_STATUS_LABELS[entry.status] || "尚未開始"),
);
const detail = createElement("div", "task-step-detail");
renderStepSnapshot(detail, entry);
details.append(summary, detail);
item.append(details);
~~~

Attach aria-label="服務流程" to the outer ordered list as before. The step summary must not expose step_id; it only uses STEP_LABELS and the existing fallback.

- [x] Step 2: Integrate history into task lifecycle

Add stepHistory: [] when startTask creates a TaskRecord. In updateTask, immediately after normalizing nextResponse, assign:

~~~js
task.stepHistory = updateStepHistory(task.stepHistory, nextResponse);
~~~

In renderTaskList, call:

~~~js
renderSteps(steps, task.stepHistory);
~~~

Do not render response.steps directly. Keep the task-level details and task.expanded logic unchanged.

- [x] Step 3: Run the focused contract test

Run:

~~~powershell
python -m unittest tests.test_frontend_static.FrontendStaticTests.test_view_supports_collapsible_step_history -v
~~~

Expected: PASS.

### Task 4: Add responsive styles for nested step details

**Files:**
- Modify: frontend/styles.css around the existing task-step rules and mobile task-card rules

**Interfaces:**
- Consumes: task-step, task-step-details, task-step-summary, task-step-detail, task-step-message, and existing status classes.
- Produces: readable, keyboard-visible, mobile-safe nested details with the same visual status colors.

- [x] Step 1: Replace the flat grid row styling

Update the existing task-step rule to use display: block, remove its fixed min-height, and keep its border, radius, and status colors. Add:

~~~css
.task-step-details > .task-step-summary {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto 24px;
  align-items: center;
  gap: 10px;
  min-height: 52px;
  padding: 8px 10px;
  cursor: pointer;
  list-style: none;
}

.task-step-summary::-webkit-details-marker {
  display: none;
}

.task-step-summary::after {
  content: "＋";
  color: var(--teal-700);
  font-weight: 800;
  text-align: center;
}

.task-step-details[open] > .task-step-summary::after {
  content: "－";
}

.task-step-detail {
  display: grid;
  gap: 12px;
  padding: 0 10px 14px 54px;
}

.task-step-message {
  margin: 0;
  color: var(--muted);
}
~~~

Keep task-step-marker, task-step-label, task-step-status, and task-step.is-* color rules so completed markers remain green and failures remain red.

- [x] Step 2: Make the mobile summary fit narrow screens

Inside the existing max-width 640px media block, add:

~~~css
.task-step-details > .task-step-summary {
  grid-template-columns: 30px minmax(0, 1fr) auto 22px;
  gap: 8px;
}

.task-step-detail {
  padding-left: 48px;
}
~~~

- [x] Step 3: Run the frontend static tests

Run:

~~~powershell
python -m unittest tests.test_frontend_static -v
~~~

Expected: PASS, including the existing large-control, focus, desktop scroll, and mobile layout contracts.

### Task 5: Update frontend documentation and perform full verification

**Files:**
- Modify: frontend/README.md in the user-visible interaction description and verification notes
- Test: tests/test_frontend_static.py, Node checks for all frontend modules

**Interfaces:**
- Consumes: the completed frontend behavior from Tasks 2–4.
- Produces: user-facing documentation that explains expandable historical steps and fresh verification evidence.

- [x] Step 1: Document the new step behavior

Update the existing task workspace bullet in frontend/README.md to say that completed steps collapse automatically, current/recovery steps stay open, and each retry occurrence can be reopened to inspect its user-safe historical summary. Keep the existing statements about task-card collapse, recovery actions, and hiding internal backend details.

- [x] Step 2: Run JavaScript syntax checks

Run:

~~~powershell
node --check frontend/app.js
node --check frontend/mcp-client.js
node --check frontend/interaction-view.js
node --check frontend/speech.js
~~~

Expected: all commands exit with code 0 and produce no syntax errors.

- [x] Step 3: Run the full frontend static test suite

Run:

~~~powershell
python -m unittest tests.test_frontend_static -v
~~~

Expected: every frontend static test passes.

- [x] Step 4: Inspect the final diff and working tree

Run:

~~~powershell
git diff --check
git status --short
git diff -- frontend/interaction-view.js frontend/styles.css frontend/README.md tests/test_frontend_static.py
~~~

Verify the diff is limited to the requested frontend behavior, the design and plan documents, and the associated tests; verify no raw technical fields were added to user-visible rendering.

- [ ] Step 5: Commit the implementation

After all checks pass, stage the implementation files and commit:

~~~powershell
git add -- frontend/interaction-view.js frontend/styles.css frontend/README.md tests/test_frontend_static.py
git commit -m "feat: collapse processed task steps"
~~~
