# Ponte Middleware Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可由前端使用的 Python middleware，將 Interaction Controller、可插入的 execution pipeline、HTTP bridge 與現有 MCP / Tool Adapter Layer 串接到 mock backend。

**Architecture:** Middleware 以 stdlib `ThreadingHTTPServer` 暴露固定 API。Interaction Controller 管理記憶體 session 和醫療預約協助流程，所有工具呼叫都經過 `ExecutionPipeline`；目前 pipeline 只有 `DirectMcpExecutionStage`，未來將 Workflow Orchestrator 作為前置 stage 加入。MCP registry 和 REST adapter 保持既有 contract，不把任意 URL、method 或 header 暴露給瀏覽器。

**Tech Stack:** Python 3.13+、Python 標準庫、既有 `MCP.registry`、`MCP.rest_adapter`、`mock_backends.server`、`unittest`、`http.server`。

## Global Constraints

- Middleware 只使用 Python 標準庫，不新增 pip、npm 或其他 runtime dependency。
- Frontend 只呼叫 middleware API；不得直接拼接 mock backend URL 或 MCP envelope。
- `MCP.registry` 的 21 個工具、既有 input 欄位、enum、context header 規則保持不變。
- Middleware 不實作 Workflow Orchestrator、durable task、scheduler、policy engine 或正式身份驗證。
- Workflow Orchestrator 是未來 pipeline stage，不是替換 MCP execution path 的模式。
- `medical.create_appointment` 只有在 middleware 已記錄明確 confirmation 後才可以呼叫；backend body 只傳送 contract 定義的 `consent: true`。
- HTTP bridge 不接受瀏覽器傳入任意 URL、HTTP method、header 或 filesystem path。
- Session state 本階段只保存在記憶體；重啟後遺失是明確的非目標。
- 所有對外錯誤必須是安全的 JSON；不得返回 traceback 或本機路徑。
- 保留工作區現有未提交變更，不修改與 middleware 無關的檔案。

---

## File and interface map

Create the following focused units:

- `middleware/__init__.py`: package marker and public exports.
- `middleware/contracts.py`: immutable request, tool-call, result and response contracts shared by controller, pipeline and HTTP server.
- `middleware/session.py`: in-memory session state and state transitions.
- `middleware/execution.py`: composable execution stages, pipeline and direct MCP stage.
- `middleware/controller.py`: deterministic medical Interaction Controller and action handling.
- `middleware/server.py`: HTTP routing, JSON parsing, CORS and safe error responses.
- `middleware/tests/test_contracts.py`: serialization and validation tests.
- `middleware/tests/test_execution.py`: pipeline ordering and MCP adapter tests.
- `middleware/tests/test_controller.py`: intent, state and confirmation-gate tests.
- `middleware/tests/test_server.py`: API routing and malformed-request tests.
- `tests/test_middleware_integration.py`: real middleware → MCP adapter → mock backend integration tests.

Shared contracts used across tasks:

```python
@dataclass(frozen=True)
class InteractionRequest:
    session_id: str
    message: str
    source: Literal["text", "voice"] = "text"


@dataclass(frozen=True)
class InteractionActionRequest:
    session_id: str
    action: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]
    step_id: str


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_name: str
    step_id: str
    ok: bool
    request_id: str
    data: Mapping[str, Any] | None = None
    error: Mapping[str, Any] | None = None
```

The stable middleware response shape is:

```json
{
  "session_id": "demo-session-1",
  "assistant_message": "我正在幫你查詢預約。",
  "task_state": "querying",
  "current_step": "load_appointments",
  "steps": [],
  "tool_events": [],
  "actions": [],
  "data": {}
}
```

### Task 1: Define middleware contracts and session state

**Files:**
- Create: `middleware/__init__.py`
- Create: `middleware/contracts.py`
- Create: `middleware/session.py`
- Create: `middleware/tests/__init__.py`
- Create: `middleware/tests/test_contracts.py`

