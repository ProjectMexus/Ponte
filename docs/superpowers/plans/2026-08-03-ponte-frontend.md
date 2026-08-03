# Ponte Frontend UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立零 build dependency 的長者友善 Ponte 網頁，透過 middleware HTTP contract 驅動醫療預約協助，並支援文字輸入、瀏覽器語音輸入及可選語音朗讀。

**Architecture:** Frontend 是只負責呈現和裝置互動的 static app；`mcp-client.js` 只呼叫 middleware，不知道 MCP registry 或 mock backend。`app.js` 保存頁面 session 與事件綁定，`interaction-view.js` 將 middleware response 轉成對話、流程、工具事件和確認卡片，`speech.js` 封裝可選的 Web Speech API，瀏覽器不支援時仍可完整使用文字模式。

**Tech Stack:** 原生 HTML、CSS、JavaScript ES modules、Web Speech API、Python 標準庫 static server、`unittest` 和 `node --check`（只作語法檢查，不新增 npm runtime dependency）。

## Global Constraints

- Frontend 位於 `frontend/`，不新增 React、Vite、npm package 或外部 CDN dependency。
- Frontend 只呼叫 middleware：`/api/health`、`/api/interactions/message`、`/api/interactions/action`；不得直接呼叫 mock backend 或自行建立 MCP envelope。
- Middleware response contract 固定使用 `session_id`、`assistant_message`、`task_state`、`current_step`、`steps`、`tool_events`、`actions`、`data`。
- 文字是穩定的主要測試入口；語音功能不可成為使用頁面的必要條件。
- 語音辨識使用 `zh-HK`，辨識結果先回填輸入框供使用者修改，不能直接送出或直接提交正式預約。
- 語音朗讀提供停止控制，並處理瀏覽器 autoplay／speech API 不可用的情況。
- 基本文字 20px 以上，重要資訊 24–28px，主要按鈕至少 56px 高；狀態不只靠顏色表達。
- 每個 formal submit、confirmation、cancel、retry 和 human-help action 都由 middleware 決定結果；frontend 不執行業務流程。
- 保留工作區現有未提交變更，不修改與 frontend 無關的檔案。

---

## Middleware contract consumed by the frontend

The frontend must consume these requests and responses exactly:

```json
POST /api/interactions/message
{
  "session_id": "S-20260803-001",
  "message": "我想查詢醫療預約",
  "source": "text"
}
```

```json
POST /api/interactions/action
{
  "session_id": "S-20260803-001",
  "action": "search_slots",
  "payload": {
    "service_id": "SERVICE-US-001",
    "date_from": "2026-08-10",
    "date_to": "2026-08-14"
  }
}
```

```json
{
  "session_id": "S-20260803-001",
  "assistant_message": "請選擇你方便的時段。",
  "task_state": "selecting_slot",
  "current_step": "search_slots",
  "steps": [
    {"id": "load_appointments", "label": "查詢現有預約", "status": "completed"},
    {"id": "search_slots", "label": "搜尋可用時段", "status": "current"}
  ],
  "tool_events": [],
  "actions": [
    {"id": "select-slot-1", "kind": "select_slot", "label": "2026年8月12日 下午2時", "payload": {"slot_id": "SLOT-US-20260812-1400"}}
  ],
  "data": {"slots": []}
}
```

### Task 1: Add the static server and typed middleware client

**Files:**
- Create: `frontend/server.py`
- Create: `frontend/mcp-client.js`
- Create: `tests/test_frontend_static.py`

**Interfaces:**
- Produces `python3 -m frontend.server --host 127.0.0.1 --port 5173`.
- Produces `MiddlewareClient(baseUrl)` with `health()`, `sendMessage(request)`, `sendAction(request)` and `callTool(name, arguments)`.
- Produces `MiddlewareError` with `status`, `code`, `message` and `details`.
- Static server serves only files below `frontend/` and returns 404 for path traversal or missing files.

- [x] **Step 1: Write the failing static-server and client contract checks**

