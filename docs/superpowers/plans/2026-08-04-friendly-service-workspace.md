# Friendly Service Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 Ponte 服務工作區由後端原始資料攤開，改成只顯示服務、日期／時間、地點、進度和下一步操作的用戶版摘要介面。

**Architecture:** 保持 middleware、MCP registry、mock backend 和既有 action contract 不變，在 frontend/interaction-view.js 增加業務語意渲染。醫療流程使用服務／時段／預約摘要；其他流程使用已知可讀欄位白名單，所有內部 ID、工具事件和請求編號在展示層過濾掉。

**Tech Stack:** 原生 HTML、CSS、ES modules、Python unittest 靜態 contract tests；不新增 build dependency 或 runtime dependency。

## Global Constraints

- Frontend remains zero build dependency and uses the existing native HTML/CSS/JavaScript stack.
- Do not change the middleware HTTP contract, conversation rendering, action handling, or speech behavior.
- 地點是主要資訊，必須保留；已知地點使用友善中文名稱，未知地點顯示「服務地點」，不可顯示 LOC-* 代碼。
- 不在用戶畫面顯示 API 工具名稱、請求編號、資源類型、內部 ID、部門 ID、英文欄位、容量或剩餘名額。
- 保留大字、高對比、鍵盤 focus、手機版單欄佈局、錯誤訊息、語音輸入、人工協助和重要操作確認。
- Preserve existing uncommitted user changes and do not modify unrelated backend files.

---

### Task 1: Lock the user-facing contract with failing static tests

**Files:**
- Modify: tests/test_frontend_static.py existing diagnostic/index/view contract tests
- Test: frontend/index.html, frontend/interaction-view.js, frontend/styles.css source text

**Interfaces:**
- Consumes: current static asset source files loaded with Path(...).read_text(encoding="utf-8").
- Produces: regression contracts requiring user-facing summaries, friendly location labels, readable step labels, and removal of developer-only UI text.

- [x] **Step 1: Replace the diagnostic prompt assertion with the new index contract**

Replace test_index_advertises_mcp_diagnostic_command with:

```python
    def test_index_hides_developer_only_diagnostics(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="mode-badge"', html)
        self.assertNotIn("mcp medical.list_departments {}", html)
        self.assertIn('id="speech-status"', html)
        self.assertIn('id="action-list"', html)
```

This must fail against the current badge and MCP help text.

- [x] **Step 2: Add the renderer contract**

```python
    def test_view_uses_friendly_service_workspace_fields(self):
        source = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        for marker in (
            "LOCATION_LABELS", "LOC-REHAB-01", "復康治療室",
            "STEP_LABELS", "renderMedicalData", "所需時間", "服務地點",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("renderToolEvents", source)
        self.assertNotIn("tool-event-card", source)
        self.assertNotIn("request_id", source)
```

Update the existing renderer test so it checks createInteractionView, renderMedicalData and actions, rather than requiring tool_events.

- [x] **Step 3: Add the summary CSS contract**

```python
    def test_styles_prioritize_summary_cards(self):
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        self.assertIn(".summary-card", css)
        self.assertNotIn(".tool-event-card", css)
```

- [x] **Step 4: Run the changed tests and verify the expected red state**

```bash
python3 -m unittest tests.test_frontend_static.FrontendStaticTests.test_index_hides_developer_only_diagnostics tests.test_frontend_static.FrontendStaticTests.test_view_uses_friendly_service_workspace_fields tests.test_frontend_static.FrontendStaticTests.test_styles_prioritize_summary_cards -v
```

Expected: FAIL because the current implementation still exposes developer copy, raw tool events, and generic backend data.

- [x] **Step 5: Commit the failing contract tests**

```bash
git add tests/test_frontend_static.py
git commit -m "test: define friendly service workspace contract"
```

### Task 2: Implement the user-facing interaction renderer

**Files:**
- Modify: frontend/interaction-view.js constants, data rendering, step rendering, action labels and response rendering
- Test: tests/test_frontend_static.py contracts from Task 1

**Interfaces:**
- Consumes: existing middleware response shape { data, steps, task_state, current_step, actions } and existing action payloads.
- Produces: friendly service/slot labels, mapped progress steps, and no tool_events DOM output; action payloads remain { service_id, date_from, date_to } and { slot_id }.

- [x] **Step 1: Add the mappings**

Near the existing task-state constants add:

```js
const LOCATION_LABELS = {
  "LOC-MAIN-OPD": "第一門診",
  "LOC-IMAGING-CENTER": "影像中心",
  "LOC-REHAB-01": "復康治療室",
};

const STEP_LABELS = {
  load_appointments: "確認現有預約",
  load_services: "選擇服務",
  select_service: "選擇服務",
  search_slots: "查找可預約時段",
  select_slot: "選擇時段",
  confirm_appointment: "確認預約",
  create_appointment: "提交預約",
  get_task_status: "完成預約",
};

const STATUS_LABELS = {
  booked: "已預約",
  confirmed: "已確認",
  completed: "已完成",
  free: "可預約",
};

const HIDDEN_DATA_KEYS = new Set([
  "resourceType", "id", "service_id", "slot_id", "department_id", "location_id",
  "task_id", "task_status", "intent", "intent_source", "booking_source",
  "request_id", "tool_name", "step_id", "arguments", "data", "error",
]);
```

- [x] **Step 2: Add safe display helpers**

Below displayDate add helpers with these guarantees:

```js
function locationLabel(value) {
  if (value && typeof value === "object") {
    if (value.display) return String(value.display);
    if (value.name) return String(value.name);
    value = value.id;
  }
  return LOCATION_LABELS[String(value || "")] || "服務地點";
}

function dateOnly(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("zh-HK", { dateStyle: "medium" }).format(date);
}

function timeOnly(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("zh-HK", { timeStyle: "short" }).format(date);
}

function timeRange(value) {
  const start = timeOnly(value?.start);
  const end = timeOnly(value?.end);
  return end === "—" ? start : [start, end].join("–");
}

function durationLabel(minutes) {
  return Number.isFinite(Number(minutes)) ? [minutes, "分鐘"].join(" ") : "—";
}
```

Unknown location values must return 服務地點 and never the raw LOC-* value.

- [x] **Step 3: Replace the generic data dump with staged medical summaries**

Implement createSummaryCard(title, fields) and renderMedicalData(container, data, response). The renderer must:

1. Render selected_slot only when present, with service, duration, date, time, location, and title 請確認預約資料 or 預約已完成.
2. Otherwise render slots as readable date/time/location cards.
3. Otherwise render services as service/duration/location cards.
4. Otherwise render appointments as service/date/time/location/status cards, or show 目前沒有已預約的醫療服務。 for a medical query with an empty list.
5. Never render internal IDs, tool event payloads, capacity, remaining count, raw resource types, or arbitrary nested objects.

Use this card boundary:

```js
function createSummaryCard(title, fields, className = "summary-card") {
  const card = createElement("article", className);
  card.append(createElement("h3", "", title));
  const list = createElement("dl");
  fields.filter((field) => field?.value && field.value !== "—").forEach((field) => {
    list.append(
      createElement("dt", "", field.label),
      createElement("dd", "", field.value),
    );
  });
  if (!list.children.length) return null;
  card.append(list);
  return card;
}
```

Keep a small allowlist for non-medical scalar fields such as plan_name, year, status, amount, payment_status, scheduled_date, title, summary, district and name; skip unknown keys and all keys ending in _id.

- [x] **Step 4: Map progress steps and derive statuses**

Change renderSteps(container, steps) to renderSteps(container, steps, currentStep). Derive status as:

```js
const rawStatus = step.status
  || (step.ok === false ? "failed" : step.ok === true ? "completed" : "pending");
const status = rawStatus === "pending" && step.step_id === currentStep ? "current" : rawStatus;
const label = STEP_LABELS[step.step_id] || "服務步驟";
```

Use the mapped label and current STEP_STATUS_LABELS; never use tool_name, step_id, or raw status as visible text.

- [x] **Step 5: Make service and slot buttons useful while preserving action payloads**

Build service text with:

```js
const label = [
  service.name || service.name_en,
  durationLabel(service.duration_minutes),
  locationLabel(service.location || service.location_id),
].join("｜");
```

Build slot text from dateOnly, timeRange and locationLabel. Keep kind search_slots with service_id/date_from/date_to and kind select_slot with slot_id unchanged.

- [x] **Step 6: Remove tool-event rendering and simplify health copy**

Delete renderToolEvents and its call. In renderResponse call:

```js
renderSteps(stepsRoot, response.steps, response.current_step);
renderData(taskRoot, response.data, response);
renderActions(actionsRoot, response, onAction);
```

Change the reachable health text to exactly 服務已連線; keep the offline message and error handling.

- [x] **Step 7: Run focused tests and syntax check**

```bash
python3 -m unittest tests.test_frontend_static -v
node --check frontend/interaction-view.js
```

