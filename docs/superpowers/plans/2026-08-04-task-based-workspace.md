# Task-Based Service Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 Ponte 服務工作區改為可收放的獨立任務卡片，讓查詢結果以 UI 摘要呈現，並保留未來由 LLM 文字／語音輸入繼續同一任務的接口。

**Architecture:** 前端在頁面 session 內保存 `TaskRecord[]`，以 native `<details>` 渲染每個任務；新文字／語音需求建立 task，UI action 更新目前 task。middleware 在新高階 message 開始時重設上一個 `SessionState` workflow 的 transient data，避免查詢 response 混入舊預約資料。既有 middleware HTTP contract、醫療 action payload、speech flow 和 mock backend contract 不變。

**Tech Stack:** 原生 HTML、CSS、ES modules、Python `unittest`、現有 middleware／mock backend；不新增 runtime 或 build dependency。

## Global Constraints

- Frontend remains zero build dependency and uses the existing native HTML/CSS/JavaScript stack.
- 不改變既有 `/api/interactions/message`、`/api/interactions/action`、醫療 mock backend 或 speech 行為。
- 新文字／語音需求目前建立 task；UI action 更新目前 task；`continueTask()` 預留未來 LLM confirmation routing。
- `TaskRecord` 必須保存 `localId`、可選 `backendTaskId`、標題、輸入 channel、狀態、response snapshot 和 expanded state。
- 終止狀態為 `completed`、`cancelled`、`failed` 或 `human_handoff`；終止任務自動收合，最新執行任務自動展開。
- 查詢資料以 `data.intent === "medical_query"` 優先渲染 `appointments`；預約流程依 `selected_slot`、`slots`、`services` 的順序渲染。
- 使用者介面不可顯示 API tool name、request ID、FHIR resource type、內部 ID、`LOC-*` 原值、容量、剩餘名額或 raw JSON。
- middleware state reset 只清理目前 workflow state，不刪除已建立的 mock appointment、durable task 或 receipt。
- 任務歷史只保留在目前頁面 session，不新增 browser storage。
- 保留大字、高對比、鍵盤 focus、ARIA、手機版單欄佈局、錯誤訊息、語音輸入、人工協助和重要操作確認。
- 每完成一個實作步驟後，更新本計畫的 checkbox 為 `[x]`，並在每個 task 的驗證命令成功後才進入下一 task。

---

### Task 1: Lock task workspace and state-reset regression contracts

**Files:**
- Modify: `tests/test_frontend_static.py`
- Modify: `middleware/tests/test_controller.py`
- Modify: `tests/test_middleware_integration.py`
- Test: source contracts and middleware response state

**Interfaces:**
- Consumes: current static frontend assets and `InteractionController` response shape.
- Produces: failing regression tests for `task-list`, `startTask`／`updateTask`／`continueTask`, same-session stale-state cleanup, and action-chain preservation.

- [x] **Step 1: Replace single-workspace HTML assertions with task-list assertions**

Update `FrontendStaticTests.test_index_has_required_landmarks_and_controls` so it requires `id="task-list"` and no longer requires static `task-steps`, `task-content`, or `action-list` roots. Keep the existing conversation, speech, input and focus landmark assertions.

Add a test with this exact contract:

```python
    def test_index_exposes_task_workspace_root(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn('id="task-list"', html)
        self.assertIn('aria-label="服務任務"', html)
        self.assertNotIn('id="task-content"', html)
```

- [x] **Step 2: Add frontend task lifecycle source contracts**

Add `test_view_supports_task_workspace_lifecycle` to `tests/test_frontend_static.py`:

```python
    def test_view_supports_task_workspace_lifecycle(self):
        source = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        for marker in (
            "TaskRecord",
            "startTask",
            "updateTask",
            "continueTask",
            "toggleTask",
            "task-card",
            "createElement(\"details\")",
            "medical_query",
            "appointments",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("taskRoot.replaceChildren()", source)
```

Add `test_app_routes_message_and_action_to_task_ids`:

```python
    def test_app_routes_message_and_action_to_task_ids(self):
        source = Path("frontend/app.js").read_text(encoding="utf-8")
        self.assertIn("startTask", source)
        self.assertIn("updateTask", source)
        self.assertIn("continueTask", source)
        self.assertIn("taskId", source)
```

- [x] **Step 3: Add the stale workflow state unit test**

Add this test to `middleware/tests/test_controller.py`:

```python
    def test_new_message_resets_previous_workflow_data(self):
        self.controller.handle_message(InteractionRequest("S-REUSE", "我想預約醫療服務"))
        self.controller.handle_action(InteractionActionRequest("S-REUSE", "search_slots", {
            "service_id": "SERVICE-US-001",
            "date_from": "2026-08-10",
            "date_to": "2026-08-14",
        }))
        self.controller.handle_action(InteractionActionRequest("S-REUSE", "select_slot", {
            "slot_id": "SLOT-US-20260812-1400",
        }))

        query = self.controller.handle_message(
            InteractionRequest("S-REUSE", "我想查詢自己的醫療預約")
        )

        self.assertEqual(query["data"]["appointments"], [])
        for stale_key in ("services", "slots", "selected_slot", "service_id", "slot_id"):
            self.assertNotIn(stale_key, query["data"])
        self.assertEqual([step["step_id"] for step in query["steps"]], ["load_appointments"])
        self.assertEqual([event["tool_name"] for event in query["tool_events"]], ["medical.get_my_appointments"])
```

- [x] **Step 4: Make the integration query reuse the booking session**

In `tests/test_middleware_integration.py::test_message_to_medical_tool_reaches_mock_backend`, change the post-booking query session from `S-QUERY-AFTER-BOOKING` to `S-1`, then assert:

```python
        self.assertNotIn("selected_slot", queried["data"])
        self.assertNotIn("slots", queried["data"])
        self.assertEqual(
            [event["tool_name"] for event in queried["tool_events"]],
            ["medical.get_my_appointments"],
        )
```

- [x] **Step 5: Run the focused contracts and confirm the red state**

Run:

```bash
python3 -m unittest \
  tests.test_frontend_static.FrontendStaticTests.test_index_exposes_task_workspace_root \
  tests.test_frontend_static.FrontendStaticTests.test_view_supports_task_workspace_lifecycle \
  tests.test_frontend_static.FrontendStaticTests.test_app_routes_message_and_action_to_task_ids \
  middleware.tests.test_controller.ControllerTests.test_new_message_resets_previous_workflow_data \
  -v
```

Expected: FAIL because the current UI has one static workspace root, no task lifecycle manager, and `SessionState` does not reset before a new message.

- [x] **Step 6: Commit the regression contracts**

```bash
git add tests/test_frontend_static.py middleware/tests/test_controller.py tests/test_middleware_integration.py
git commit -m "test: define task workspace lifecycle"
```

### Task 2: Reset middleware transient state between high-level tasks

**Files:**
- Modify: `middleware/session.py: SessionState`
- Modify: `middleware/controller.py: InteractionController.handle_message`
- Test: `middleware/tests/test_controller.py`, `tests/test_middleware_integration.py`

**Interfaces:**
- Consumes: Task 1 stale-state regression tests.
- Produces: `SessionState.reset_for_new_task()` and message handling that starts each new high-level task with clean workflow data while leaving `handle_action()` unchanged.

- [x] **Step 1: Implement the reset method on `SessionState`**

Add this method to `middleware/session.py`:

```python
    def reset_for_new_task(self) -> None:
        self.task_state = "idle"
        self.current_step = "welcome"
        self.data.clear()
        self.steps.clear()
        self.tool_events.clear()
        self.last_tool_call = None
        self.confirmation_record = None
        self.last_error = None
```

This only resets in-memory interaction state; it must not touch any mock backend repository.

- [x] **Step 2: Invoke the reset at the start of a new message**

In `InteractionController.handle_message`, replace the current `state.last_error = None` and pending diagnostic cleanup with:

```python
        state = self.sessions.get_or_create(request.session_id)
        state.reset_for_new_task()
```

Keep diagnostic parsing after the reset. Do not call this method from `handle_action`; action chains need the current services, slots, selected slot and confirmation record.

- [x] **Step 3: Run the middleware regression tests**

Run:

```bash
python3 -m unittest \
  middleware.tests.test_controller.ControllerTests \
  tests.test_middleware_integration.MiddlewareBackendIntegrationTests.test_message_to_medical_tool_reaches_mock_backend \
  -v
```

Expected: PASS, including the new same-session stale-state assertions.

- [x] **Step 4: Commit the middleware reset**

```bash
git add middleware/session.py middleware/controller.py middleware/tests/test_controller.py tests/test_middleware_integration.py
git commit -m "fix: reset middleware state for new tasks"
```

### Task 3: Build the frontend TaskRecord renderer

**Files:**
- Modify: `frontend/interaction-view.js`
- Test: `tests/test_frontend_static.py`

**Interfaces:**
- Consumes: middleware response `{task_state, current_step, steps, data, actions, error}` and Task 1 source contracts.
- Produces: `startTask({channel,value,taskId})`, `updateTask(taskId,response)`, `continueTask(taskId,input)`, `toggleTask(taskId)`, `failTask(taskId,error)` and an internal `TaskRecord[]` renderer.

- [x] **Step 1: Add task labels and terminal-state helpers**

Keep the existing friendly `TASK_STATE_LABELS`, `STEP_STATUS_LABELS`, `LOCATION_LABELS`, `STEP_LABELS`, and `STATUS_LABELS`. Add:

```js
const TERMINAL_TASK_STATES = new Set([
  "completed",
  "cancelled",
  "failed",
  "error",
  "human_handoff",
]);

function taskStatus(taskState) {
  if (taskState === "completed") return "completed";
  if (taskState === "cancelled") return "cancelled";
  if (taskState === "human_handoff") return "human_handoff";
  if (taskState === "failed" || taskState === "error") return "failed";
  return "running";
}
```

Use a local ID format `UI-TASK-${sequence}` when no task ID is provided. Never render this ID to the user.

- [x] **Step 2: Extract medical query rendering before booking rendering**

At the start of `renderMedicalData`, implement this branch before `selected_slot`, `slots`, or `services`:

```js
  if (data.intent === "medical_query") {
    if (appointments.length) {
      appointments.forEach((appointment, index) => {
        const card = createSummaryCard(
          serviceName(appointment.service, services) || `醫療預約 ${index + 1}`,
          [
            { label: "日期", value: dateOnly(appointment.start) },
            { label: "時間", value: timeRange(appointment) },
            { label: "服務地點", value: locationLabel(appointment.location) },
            { label: "狀態", value: STATUS_LABELS[appointment.status] || "已登記" },
          ],
        );
        if (card) container.append(card);
      });
    } else {
      container.append(createElement("div", "empty-workspace", "目前沒有已預約的醫療服務。"));
    }
    return;
  }
```

Then keep booking order as selected slot, slots, services, and leave the generic allowlist renderer unchanged except for task-card container ownership.

- [x] **Step 3: Add TaskRecord storage and lifecycle methods**

Inside `createInteractionView`, add this JSDoc marker and task storage:

```js
/** @typedef {Object} TaskRecord */
const tasks = [];
let taskSequence = 0;
let activeTaskId = null;

function startTask({ channel = "text", value = "", taskId = null } = {}) {
  const localId = taskId || `UI-TASK-${++taskSequence}`;
  tasks.forEach((task) => { task.expanded = false; });
  tasks.push({
    localId,
    backendTaskId: null,
    title: deriveTaskTitle(value),
    channel,
    status: "running",
    taskState: "querying",
    currentStep: "welcome",
    response: null,
    expanded: true,
  });
  activeTaskId = localId;
  renderTaskList();
  return localId;
}
```