```python
import json
import threading
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from frontend.server import create_http_server


class FrontendStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_http_server("127.0.0.1", 0, Path("frontend"))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_client_asset_is_served(self):
        with self.opener.open(self.base_url + "/mcp-client.js") as response:
            self.assertIn("MiddlewareClient", response.read().decode("utf-8"))

    def test_path_traversal_is_not_served(self):
        with self.assertRaises(Exception):
            self.opener.open(self.base_url + "/../docs/PonteArch.md")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the check to verify it fails**

Run: `python3 -m unittest tests.test_frontend_static -v`

Expected: FAIL because `frontend/server.py`, `frontend/index.html` and `frontend/mcp-client.js` do not exist.

- [x] **Step 3: Implement a safe static server and middleware-only client**

Use `SimpleHTTPRequestHandler` with a resolved `frontend/` root and reject any resolved path outside that root. Keep the server independent from the middleware process so frontend and middleware can be started and tested separately.

Implement the client around one private request method:

```javascript
export class MiddlewareError extends Error {
  constructor(code, message, status = 0, details = {}) {
    super(message);
    this.name = "MiddlewareError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}


export class MiddlewareClient {
  constructor(baseUrl = window.PONTE_MIDDLEWARE_URL || "http://127.0.0.1:8090") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async request(path, options = {}) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new MiddlewareError(
        payload.error?.code || "MIDDLEWARE_HTTP_ERROR",
        payload.error?.message || "服務暫時未能回應。",
        response.status,
        payload.error || payload,
      );
    }
    return payload;
  }

  health() { return this.request("/api/health"); }
  sendMessage(body) { return this.request("/api/interactions/message", { method: "POST", body: JSON.stringify(body) }); }
  sendAction(body) { return this.request("/api/interactions/action", { method: "POST", body: JSON.stringify(body) }); }
  callTool(name, argumentsValue) { return this.request("/api/mcp/tools/call", { method: "POST", body: JSON.stringify({ name, arguments: argumentsValue }) }); }
}
```

The client must parse non-JSON responses into a safe `MIDDLEWARE_INVALID_RESPONSE` error and never expose raw response HTML to the UI.

- [x] **Step 4: Run the checks to verify they pass**

Run: `python3 -m unittest tests.test_frontend_static -v`

Expected: all static server checks PASS.

Run: `node --check frontend/mcp-client.js`

Expected: exit code 0.

- [x] **Step 5: Commit**

```bash
git add frontend/server.py frontend/mcp-client.js tests/test_frontend_static.py
git commit -m "feat: add Ponte frontend server and middleware client"
```

### Task 2: Build the accessible page shell and elder-friendly visual system

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/styles.css`

**Interfaces:**
- Produces semantic landmarks: `header`, `main`, conversation section, service workspace and live status region.
- Produces stable element IDs used by `app.js`: `health-status`, `conversation-list`, `message-form`, `message-input`, `mic-button`, `speak-stop-button`, `task-steps`, `task-content`, `action-list`, `global-error`.
- Produces accessible labels and keyboard focus states without requiring JavaScript to understand the business domain.

- [x] **Step 1: Write the failing asset and accessibility checks**

Extend `tests/test_frontend_static.py`:

```python
def test_index_has_required_landmarks_and_controls(self):
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    for token in (
        '<main', 'aria-live="polite"', 'id="message-input"',
        'id="mic-button"', 'id="speak-stop-button"',
        'id="task-steps"', 'id="action-list"',
    ):
        self.assertIn(token, html)
    self.assertIn('lang="zh-Hant"', html)


def test_styles_define_large_controls_and_focus(self):
    css = Path("frontend/styles.css").read_text(encoding="utf-8")
    self.assertRegex(css, r"font-size:\s*20px")
    self.assertRegex(css, r"min-height:\s*56px")
    self.assertIn(":focus-visible", css)
```

- [x] **Step 2: Run the checks to verify they fail**

Run: `python3 -m unittest tests.test_frontend_static.FrontendStaticTests.test_index_has_required_landmarks_and_controls tests.test_frontend_static.FrontendStaticTests.test_styles_define_large_controls_and_focus -v`

Expected: FAIL because the HTML and CSS assets are not implemented.