**Interfaces:**
- Produces `InteractionRequest.from_json(value: Mapping[str, Any]) -> InteractionRequest`.
- Produces `InteractionActionRequest.from_json(value: Mapping[str, Any]) -> InteractionActionRequest`.
- Produces `ToolCall` and `ToolExecutionResult`.
- Produces `SessionState` with `task_state`, `current_step`, `data`, `tool_events`, `last_tool_call` and `confirmation_record`.
- Produces `SessionStore.get_or_create(session_id: str) -> SessionState` and `SessionStore.save(state: SessionState) -> None`.
- Produces `build_response(state: SessionState, assistant_message: str, actions: Sequence[Mapping[str, Any]]) -> dict[str, Any]`.

- [x] **Step 1: Write the failing tests**

```python
from datetime import datetime, timezone
import unittest

from middleware.contracts import InteractionActionRequest, InteractionRequest
from middleware.session import SessionStore


class ContractTests(unittest.TestCase):
    def test_message_request_accepts_text_and_voice(self):
        text = InteractionRequest.from_json({
            "session_id": "S-1",
            "message": "我想查醫療預約",
            "source": "text",
        })
        voice = InteractionRequest.from_json({
            "session_id": "S-1",
            "message": "我想改期",
            "source": "voice",
        })
        self.assertEqual(text.source, "text")
        self.assertEqual(voice.source, "voice")

    def test_invalid_message_request_is_rejected(self):
        with self.assertRaises(ValueError):
            InteractionRequest.from_json({"message": "沒有 session"})

    def test_session_store_preserves_confirmation_record(self):
        store = SessionStore()
        state = store.get_or_create("S-1")
        state.confirmation_record = {
            "decision": "confirmed",
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "step_id": "confirm_appointment",
        }
        store.save(state)
        self.assertEqual(store.get_or_create("S-1").confirmation_record["decision"], "confirmed")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest middleware.tests.test_contracts -v`

Expected: FAIL with `ModuleNotFoundError` or missing contract symbols because the middleware package is not implemented.

- [x] **Step 3: Implement the minimal contracts and state store**

Validate non-empty `session_id` and `message`, restrict `source` to `text` or `voice`, reject unknown action values only at the controller boundary, and make `SessionState` fields explicit:

```python
@dataclass
class SessionState:
    session_id: str
    task_state: str = "idle"
    current_step: str = "welcome"
    data: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    last_tool_call: ToolCall | None = None
    confirmation_record: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None
```

Use a dictionary protected by `threading.Lock` so concurrent browser requests cannot create duplicate session objects. `build_response` must return JSON-serializable copies and never expose `ToolCall` objects directly.

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest middleware.tests.test_contracts -v`

Expected: all contract and session tests PASS.

- [x] **Step 5: Commit**

```bash
git add middleware/__init__.py middleware/contracts.py middleware/session.py middleware/tests
git commit -m "feat: add middleware interaction contracts"
```

### Task 2: Build the composable execution pipeline and direct MCP stage

**Files:**
- Create: `middleware/execution.py`
- Create: `middleware/tests/test_execution.py`

**Interfaces:**
- Produces `ExecutionStage.handle(call: ToolCall, next_stage: Callable[[ToolCall], ToolExecutionResult]) -> ToolExecutionResult`.
- Produces `ExecutionPipeline(stages: Sequence[ExecutionStage]).dispatch(call: ToolCall) -> ToolExecutionResult`.
- Produces `DirectMcpExecutionStage(registry: ToolRegistry, adapter: RestAdapter)`.
- Consumes `MCP.registry.ToolRegistry`, `MCP.rest_adapter.RestAdapter` and `MCP.errors.AdapterError`.

- [x] **Step 1: Write the failing tests**

```python
import unittest

from middleware.contracts import ToolCall, ToolExecutionResult
from middleware.execution import DirectMcpExecutionStage, ExecutionPipeline
from MCP.registry import build_registry


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    def invoke(self, definition, arguments):
        self.calls.append((definition.name, arguments))
        return {"request_id": "REQ-1", "data": {"ok": True}}