Implement `updateTask(taskId, response)` to replace only that record’s response snapshot, task state, current step and status. Set `backendTaskId` from `response.task_id` when available. Open non-terminal tasks and close terminal tasks. Implement `continueTask(taskId, input)` to update the record’s channel/value, mark it running and open it without assuming the input came from a button. Implement `toggleTask(taskId)` by changing `expanded` and rerendering.

- [x] **Step 4: Render each task as an accessible native details card**

Implement `renderTaskList()` so every task creates:

```html
<details class="task-card" open>
  <summary class="task-card-summary">
    <span class="task-card-title">查詢醫療預約</span>
    <span class="task-card-state">已完成</span>
    <span class="task-card-teaser">已查到 2 個醫療預約</span>
  </summary>
  <div class="task-card-body">
    <div class="task-summary">...</div>
    <ol class="task-steps">...</ol>
    <div class="task-content">...</div>
    <div class="action-list">...</div>
  </div>
</details>
```

Use the existing `renderSteps`, `renderData`, and `renderActions` functions against elements created inside each card. Pass `(action, task.localId)` to `onAction`; completed cards must not render interactive actions. The task title and teaser may use friendly text, but must never include backend IDs.

- [x] **Step 5: Preserve view-level error behavior while marking the task failed**

Add `failTask(taskId, error)` that updates the record with `task_state: "failed"`, an error response, and a closed card. Keep `renderError(error)` for the global alert. `clearError()` remains unchanged.

Return the new methods from `createInteractionView`:

```js
return {
  appendUserMessage: (text) => appendMessage("user", text),
  startTask,
  updateTask,
  continueTask,
  toggleTask,
  failTask,
  renderHealth,
  renderError,
  clearError,
};
```

- [x] **Step 6: Run renderer-focused contracts and syntax**

Run:

```bash
python3 -m unittest \
  tests.test_frontend_static.FrontendStaticTests.test_view_module_exports_renderer \
  tests.test_frontend_static.FrontendStaticTests.test_view_uses_friendly_service_workspace_fields \
  tests.test_frontend_static.FrontendStaticTests.test_view_supports_task_workspace_lifecycle
```

Run the JavaScript syntax check separately because `node --check` is not a unittest target:

```bash
node --check frontend/interaction-view.js
```

Expected: PASS for the task lifecycle contracts and existing friendly-renderer contracts. The full `tests.test_frontend_static` suite runs after Task 4 updates the HTML and app wiring.

- [x] **Step 7: Commit the task renderer**

```bash
git add frontend/interaction-view.js tests/test_frontend_static.py
git commit -m "feat: render collapsible task workspace"
```

### Task 4: Wire message/action routing and semantic HTML

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Test: `tests/test_frontend_static.py`

**Interfaces:**
- Consumes: Task 3 view methods `startTask`, `updateTask`, `continueTask`, and `failTask`.
- Produces: message requests that create tasks, actions that continue active tasks, and a single `task-list` workspace root.

- [x] **Step 1: Replace the static task roots with one task-list root**

In `frontend/index.html`, replace the current `task-summary`, `task-steps`, `task-content`, and `action-list` elements with:

```html
<div id="task-list" class="task-list" aria-label="服務任務" aria-live="polite"></div>
```

Keep the workspace heading, visible-execution promise, health status, global error, human help and all conversation/input controls.

- [x] **Step 2: Pass task-list root to the interaction view**

In `frontend/app.js`, replace `stepsRoot`, `taskRoot`, `actionsRoot`, and `stateRoot` with:

```js
taskListRoot: byId("task-list"),
```

Keep `conversationRoot`, `healthRoot`, `errorRoot`, and `onAction`.

- [x] **Step 3: Start and update tasks for messages**

In `sendMessage`, after appending the user message and before the network request, add:

```js
const taskId = view.startTask({
  channel: source,
  value: trimmed,
});
```

Then update that task on success:

```js
const response = await client.sendMessage({ session_id: sessionId, message: trimmed, source });
view.updateTask(taskId, response);
speech.speak(response.assistant_message);
```

On error, call `view.failTask(taskId, error)` before `handleError(error)`.