- [x] **Step 3: Implement the semantic shell and CSS**

Create a two-column desktop layout and a stacked mobile layout:

```html
<main class="app-shell">
  <section class="conversation-panel" aria-labelledby="conversation-heading">
    <div id="conversation-list" class="conversation-list" aria-live="polite"></div>
    <form id="message-form" class="message-form">
      <label for="message-input">想對 Ponte 說什麼？</label>
      <textarea id="message-input" rows="2" autocomplete="off"></textarea>
      <div class="input-actions">
        <button id="mic-button" type="button" class="button button-secondary">按這裡說話</button>
        <button id="speak-stop-button" type="button" class="button button-secondary">停止朗讀</button>
        <button type="submit" class="button button-primary">送出</button>
      </div>
    </form>
  </section>
  <aside class="workspace-panel" aria-labelledby="workspace-heading">
    <div id="health-status" role="status"></div>
    <ol id="task-steps" class="task-steps"></ol>
    <div id="task-content"></div>
    <div id="action-list" class="action-list"></div>
  </aside>
</main>
```

Use no decorative gradients or dense navigation. Provide large readable cards for appointment/service/slot data, visible labels for risk and confirmation, sticky action controls on mobile, and an always-visible global error region with `role="alert"`. Use `:focus-visible`, `prefers-reduced-motion`, CSS custom properties for high-contrast colors, and text labels alongside icons.

- [x] **Step 4: Run the checks to verify they pass**

Run: `python3 -m unittest tests.test_frontend_static -v`

Expected: all asset and accessibility checks PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/index.html frontend/styles.css tests/test_frontend_static.py
git commit -m "feat: add elder-friendly Ponte interface shell"
```

### Task 3: Implement the response-driven conversation and task view

**Files:**
- Create: `frontend/interaction-view.js`
- Modify: `frontend/index.html` only if the renderer needs an additional stable container.

**Interfaces:**
- Produces `createInteractionView({conversationRoot, healthRoot, stepsRoot, taskRoot, actionsRoot, errorRoot, onAction})`.
- Produces `renderResponse(response)`, `renderHealth(payload)`, `renderError(error)` and `clearError()`.
- Consumes only the middleware response contract; it never calls `fetch` or interprets tool names as backend URLs.

- [x] **Step 1: Write the failing static contract check**

Extend `tests/test_frontend_static.py`:

```python
def test_view_module_exports_renderer(self):
    js = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
    self.assertIn("createInteractionView", js)
    self.assertIn("tool_events", js)
    self.assertIn("actions", js)
```

- [x] **Step 2: Run the check to verify it fails**

Run: `python3 -m unittest tests.test_frontend_static.FrontendStaticTests.test_view_module_exports_renderer -v`

Expected: FAIL because the view module does not exist.

- [x] **Step 3: Implement safe, response-driven rendering**

Render all server-provided text through `textContent`, never `innerHTML` with untrusted response values. The view must:

- append the user message and assistant message to the conversation list;
- show `task_state` and `current_step` as text;
- render each step with `completed`, `current`, `pending` or `failed` labels;
- render appointment/service/slot data as readable key-value cards;
- render each `tool_event` with tool name, status and request ID;
- render `actions` as buttons and call `onAction(action)` with the original action object;
- show `global-error` for safe error messages and keep existing conversation content visible.

Use an explicit `formatValue(value)` helper that handles strings, numbers, booleans, arrays and objects without leaking `[object Object]`. Display dates in `zh-HK` only when the value is a valid ISO date; retain the raw value in a visually secondary diagnostic line when formatting fails.

- [x] **Step 4: Run syntax and static checks**

Run: `node --check frontend/interaction-view.js`

Expected: exit code 0.

Run: `python3 -m unittest tests.test_frontend_static -v`

Expected: all frontend static checks PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/interaction-view.js frontend/index.html tests/test_frontend_static.py
git commit -m "feat: render Ponte conversation and task state"
```

### Task 4: Add optional Cantonese speech input and output