class ExecutionTests(unittest.TestCase):
    def test_direct_stage_calls_registry_definition_and_adapter(self):
        adapter = RecordingAdapter()
        stage = DirectMcpExecutionStage(build_registry(), adapter)
        result = ExecutionPipeline([stage]).dispatch(ToolCall(
            "medical.list_departments",
            {"context": {"authorization": "Bearer mock-user-token"}, "input": {}},
            "load_departments",
        ))
        self.assertTrue(result.ok)
        self.assertEqual(adapter.calls[0][0], "medical.list_departments")

    def test_pipeline_preserves_stage_order_for_future_workflow_stage(self):
        events = []

        class GateStage:
            def handle(self, call, next_stage):
                events.append("workflow")
                return next_stage(call)

        class TerminalStage:
            def handle(self, call, next_stage):
                events.append("mcp")
                return ToolExecutionResult("fake.tool", call.step_id, True, "REQ-2", {"data": {}}, None)

        ExecutionPipeline([GateStage(), TerminalStage()]).dispatch(ToolCall("fake.tool", {}, "step"))
        self.assertEqual(events, ["workflow", "mcp"])


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest middleware.tests.test_execution -v`

Expected: FAIL because `middleware.execution` and the pipeline classes do not exist.

- [x] **Step 3: Implement pipeline composition and adapter error conversion**

Implement the pipeline as nested `next_stage` calls so a future Workflow Orchestrator can be inserted without changing the controller:

```python
class ExecutionPipeline:
    def __init__(self, stages):
        self._stages = tuple(stages)

    def dispatch(self, call):
        def run(index, current_call):
            if index >= len(self._stages):
                raise RuntimeError("execution pipeline has no terminal stage")
            stage = self._stages[index]
            return stage.handle(current_call, lambda next_call: run(index + 1, next_call))

        return run(0, call)
```

`DirectMcpExecutionStage` looks up the fixed registry definition and invokes the existing adapter. Convert `AdapterError` into `ToolExecutionResult(ok=False, error=error.to_dict())`; do not include tracebacks. Pull `request_id` from successful payload `request_id`, or generate a safe `REQ-MW-*` value when the adapter error has no request ID.

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest middleware.tests.test_execution MCP.tests.test_rest_adapter -v`

Expected: all pipeline tests and all existing adapter tests PASS.

- [x] **Step 5: Commit**

```bash
git add middleware/execution.py middleware/tests/test_execution.py
git commit -m "feat: add composable middleware execution pipeline"
```

### Task 3: Implement the deterministic Interaction Controller

**Files:**
- Create: `middleware/controller.py`
- Create: `middleware/tests/test_controller.py`

**Interfaces:**
- Produces `InteractionController(pipeline: ExecutionPipeline, sessions: SessionStore, patient_id: str, authorization: str)`.
- Produces `handle_message(request: InteractionRequest) -> dict[str, Any]`.
- Produces `handle_action(request: InteractionActionRequest) -> dict[str, Any]`.
- Consumes `ToolCall`, `ToolExecutionResult`, `SessionStore` and `build_response`.

- [x] **Step 1: Write the failing tests**

