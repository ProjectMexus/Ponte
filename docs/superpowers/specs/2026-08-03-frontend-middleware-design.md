# Ponte Frontend and Middleware Design

## Goal

建立一個面向長者的第一版 Ponte 網頁入口，讓使用者可以用文字或語音提出醫療預約需要；由 middleware 的 Interaction Controller 直接經 MCP / Tool Adapter 呼叫現有 mock backend，並保留把 Workflow Orchestrator 加入 pipeline 的位置。

本階段的首要目標是驗證 middleware 與 backend 的可用性和資料流，不追求完整 LLM、durable task 或高保真 UI。

## Scope

### In scope

- 原生 HTML、CSS、JavaScript 的前端，零 npm runtime dependency。
- 適合長者的單頁 UI：清晰大字、少量主要操作、高對比、文字輸入、麥克風輸入及可選語音朗讀。
- Middleware HTTP bridge，讓瀏覽器透過 HTTP 使用現有 Python MCP / Tool Adapter Layer。
- Deterministic Interaction Controller，先用可預測規則驗證醫療工具鏈，不依賴外部 LLM。
- `ExecutionPipeline` 邊界；目前直接執行 MCP，未來可在 pipeline 中加入 Workflow Orchestrator stage。
- 醫療查詢／預約驗證流程：查詢已有預約、列出服務、查詢可用時段、確認後建立預約、查詢 task 狀態。
- 確認前禁止呼叫正式 POST 工具。
- middleware、adapter、HTTP bridge、前端基本 smoke test。

### Out of scope

- 真實 ASR、TTS、身份驗證或醫療資料。
- 完整 LLM 意圖識別、通用自然語言規劃器。
- Workflow Orchestrator、durable task runtime、scheduler、policy engine 的實作。
- 完整的 `medical.reschedule_appointment` backend contract；目前只使用既有預約與建立預約能力。
- Action Receipt store、screenshot store、管理員工作台。
- React/Vite 或其他前端 build toolchain。

## Architecture

```text
Frontend
  User Interface
  ├─ text input
  ├─ browser speech recognition / transcript editing
  ├─ optional speech synthesis
  └─ conversation + task workspace
          │ HTTP
          ▼
Middleware
  Interaction Controller
  └─ Execution Pipeline
     └─ Direct MCP Execution Stage (current)
          │
          ▼
MCP / Tool Adapter Layer
  Tool Registry + RestAdapter
          │ HTTP
          ▼
Mock Backend API
  One Account / Medical / Social Welfare domains
```

The `Workflow Orchestrator` is not a replacement mode. It will be added as a middleware pipeline stage before the MCP execution stage:

```text
Interaction Controller
  → Workflow Orchestrator Stage (future)
  → MCP / Tool Adapter Stage
  → Backend API
```

The frontend talks only to middleware response contracts. It does not construct backend URLs, methods, headers or MCP envelopes.

## Components and responsibilities

### Frontend

The frontend is a static app under `frontend/` with focused modules:

- `index.html`: semantic page structure and accessible controls.
- `styles.css`: elder-friendly typography, spacing, contrast, responsive layout and state styles.
- `app.js`: browser bootstrap and UI event wiring.
- `mcp-client.js`: HTTP client for middleware endpoints; no backend URL construction.
- `interaction-view.js`: render conversation, task steps, tool events, confirmations and errors.
- `speech.js`: Web Speech API integration with graceful text-only fallback.

The desktop layout uses a conversation area and a service workspace. On small screens they stack vertically. The primary UI controls are text send, microphone, stop speaking, confirm, cancel, retry and request human help. Voice recognition always shows an editable transcript before submission.

The initial visual flow is:

```text
理解需要 → 查詢預約／服務 → 選擇時段 → 確認提交 → 完成／等待確認
```

Base text is 20px or larger, important data is 24–28px, primary controls are at least 56px high, and status is communicated through text and iconography in addition to color.

### Middleware Interaction Controller

The controller owns session-level interaction state and maps user input or UI actions to structured operations. It uses deterministic keyword intent matching for the first vertical slice, with an interface that can later be backed by an LLM without changing the UI contract.

The controller must:

- accept text or speech transcripts as the same `message` input;
- keep a session identifier and current step;
- call tools only through the execution pipeline;
- surface tool events and backend errors in a user-readable response;
- create an idempotency key for each formal submission;
- stop before `medical.create_appointment` until an explicit confirmation action is received;
- return enough structured state for the UI to display visible execution.

The controller is intentionally not durable in this phase. Session state may be in memory; durable task persistence belongs to the future Workflow Orchestrator stage.