**Files:**
- Create: `frontend/speech.js`
- Modify: `frontend/index.html` only if the speech support status needs a dedicated label.
- Modify: `frontend/styles.css` only if recording or unsupported states need visual styles.

**Interfaces:**
- Produces `createSpeechController({onTranscript, onStateChange})`.
- `supported: boolean` reports whether recognition is available.
- `start()`, `stop()`, `speak(text)`, `stopSpeaking()` are safe no-op or stateful operations.
- Recognition language is `zh-HK`; transcript callbacks include `{text, isFinal}`.

- [x] **Step 1: Write the failing static checks**

Extend `tests/test_frontend_static.py`:

```python
def test_speech_module_has_fallback_and_cantonese_locale(self):
    js = Path("frontend/speech.js").read_text(encoding="utf-8")
    self.assertIn("SpeechRecognition", js)
    self.assertIn("webkitSpeechRecognition", js)
    self.assertIn('zh-HK', js)
    self.assertIn("speechSynthesis", js)
```

- [x] **Step 2: Run the check to verify it fails**

Run: `python3 -m unittest tests.test_frontend_static.FrontendStaticTests.test_speech_module_has_fallback_and_cantonese_locale -v`

Expected: FAIL because `frontend/speech.js` does not exist.

- [x] **Step 3: Implement feature detection and editable transcript behavior**

Use the browser implementation when available and report `unsupported` otherwise:

```javascript
export function createSpeechController({ onTranscript, onStateChange }) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = Recognition ? new Recognition() : null;
  const supported = Boolean(recognition);
  if (!supported) onStateChange("unsupported");
  if (recognition) {
    recognition.lang = "zh-HK";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.onstart = () => onStateChange("listening");
    recognition.onresult = (event) => {
      const text = Array.from(event.results).map((result) => result[0].transcript).join("");
      onTranscript({ text, isFinal: event.results[event.results.length - 1].isFinal });
    };
    recognition.onerror = () => onStateChange("error");
    recognition.onend = () => onStateChange("idle");
  }
  return {
    supported,
    start: () => recognition?.start(),
    stop: () => recognition?.stop(),
    speak: (text) => { if (text && window.speechSynthesis) window.speechSynthesis.speak(new SpeechSynthesisUtterance(text)); },
    stopSpeaking: () => window.speechSynthesis?.cancel(),
  };
}
```

Do not auto-submit final transcripts. `app.js` writes them into `message-input`, and the user presses `送出`. Automatically speak only the assistant message after a user-initiated interaction; catch speech synthesis failures and leave text output intact.

- [x] **Step 4: Run syntax and static checks**

Run: `node --check frontend/speech.js`

Expected: exit code 0.

Run: `python3 -m unittest tests.test_frontend_static -v`

Expected: all speech fallback checks PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/speech.js frontend/index.html frontend/styles.css tests/test_frontend_static.py
git commit -m "feat: add optional Cantonese speech interaction"
```

### Task 5: Wire the app to middleware messages and actions

**Files:**
- Create: `frontend/app.js`
- Modify: `frontend/index.html` to load `app.js` as a module.

**Interfaces:**
- Produces browser bootstrap `startPonteApp()`.
- Consumes `MiddlewareClient`, `createInteractionView` and `createSpeechController`.
- Sends `{session_id, message, source}` for text or voice transcripts.
- Sends `{session_id, action, payload}` for every middleware action button.

- [x] **Step 1: Write the failing static wiring checks**

Extend `tests/test_frontend_static.py`:

```python
def test_app_wires_client_view_and_speech(self):
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    for token in ("MiddlewareClient", "createInteractionView", "createSpeechController", "sendMessage", "sendAction"):
        self.assertIn(token, js)