- [x] **Step 4: Continue the active task for UI actions**

Change `handleAction(action, taskId = null)` to use the supplied task ID or the app’s `activeTaskId`. If neither exists (for example, the footer human-help action is clicked before any message), start a UI task first; otherwise call `continueTask`. Before `client.sendAction`, call:

```js
if (!taskId) {
  taskId = view.startTask({ channel: "ui", value: action });
} else {
  view.continueTask(taskId, {
    channel: "ui",
    value: action,
  });
}
```

Update the same task with `view.updateTask(taskId, response)`. On failure, call `view.failTask(taskId, error)` and preserve the global error alert. Do not change the outgoing action name or payload.

- [x] **Step 5: Keep future LLM continuation routing isolated**

Keep the current `sendMessage` behavior of starting a new task, but ensure the task ID is explicit at the view boundary. Add a comment-free, callable view method `continueTask` (already implemented in Task 3) so a later input router can call it without changing task-card rendering. Do not add a new backend endpoint or fake `task_id` field in this task.

- [x] **Step 6: Run static and syntax checks**

Run:

```bash
python3 -m unittest tests.test_frontend_static -v
node --check frontend/app.js
node --check frontend/interaction-view.js
```

Expected: PASS.

- [x] **Step 7: Commit the routing and markup**

```bash
git add frontend/app.js frontend/index.html tests/test_frontend_static.py
git commit -m "feat: route responses into task cards"
```

### Task 5: Style task history and update user-facing documentation

**Files:**
- Modify: `frontend/styles.css`
- Modify: `frontend/README.md`
- Modify: `README.md`
- Test: `tests/test_frontend_static.py`, `git diff --check`

**Interfaces:**
- Consumes: Task 3 card class names and Task 4 `task-list` markup.
- Produces: readable collapsible cards with preserved large controls, responsive behavior and documentation that describes task cards rather than raw tool events.

- [x] **Step 1: Add task-list/card styles**

Add styles for the new card hierarchy:

```css
.task-list {
  display: grid;
  gap: 12px;
}

.task-card {
  overflow: hidden;
  border: 1px solid #c9ddda;
  border-radius: 16px;
  background: #fbfdfc;
}

.task-card.is-current {
  border-color: #78aaa5;
  box-shadow: 0 6px 18px rgba(25, 85, 83, 0.08);
}

.task-card-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 12px;
  padding: 16px 18px;
  cursor: pointer;
  list-style: none;
}

.task-card-summary::-webkit-details-marker {
  display: none;
}

.task-card-title,
.task-card-state {
  font-weight: 800;
}

.task-card-state {
  color: var(--teal-700);
  font-size: 0.82rem;
}

.task-card-teaser {
  grid-column: 1 / -1;
  color: var(--muted);
  font-size: 0.82rem;
}

.task-card-body {
  display: grid;
  gap: 12px;
  padding: 0 18px 18px;
}
```

Reuse existing `.task-summary`, `.task-steps`, `.task-content`, `.summary-card`, `.action-list`, focus and mobile rules inside the card body. Add a mobile rule that changes `.task-card-summary` to one column below 640px.

- [x] **Step 2: Update the frontend README**

Replace the current workspace bullet with text explaining:

```text
Middleware response 會以獨立任務卡顯示；進行中的任務展開顯示 steps、服務資料和下一步操作，完成、取消或失敗的任務會收合但可重新展開。醫療查詢會顯示每筆預約的服務、日期、時間、地點和狀態；一般使用者不會看到 API 工具名稱、請求編號或原始 backend JSON。未來可讓文字／語音確認繼續同一任務。
```

Keep startup, speech behavior, action contract and zero-build instructions accurate.

- [x] **Step 3: Update the root README workflow description**

Change the medical query acceptance paragraph from “看到 tool event” to “看到完成的查詢任務卡和預約摘要”。Update the booking paragraph to mention that the active task shows visible steps and that completed tasks remain collapsed in the workspace. Add one architecture sentence under the frontend layer: “Frontend Task Workspace 管理目前頁面的任務卡歷史；Workflow／middleware 管理實際 task state。”