### Execution Pipeline

The pipeline exposes one stable dispatch entry point to the controller:

```text
dispatch(StructuredInteractionRequest) -> InteractionExecutionResult
```

The current implementation contains a `DirectMcpExecutionStage`, which calls the existing MCP registry and REST adapter. Future workflow constraints are inserted as another stage, rather than changing the controller or creating a second frontend path.

### HTTP bridge

The bridge runs beside the static frontend and uses the existing `MCP.registry` and `MCP.rest_adapter` implementation. It must not accept arbitrary URL, HTTP method or headers from the browser.

Endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Report bridge state, backend target and registered tool count. |
| `GET` | `/api/mcp/tools` | Return the fixed MCP tool catalog for diagnostics. |
| `POST` | `/api/mcp/tools/call` | Direct adapter test endpoint using a tool name and MCP envelope. |
| `POST` | `/api/interactions/message` | Normal frontend entry point for a text or speech transcript. |
| `POST` | `/api/interactions/action` | Handle select slot, confirm, cancel, retry and human-help actions. |

`/api/mcp/tools/call` accepts:

```json
{
  "name": "medical.get_my_appointments",
  "arguments": {
    "context": {
      "patient_id": "PAT-DEMO-001",
      "authorization": "Bearer mock-user-token",
      "request_id": "REQ-DEMO-001"
    },
    "input": {}
  }
}
```

The bridge returns structured result data and stable error codes. Tracebacks and local file paths never reach the browser.

## Medical vertical slice

The first executable chain uses only currently documented and implemented tools:

```text
medical.get_my_appointments
  → medical.list_appointment_services
  → medical.search_appointment_slots
  → [explicit user confirmation]
  → medical.create_appointment
  → medical.get_task_status
```

The current backend does not expose `medical.reschedule_appointment`. Therefore the first UI labels this flow as medical appointment assistance and does not claim that a new appointment is a reschedule. When a reschedule contract is added, it can be introduced as a new tool/workflow mapping while preserving the same UI and pipeline contracts.

For a formal appointment submission, the middleware supplies:

- `patient_id` and mock authorization context;
- a unique `request_id`;
- an idempotency key tied to session and submission step;
- `consent: true` in the documented backend input body; the middleware keeps the explicit confirmation decision in its own task event and only calls the backend after that decision.

The middleware only reports submission success after the adapter receives a successful backend response.

## Error handling

Errors are grouped into user-visible categories while preserving machine-readable details:

- invalid input: ask the user to correct the missing or invalid field;
- backend unavailable or timeout: explain that the service is temporarily unavailable and offer retry;
- slot unavailable or duplicate booking: keep the task open and offer another slot;
- confirmation required: keep the task at the confirmation step and do not submit;
- unsupported speech: keep text input active and explain that typing is available;
- unknown or non-retryable adapter error: show a concise message and offer human help.

Every error response includes a stable code, a safe message, retryability and a request ID for diagnostics.

## Testing and acceptance

### Unit tests

- Controller maps representative Cantonese/Chinese phrases to the medical intent.
- Controller emits the expected MCP tool request for each step.
- Formal submission is blocked until confirmation.
- Confirmation creates an idempotency key and passes consent/confirmation to the adapter.
- Adapter errors become safe middleware responses.

### Integration tests

Start a temporary mock backend and middleware server, then verify:

- `/api/health` reports the expected tool count and backend reachability.
- `/api/mcp/tools` returns the existing fixed registry.
- `/api/mcp/tools/call` reaches the mock backend with the expected method, path, query and allowlisted headers.
- `/api/interactions/message` reaches a real medical backend query.
- `/api/interactions/action` cannot submit before confirmation and can submit after confirmation.
- backend errors are returned without tracebacks or local paths.

### Frontend smoke checks

- Static files are served successfully.
- The page can load health status.
- Text input displays the controller response and tool progress.
- Voice unsupported state leaves text input usable.
- Confirmation, cancel and retry controls update the visible task state.

## Acceptance criteria

The first implementation is accepted when:

1. A browser can start the frontend and reach middleware through HTTP.
2. Middleware can call the existing MCP / Tool Adapter Layer and the real mock backend.
3. The UI can drive the medical query and appointment-assistance path using text.
4. Voice input and optional speech output work when the browser provides the Web Speech APIs, with a usable text fallback when it does not.
5. A formal appointment POST is impossible without explicit confirmation.
6. Tool events, task steps and backend receipts are visible in the UI.
7. The future Workflow Orchestrator insertion point is represented by a stable middleware pipeline interface.
8. Automated tests cover the controller, bridge and real mock-backend request path.