```

- [x] **Step 2: Run the check to verify it fails**

Run: `python3 -m unittest tests.test_frontend_static.FrontendStaticTests.test_app_wires_client_view_and_speech -v`

Expected: FAIL because `frontend/app.js` does not exist.

- [x] **Step 3: Implement event wiring and resilient request state**

On startup:

1. Generate a page session ID such as `S-${Date.now()}`.
2. Instantiate `MiddlewareClient`, view and speech controller.
3. Call `health()` and render `backend_reachable`; keep text input enabled even when health fails.
4. Bind form submit to `sendMessage({session_id, message, source: "text"})`.
5. Bind mic button to start/stop recognition; update button label and `aria-pressed`.
6. Bind speech stop to `stopSpeaking()`.
7. Bind view actions to `sendAction({session_id, action: action.kind, payload: action.payload})`.
8. Render the response and speak `assistant_message` only after a successful user-triggered request.

Disable only the submit control while a request is pending. Keep cancel and stop controls available. On `MiddlewareError`, call `view.renderError` with its safe message and leave the last valid task state on screen. Do not catch errors by replacing the entire page with a generic failure message.

- [x] **Step 4: Run syntax and static checks**

Run: `node --check frontend/app.js && node --check frontend/mcp-client.js && node --check frontend/interaction-view.js && node --check frontend/speech.js`

Expected: exit code 0 for all modules.

Run: `python3 -m unittest tests.test_frontend_static -v`

Expected: all frontend wiring checks PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/app.js frontend/index.html tests/test_frontend_static.py
git commit -m "feat: connect Ponte frontend to middleware"
```

### Task 6: Verify frontend with the running middleware and document startup

**Files:**
- Create: `frontend/README.md`
- Modify: `tests/test_frontend_static.py` only if the static smoke test needs a missing server behavior covered by the README.

**Interfaces:**
- Documents `PONTE_MIDDLEWARE_URL` and the separate frontend/middleware startup commands.
- Provides a repeatable browser smoke checklist for text, voice fallback, tool events and confirmation actions.

- [x] **Step 1: Add the runbook**

Document this exact local setup:

```bash
python3 -m mock_backends.server --host 127.0.0.1 --port 8080 --data-dir /tmp/ponte-mock-data
PONTE_BACKEND_URL=http://127.0.0.1:8080 python3 -m middleware.server --host 127.0.0.1 --port 8090
python3 -m frontend.server --host 127.0.0.1 --port 5173
```

Document optional browser configuration before loading the page:

```javascript
window.PONTE_MIDDLEWARE_URL = "http://127.0.0.1:8090";
```

The default already points to `http://127.0.0.1:8090`; the config exists so a future deployed middleware URL can be selected without changing application logic.

- [x] **Step 2: Run automated frontend verification**

Run: `python3 -m unittest tests.test_frontend_static -v`

Expected: all static server, landmark and module contract tests PASS.

Run: `node --check frontend/app.js && node --check frontend/mcp-client.js && node --check frontend/interaction-view.js && node --check frontend/speech.js`

Expected: exit code 0.

- [ ] **Step 3: Run the manual browser smoke checklist**

With all three local processes running, verify:

1. Page opens with readable large text and health status.
2. Typing `我想查詢醫療預約` displays assistant response and tool events.
3. Services and slots render as large selectable cards.
4. Selecting a slot shows the confirmation state and displays date, time and location.
5. No POST submission occurs before clicking `確認提交`.
6. Confirming shows submitted task and receipt data returned by middleware.
7. Clicking `停止朗讀` stops speech synthesis.
8. In a browser without speech recognition, the microphone control explains that text input remains available.
9. Backend shutdown produces a readable error and keeps the text form usable.

- [x] **Step 4: Commit**

```bash
git add frontend/README.md tests/test_frontend_static.py
git commit -m "docs: document Ponte frontend verification"
```

## Plan self-review checklist

- Every frontend requirement is covered by Tasks 1–6: static UI, elder-friendly sizing, text input, optional Cantonese voice, speech fallback, visible tool/task state, confirmation controls and middleware integration.
- The frontend never chooses a tool, constructs backend headers, or submits a formal operation directly.
- The response field names match the middleware plan: `session_id`, `assistant_message`, `task_state`, `current_step`, `steps`, `tool_events`, `actions`, `data`.
- The plan does not assume `medical.reschedule_appointment`; the UI displays the current appointment-assistance contract returned by middleware.
- The frontend and middleware can run as separate processes, with middleware CORS supporting the static server origin.