Expected: renderer syntax passes; the static suite may still fail because Task 3 has not yet removed the HTML developer copy or added the summary-card CSS contract.

- [x] **Step 8: Commit the renderer**

```bash
git add frontend/interaction-view.js tests/test_frontend_static.py
git commit -m "feat: render friendly service summaries"
```

### Task 3: Remove developer copy and style the summary hierarchy

**Files:**
- Modify: frontend/index.html header status and message-form help text
- Modify: frontend/styles.css summary-card rules and unused tool-event rules
- Modify: frontend/README.md user-facing behavior description
- Test: tests/test_frontend_static.py index and style contracts

**Interfaces:**
- Consumes: semantic markup IDs and renderer class names from Task 2.
- Produces: a user-facing page with no test-mode/MCP prompt, readable summary cards, preserved controls, and matching documentation.

- [x] **Step 1: Remove developer-only HTML text**

Delete the 測試模式 span from the header status and the paragraph containing mcp medical.list_departments {}. Keep health-status, speech-status, mic-button, speak-stop-button, send-button, task-steps, and action-list.

- [x] **Step 2: Add summary-card styles and remove raw event styles**

Replace the data-card and tool-event-card presentation rules with:

```css
.summary-card {
  padding: 18px;
  border: 1px solid #c9ddda;
  border-radius: 16px;
  background: #fbfdfc;
}

.summary-card h3 {
  margin: 0 0 12px;
  color: var(--teal-900);
  font-size: 1.08rem;
}

.summary-card dl {
  display: grid;
  grid-template-columns: minmax(96px, 0.7fr) minmax(0, 1.3fr);
  gap: 8px 14px;
  margin: 0;
}

.summary-card dt {
  color: var(--muted);
  font-size: 0.82rem;
}

.summary-card dd {
  margin: 0;
  overflow-wrap: anywhere;
  font-weight: 800;
}
```

Keep the existing empty state, action controls, date/referral controls, focus styles and mobile rules. Do not add a technical-details disclosure.

- [x] **Step 3: Update the frontend README**

State that the workspace shows readable progress, service/date/time/location summaries and required actions. Remove the claim that normal users see tool events, HTTP contracts, backend JSON or an MCP diagnostic prompt. Keep startup, workflow examples, speech behavior and zero-build instructions.

- [x] **Step 4: Run the frontend suite and whitespace check**

```bash
python3 -m unittest tests.test_frontend_static -v
git diff --check
```

- [x] **Step 5: Commit the page and style cleanup**

```bash
git add frontend/index.html frontend/styles.css frontend/README.md tests/test_frontend_static.py
git commit -m "refactor: simplify Ponte service workspace UI"
```

### Task 4: Verify the complete workflow and hand off

**Files:**
- Verify: frontend/index.html, frontend/interaction-view.js, frontend/styles.css, frontend/README.md
- Verify: all existing Python tests and JavaScript modules

**Interfaces:**
- Consumes: the completed user-facing renderer and existing middleware action contracts.
- Produces: fresh evidence that the simplification did not regress medical booking, other services, or responsive/accessibility contracts.

- [x] **Step 1: Run all JavaScript syntax checks**

```bash
node --check frontend/app.js
node --check frontend/mcp-client.js
node --check frontend/interaction-view.js
node --check frontend/speech.js
```

- [x] **Step 2: Run frontend static tests**

```bash
python3 -m unittest tests.test_frontend_static -v
```

- [x] **Step 3: Run the full Python regression suite**

```bash
python3 -m unittest discover -v
```

- [x] **Step 4: Inspect the final diff and intentional identifiers**

```bash
git diff --check
git status --short
rg -n "測試模式|mcp medical\.list_departments|tool-event-card" frontend/index.html frontend/interaction-view.js frontend/styles.css frontend/README.md
```

Expected: no developer-only copy or raw tool-event class. The only intentional internal identifiers remaining in renderer source are mapping/payload inputs used to convert backend data into friendly labels.

- [x] **Step 5: Run a local medical booking smoke check**

Start:

```bash
python3 -m frontend.server --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173, exercise 我想預約醫療服務 through service selection, date range, slot selection, referral confirmation and completion. Confirm the workspace shows progress, service, date/time, location, status and actions only; no request numbers, tool names, resourceType, or LOC-* values. Also check an empty appointment query and a mobile-width layout.

- [x] **Step 6: Mark each completed plan step with x and report evidence**

After every completed step, change its checkbox from [ ] to [x] in this plan, then report exact command results and any smoke-check limitation in the final response.