```python
import unittest

from middleware.contracts import InteractionActionRequest, InteractionRequest, ToolExecutionResult
from middleware.controller import InteractionController
from middleware.session import SessionStore


class RecordingPipeline:
    def __init__(self):
        self.calls = []

    def dispatch(self, call):
        self.calls.append(call)
        if call.name == "medical.get_my_appointments":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-1", {"data": []}, None)
        if call.name == "medical.list_appointment_services":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-2", {"data": [{"id": "SERVICE-US-001", "name": "超聲波檢查"}]}, None)
        if call.name == "medical.search_appointment_slots":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-3", {"data": [{"id": "SLOT-US-20260812-1400", "start": "2026-08-12T14:00:00+08:00"}]}, None)
        if call.name == "medical.create_appointment":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-4", {"data": {"task_id": "TASK-1"}, "task": {"id": "TASK-1"}}, None)
        if call.name == "medical.get_task_status":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-5", {"data": {"status": "SUBMITTED"}}, None)
        raise AssertionError(call.name)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = RecordingPipeline()
        self.controller = InteractionController(self.pipeline, SessionStore(), "PAT-DEMO-001", "Bearer mock-user-token")

    def test_medical_message_loads_appointments_and_services(self):
        response = self.controller.handle_message(InteractionRequest("S-1", "我想查詢醫療預約"))
        self.assertEqual(response["task_state"], "selecting_service")
        self.assertEqual([call.name for call in self.pipeline.calls], [
            "medical.get_my_appointments",
            "medical.list_appointment_services",
        ])

    def test_create_appointment_is_blocked_until_confirmation(self):
        self.controller.handle_message(InteractionRequest("S-1", "我想預約醫療服務"))
        self.controller.handle_action(InteractionActionRequest("S-1", "search_slots", {
            "service_id": "SERVICE-US-001", "date_from": "2026-08-10", "date_to": "2026-08-14",
        }))
        self.controller.handle_action(InteractionActionRequest("S-1", "select_slot", {
            "slot_id": "SLOT-US-20260812-1400",
        }))
        pending = self.controller.handle_action(InteractionActionRequest("S-1", "cancel", {}))
        self.assertEqual(pending["task_state"], "cancelled")
        self.assertNotIn("medical.create_appointment", [call.name for call in self.pipeline.calls])

    def test_confirmation_submits_documented_body_and_reads_task_status(self):
        self.controller.handle_message(InteractionRequest("S-1", "我想預約醫療服務"))
        self.controller.handle_action(InteractionActionRequest("S-1", "search_slots", {
            "service_id": "SERVICE-US-001", "date_from": "2026-08-10", "date_to": "2026-08-14",
        }))
        self.controller.handle_action(InteractionActionRequest("S-1", "select_slot", {
            "slot_id": "SLOT-US-20260812-1400",
        }))
        response = self.controller.handle_action(InteractionActionRequest("S-1", "confirm", {}))
        self.assertEqual(response["task_state"], "submitted")
        create_call = next(call for call in self.pipeline.calls if call.name == "medical.create_appointment")
        self.assertTrue(create_call.arguments["input"]["consent"])
        self.assertNotIn("confirmation", create_call.arguments["input"])
        self.assertEqual(self.pipeline.calls[-1].name, "medical.get_task_status")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest middleware.tests.test_controller -v`

Expected: FAIL because `InteractionController` is not implemented.

- [x] **Step 3: Implement the medical state machine and safe context factory**

Recognize `醫療`, `預約`, `覆診`, `睇醫生`, `改期` as the first intent group. A recognized message calls `medical.get_my_appointments` and then `medical.list_appointment_services`; an unrecognized message returns a helpful text response with no tool call.

Use these exact actions and transitions:

```text
message medical intent → selecting_service
search_slots          → selecting_slot
select_slot           → awaiting_confirmation
confirm               → submitted, then completed when task status is returned
cancel                → cancelled
retry                 → replay the last safe query call
human_help            → human_handoff
```

`search_slots` requires non-empty `service_id`, `date_from` and `date_to`; `select_slot` requires `slot_id`; `confirm` requires a stored selected slot. The controller constructs a context with configured patient ID, authorization, generated request ID and language `zh-TW`. It creates an idempotency key only for the create step. It records `{step_id, displayed_data, decision, confirmed_at}` in `confirmation_record` before invoking `medical.create_appointment`, and passes only the documented fields `patient_id`, `service_id`, `slot_id`, optional `referring_appointment_id`, `administrative_note` and `consent: true` to the adapter.