- [x] **Step 4: Run documentation and style contracts**

Run:

```bash
python3 -m unittest tests.test_frontend_static -v
git diff --check
rg -n "tool event|tool-event-card|task-list|Task Workspace" README.md frontend/README.md frontend/index.html frontend/styles.css docs/PonteArch.md
```

Expected: the user-facing READMEs describe task cards, the source contains no obsolete raw tool-event CSS or static workspace roots, and `git diff --check` is clean.

- [x] **Step 5: Commit styles and documentation**

```bash
git add frontend/styles.css frontend/README.md README.md tests/test_frontend_static.py
git commit -m "docs: describe task workspace UI"
```

### Task 6: Run complete verification and perform local UI smoke check

**Files:**
- Verify: `frontend/index.html`, `frontend/app.js`, `frontend/interaction-view.js`, `frontend/styles.css`
- Verify: `middleware/session.py`, `middleware/controller.py`
- Verify: `README.md`, `frontend/README.md`, `docs/PonteArch.md`

**Interfaces:**
- Consumes: completed tasks 1–5.
- Produces: fresh test, syntax, integration and visual evidence for the approved behavior.

- [x] **Step 1: Run all JavaScript syntax checks**

```bash
node --check frontend/app.js
node --check frontend/mcp-client.js
node --check frontend/interaction-view.js
node --check frontend/speech.js
```

Expected: all four commands exit 0.

- [x] **Step 2: Run all Python tests**

```bash
python3 -m unittest discover -v
python3 -m unittest discover -s MCP/tests -v
python3 -m unittest discover -s middleware/tests -v
python3 -m compileall -q MCP middleware mock_backends frontend scripts tests
```

Expected: every unittest command exits 0 and compileall emits no error.

- [x] **Step 3: Inspect final diff and forbidden user-facing identifiers**

```bash
git diff --check
git status --short
rg -n "測試模式|mcp medical\.list_departments|tool-event-card|id=\"task-content\"|id=\"task-steps\"|id=\"action-list\"" frontend/index.html frontend/interaction-view.js frontend/styles.css frontend/README.md
rg -n "tool event|Task Workspace|任務卡" README.md frontend/README.md
```

Expected: no obsolete developer copy, raw tool-event CSS, or single-workspace static roots in frontend assets. The root README may retain its explicitly documented developer MCP diagnostic commands, but its user-facing workflow description must use task cards. Internal identifiers may remain only as input keys or mapping keys in renderer/controller code and must not be inserted into visible text.

- [x] **Step 4: Run a local full-stack medical workflow smoke check**

Start the stack with:

```bash
python3 scripts/run_stack.py --data-dir /tmp/ponte-task-workspace-smoke
```

In the browser:

1. Enter `我想查詢自己的醫療預約`; confirm one completed task card expands with appointment service/date/time/location/status.
2. Enter `我想預約醫療服務`; confirm a second active task card appears, the query card collapses, and the active card shows steps and service choices.
3. Select a service and date range; confirm the same card shows available slots.
4. Select a slot and confirm; confirm the same card reaches completed/submitted state and collapses.
5. Expand the query and booking cards again; confirm summaries remain readable and no tool name, request ID, `LOC-*`, FHIR type or raw JSON appears.
6. Repeat the query in the same session; confirm it creates a new query card with only appointment results and does not show the previous selected slot.
7. Resize to a mobile-width viewport; confirm task summaries, controls and details remain keyboard-operable. The in-app browser could not initialize in this WSL workspace because of `sandboxCwd`; the equivalent localhost HTTP workflow plus a DOM task-renderer harness passed, while visual browser inspection remains unavailable in this environment.

- [x] **Step 5: Record verification evidence and finish the implementation handoff**

Capture the exact unittest counts, syntax-check exit status, smoke-check observations and final `git status`. Only after these are fresh and clean, update this plan’s checkboxes to `[x]` and report the changed files and verification commands.