Normalize result envelopes defensively: accept `data` as list or object, extract task ID from either `data.task_id` or `task.id`, and convert missing required result data into a safe `BACKEND_INVALID_RESPONSE` error response.

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest middleware.tests.test_controller -v`

Expected: all intent, state transition and confirmation-gate tests PASS.

- [x] **Step 5: Commit**

```bash
git add middleware/controller.py middleware/tests/test_controller.py
git commit -m "feat: add deterministic Ponte interaction controller"
```

### Task 4: Expose the middleware HTTP bridge

**Files:**
- Create: `middleware/server.py`
- Create: `middleware/tests/test_server.py`

**Interfaces:**
- Produces `create_application(backend_url: str, patient_id: str, authorization: str) -> MiddlewareApplication`.
- Produces `create_http_server(host: str, port: int, application: MiddlewareApplication) -> ThreadingHTTPServer`.
- Provides `GET /api/health`, `GET /api/mcp/tools`, `POST /api/mcp/tools/call`, `POST /api/interactions/message` and `POST /api/interactions/action`.
- Provides `main()` for `python3 -m middleware.server --host 127.0.0.1 --port 8090`.

- [ ] **Step 1: Write the failing tests**

```python
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from middleware.server import create_application, create_http_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = create_application("http://backend.test", "PAT-DEMO-001", "Bearer mock-user-token")
        cls.server = create_http_server("127.0.0.1", 0, cls.application)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            return response.status, json.loads(response.read())

    def test_tools_endpoint_returns_registry(self):
        status, payload = self.request("GET", "/api/mcp/tools")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["tools"]), 21)

    def test_malformed_json_is_safe_client_error(self):
        request = Request(self.base_url + "/api/interactions/message", data=b"{", method="POST", headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 400)
        error_body = json.loads(raised.exception.read())
        self.assertNotIn("traceback", json.dumps(error_body).lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest middleware.tests.test_server -v`

Expected: FAIL because the HTTP application and routes are not implemented.

- [ ] **Step 3: Implement route handling and CORS**

Build a `MiddlewareApplication` with one shared registry, `RestAdapter.from_environment`-compatible base URL, `ExecutionPipeline([DirectMcpExecutionStage(...)])`, `SessionStore` and `InteractionController`.

Return these exact response shapes:

```json
GET /api/health
{
  "status": "ok",
  "backend_url": "http://127.0.0.1:8080",
  "tool_count": 21,
  "backend_reachable": true
}
```

```json
POST /api/mcp/tools/call
{
  "name": "medical.list_departments",
  "arguments": {"context": {"authorization": "Bearer mock-user-token"}, "input": {}}
}
```

For `/api/health`, perform a lightweight `medical.list_departments` call with the configured authorization context; return HTTP 200 with `backend_reachable: false` when the bridge is running but backend connection fails. For `/api/mcp/tools/call`, require a known string tool name and object `arguments`, look up the fixed registry, and return HTTP 200 for adapter results including `ok: false`, or HTTP 400 for invalid input. Never let the client supply backend headers.

Use HTTP 400 for malformed JSON, missing required fields and invalid actions; HTTP 404 for unknown paths; HTTP 405 for unsupported methods. Add `Access-Control-Allow-Origin` from the configured allowlist, `Access-Control-Allow-Headers: Content-Type`, and an `OPTIONS` response so the separate static frontend can call the bridge.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest middleware.tests.test_server -v`

Expected: all bridge routing, JSON error and catalog tests PASS.

- [ ] **Step 5: Commit**

```bash
git add middleware/server.py middleware/tests/test_server.py
git commit -m "feat: expose Ponte middleware HTTP bridge"
```

### Task 5: Prove the middleware reaches the real mock backend

**Files:**
- Create: `tests/test_middleware_integration.py`
- Modify: `middleware/server.py` only if the integration test identifies a contract mismatch.

**Interfaces:**
- Consumes the existing `mock_backends.server.create_http_server` and `middleware.server.create_http_server` helpers.
- Verifies the public HTTP contracts without replacing the existing MCP registry or backend fixtures.

- [ ] **Step 1: Write the failing end-to-end test**

```python
def post_json(url, body):
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request) as response:
        return json.loads(response.read())


class MiddlewareBackendIntegrationTests(unittest.TestCase):
    def test_message_to_medical_tool_reaches_mock_backend(self):
        backend = create_http_server("127.0.0.1", 0, self.data_dir)
        backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
        backend_thread.start()
        middleware = create_http_server(
            "127.0.0.1", 0,
            create_application(
                f"http://127.0.0.1:{backend.server_port}",
                "PAT-DEMO-001",
                "Bearer mock-user-token",
            ),
        )
        middleware_thread = threading.Thread(target=middleware.serve_forever, daemon=True)
        middleware_thread.start()
        try:
            response = post_json(
                f"http://127.0.0.1:{middleware.server_port}/api/interactions/message",
                {"session_id": "S-1", "message": "我想查詢醫療預約", "source": "text"},
            )
            self.assertEqual(response["session_id"], "S-1")
            self.assertEqual(response["task_state"], "selecting_service")
            self.assertTrue(response["tool_events"])
            self.assertEqual(response["tool_events"][0]["tool_name"], "medical.get_my_appointments")
        finally:
            middleware.shutdown()
            backend.shutdown()
            middleware.server_close()
            backend.server_close()
```

Use `tempfile.TemporaryDirectory()` for backend data and actual ephemeral ports. The test must not call external network services.

- [ ] **Step 2: Run the integration test and confirm it fails before the bridge is complete**

Run: `python3 -m unittest tests.test_middleware_integration -v`

Expected before implementation: FAIL because the middleware HTTP bridge does not yet exist.

- [ ] **Step 3: Add the real backend assertions**

After the message query passes, send `search_slots`, `select_slot`, `confirm` actions using service and slot IDs returned by the backend. Assert that the final `tool_events` include `medical.create_appointment` and `medical.get_task_status`, that the create event contains `consent: true`, and that a confirmation-free action sequence never produces a create event.

Also call `/api/mcp/tools/call` directly with `medical.list_departments` and assert the response contains the mock department data. Use an invalid tool name and assert HTTP 400 with a stable safe error code.

- [ ] **Step 4: Run the integration test to verify it passes**

Run: `python3 -m unittest tests.test_middleware_integration -v`

Expected: all middleware-to-backend assertions PASS with no dependency on a pre-running server.

- [ ] **Step 5: Run the complete Python test suite**

Run: `python3 -m unittest discover -v`

Expected: existing MCP and mock-backend tests plus middleware tests PASS; no tests rely on network access outside the temporary local servers.

- [ ] **Step 6: Commit**

```bash
git add tests/test_middleware_integration.py middleware/server.py
git commit -m "test: verify middleware reaches mock medical backend"
```

### Task 6: Document middleware startup and contract verification

**Files:**
- Create: `middleware/README.md`

**Interfaces:**
- Documents `python3 -m middleware.server --host 127.0.0.1 --port 8090`.
- Documents `PONTE_BACKEND_URL`, `PONTE_FRONTEND_ORIGINS`, `PONTE_PATIENT_ID` and `PONTE_AUTHORIZATION`.
- Documents the JSON bodies for `/api/interactions/message`, `/api/interactions/action` and `/api/mcp/tools/call`.

- [ ] **Step 1: Write the runbook**

Include the exact local sequence:

```bash
python3 -m mock_backends.server --host 127.0.0.1 --port 8080 --data-dir /tmp/ponte-mock-data
PONTE_BACKEND_URL=http://127.0.0.1:8080 python3 -m middleware.server --host 127.0.0.1 --port 8090
curl http://127.0.0.1:8090/api/health
```

Explain that `backend_reachable` is checked through the medical catalog call, that the session store is in memory, and that formal creation requires an explicit middleware action `confirm`.

- [ ] **Step 2: Verify the documented commands against the implementation**

Run the two servers with temporary data, call `/api/health`, `/api/mcp/tools`, and one `/api/interactions/message`, then stop both processes and confirm no repository data directory was created.

- [ ] **Step 3: Commit**

```bash
git add middleware/README.md
git commit -m "docs: document Ponte middleware bridge"
```

## Plan self-review checklist

- Every design requirement is covered by Tasks 1–6: middleware boundary, direct MCP path, future pipeline stage, medical tool chain, confirmation gate, safe errors, CORS and real-backend verification.
- No task changes `MCP/registry.py` or renames the existing tool contract.
- The names `ToolCall`, `ToolExecutionResult`, `ExecutionStage.handle`, `ExecutionPipeline.dispatch`, `InteractionController.handle_message` and `InteractionController.handle_action` remain consistent across tasks.
- The plan does not implement or imply `medical.reschedule_appointment`; it uses the existing appointment contract and leaves reschedule as a later tool/workflow addition.
