# Ponte MCP／工具轉接層實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `./MCP` 建立一個以 Python 標準庫實作的 stdio MCP server，把 `docs/api/` 的一戶通、長者文娛活動及醫療 REST API 暴露為 21 個固定工具，並以本地 fixture backend 驗證連通性與可用性。

**Architecture:** MCP server 讀取 newline-delimited JSON-RPC，使用固定 registry 將 tool call 映射成受控 REST request，再由 `PONTE_BACKEND_URL` 指向正在開發中的 backend。context metadata 只轉換成 API 文件允許的 headers，backend 回應與錯誤則轉換成 MCP tool result；不加入 Workflow、policy、持久化或任意 REST proxy。

**Tech Stack:** Python 3.13+、Python 標準庫（`dataclasses`、`json`、`urllib.request`、`unittest`、`http.server`、`subprocess`）；stdio JSON-RPC/MCP；HTTP JSON REST。

## Global Constraints

- 所有 MCP runtime 程式碼必須位於 `MCP/`；不修改或移動 backend 的 `mock_backends/`、`tests/` 及其未追蹤變更。
- backend contract 只取自 `docs/api/one-account-api.md`、`docs/api/elderly-cultural-activities-api.md` 及 `docs/api/jinghu-medical-mock-api.md`。
- catalog 必須固定包含 21 個工具：一戶通 5 個、長者文娛活動 6 個、醫療 10 個；不加入沒有 `docs/api/` contract 的 social-welfare 或 notification 工具。
- Python runtime 只可使用標準庫，不新增 pip、npm 或其他外部 dependency。
- backend base URL 由 `PONTE_BACKEND_URL` 提供，預設為 `http://127.0.0.1:8080`；registry 才能決定 path 和 HTTP method。
- MCP stdout 只能輸出 JSON-RPC response；診斷 logging 必須寫 stderr。
- 工具輸入使用 `{ "context": {}, "input": {} }` envelope；`input` 內的 backend 欄位名稱和 enum 值必須保持與 API 文件一致。
- POST 工具必須要求 `context.idempotency_key`；醫療工具必須要求 `context.authorization`；需要個人資料或建立資源時依 API contract 要求 `context.patient_id` 或 `context.mock_user_id`。
- `confirmation`、`consent` 只由 Workflow 放進 `input`，adapter 原樣轉送，不自行建立、判定或繞過。
- 不接受 client 傳入任意 URL、HTTP method、任意 header 或本地檔案路徑。
- 維持已批准設計中的 compatibility handshake：支援 `initialize`、`notifications/initialized`、`tools/list`、`tools/call`，protocol version 常數使用 `2025-03-26`；不實作 durable task、session store 或未在本計畫中的 MCP extension。

---

### Task 1: 建立共用資料模型與錯誤邊界

**Files:**
- Create: `MCP/__init__.py`
- Create: `MCP/models.py`
- Create: `MCP/errors.py`
- Test: `MCP/tests/__init__.py`
- Test: `MCP/tests/test_models.py`

**Interfaces:**
- Produces `ToolContext.from_arguments(arguments: Mapping[str, Any]) -> ToolContext`。
- Produces `ContextRequirements`，描述 `mock_user_id`、`patient_id`、`authorization`、`idempotency_key` 及可選的 `accept_language`。
- Produces `RestRequest(method: str, path: str, query: Mapping[str, str], body: Mapping[str, Any] | None, headers: Mapping[str, str])`。
- Produces `AdapterError(code: str, message: str, status: int | None, details: Any, retryable: bool)` 及 `InvalidToolArguments`、`BackendUnavailable`、`BackendTimeout`、`BackendInvalidResponse` 子類。

- [x] **Step 1: 寫 failing tests**

```python
# MCP/tests/test_models.py
import unittest

from MCP.errors import InvalidToolArguments
from MCP.models import ContextRequirements, ToolContext


class ToolContextTests(unittest.TestCase):
    def test_builds_allowlisted_headers_for_medical_post(self):
        context = ToolContext.from_arguments({
            "context": {
                "authorization": "Bearer mock-user-token",
                "patient_id": "P-10001",
                "request_id": "REQ-1",
                "idempotency_key": "KEY-1",
                "accept_language": "zh-TW",
            },
            "input": {},
        })
        headers = context.to_headers(
            ContextRequirements(
                authorization=True,
                patient_id=True,
                idempotency_key=True,
                request_id=True,
                accept_language=True,
            ),
            method="POST",
        )
        self.assertEqual(headers["Authorization"], "Bearer mock-user-token")
        self.assertEqual(headers["X-Patient-Id"], "P-10001")
        self.assertEqual(headers["Idempotency-Key"], "KEY-1")
        self.assertEqual(headers["Accept-Language"], "zh-TW")
        self.assertNotIn("context", headers)

    def test_rejects_post_without_idempotency_key(self):
        context = ToolContext.from_arguments({"context": {}, "input": {}})
        with self.assertRaises(InvalidToolArguments):
            context.to_headers(
                ContextRequirements(idempotency_key=True), method="POST"
            )


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: 執行測試確認失敗**

Run: `python3 -m unittest MCP.tests.test_models -v`

Expected: FAIL，因為 `MCP.models`、`MCP.errors` 及上述 classes 尚未存在。

- [x] **Step 3: 寫最小實作**

在 `MCP/models.py` 實作 frozen dataclasses。`ToolContext.from_arguments` 必須拒絕非 object 的 arguments、缺少 `context` 或 `input`、非 object 的 context/input，以及未知 context keys；`to_headers` 只輸出 API 文件允許的 header，`accept_language` 缺省為 `zh-TW`，POST 的 `Idempotency-Key` 由 requirement 強制。`MCP/errors.py` 的 `AdapterError` 保存 code、status、details、retryable，並提供 `to_dict()` 返回這四個欄位及 message。

```python
# MCP/models.py 的核心介面
@dataclass(frozen=True)
class ContextRequirements:
    mock_user_id: bool = False
    patient_id: bool = False
    authorization: bool = False
    idempotency_key: bool = False
    request_id: bool = False
    accept_language: bool = False


@dataclass(frozen=True)
class RestRequest:
    method: str
    path: str
    query: Mapping[str, str]
    body: Mapping[str, Any] | None
    headers: Mapping[str, str]
```

- [x] **Step 4: 執行測試確認通過**

Run: `python3 -m unittest MCP.tests.test_models -v`

Expected: 2 tests PASS。

- [x] **Step 5: Commit**

```bash
git add MCP/__init__.py MCP/models.py MCP/errors.py MCP/tests/__init__.py MCP/tests/test_models.py
git commit -m "feat: add MCP adapter contracts"
```

### Task 2: 建立固定工具 registry 與 JSON schema

**Files:**
- Create: `MCP/registry.py`
- Test: `MCP/tests/test_registry.py`

**Interfaces:**
- Produces `ToolDefinition`，欄位包括 `name`、`description`、`method`、`path_template`、`input_schema`、`risk_level`、`context_requirements`、`query_fields`、`body_mode` 及 optional route variants。
- Produces `ToolRegistry.get(name: str) -> ToolDefinition`、`ToolRegistry.list_mcp_tools() -> list[dict[str, Any]]` 及 `ToolRegistry.names() -> tuple[str, ...]`。
- Produces `build_registry() -> ToolRegistry`，返回固定 21-tool catalog。

- [ ] **Step 1: 寫 failing tests**

```python
# MCP/tests/test_registry.py
import unittest

from MCP.registry import build_registry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()

    def test_catalog_has_exactly_21_documented_tools(self):
        self.assertEqual(len(self.registry.names()), 21)
        self.assertNotIn("social_welfare.search_services", self.registry.names())
        self.assertNotIn("notification.send_reminder", self.registry.names())

    def test_medical_create_registration_is_post_and_requires_context(self):
        definition = self.registry.get("medical.create_registration")
        self.assertEqual(definition.method, "POST")
        self.assertEqual(definition.path_template, "/mock/medical/v1/registrations")
        self.assertTrue(definition.context_requirements.authorization)
        self.assertTrue(definition.context_requirements.patient_id)
        self.assertTrue(definition.context_requirements.idempotency_key)

    def test_activity_status_has_explicit_route_selector(self):
        definition = self.registry.get("one_account.get_activity_registration_status")
        self.assertEqual(definition.method, "GET")
        self.assertEqual(set(definition.route_variants), {"registration", "phone_assistance"})

    def test_tools_list_has_input_schema(self):
        for tool in self.registry.list_mcp_tools():
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertEqual(set(tool["inputSchema"]["required"]), {"context", "input"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python3 -m unittest MCP.tests.test_registry -v`

Expected: FAIL，因為 `build_registry` 尚未存在。

- [ ] **Step 3: 寫最小實作**

在 `MCP/registry.py` 宣告固定工具資料，不用反射或從 client 載入設定。catalog 必須逐項包含以下 path：

```text
one_account.submit_pension_application                         POST /mock/one-account/pension/applications
one_account.get_cash_sharing_plan                              GET  /mock/one-account/cash-sharing-plan
one_account.book_government_service_center_queue               POST /mock/one-account/queue-tickets/government-service-center
one_account.book_identification_services_bureau_queue          POST /mock/one-account/queue-tickets/identification-services-bureau
one_account.list_my_queue_tickets                               GET  /mock/one-account/my/queue-tickets
one_account.search_elderly_activities                           GET  /mock/elderly-activities/v1/activities
one_account.get_elderly_activity                                GET  /mock/elderly-activities/v1/activities/{activityId}
one_account.get_activity_registration_form                     GET  /mock/elderly-activities/v1/activities/{activityId}/registration-form
one_account.submit_activity_registration                       POST /mock/elderly-activities/v1/registrations
one_account.start_phone_registration_assistance                POST /mock/elderly-activities/v1/phone-registration-assists
one_account.get_activity_registration_status                   GET  /mock/elderly-activities/v1/registrations/{registrationId} 或 /phone-registration-assists/{assistanceId}
medical.list_departments                                       GET  /mock/medical/v1/departments
medical.list_department_doctors                                GET  /mock/medical/v1/departments/{departmentId}/doctors
medical.search_registration_slots                              GET  /mock/medical/v1/registration-slots
medical.create_registration                                   POST /mock/medical/v1/registrations
medical.list_appointment_services                              GET  /mock/medical/v1/appointment-services
medical.search_appointment_slots                              GET  /mock/medical/v1/appointment-slots
medical.create_appointment                                    POST /mock/medical/v1/appointments
medical.get_my_appointments                                   GET  /mock/medical/v1/appointments
medical.get_appointment                                        GET  /mock/medical/v1/appointments/{appointmentId}
medical.get_task_status                                       GET  /mock/medical/v1/tasks/{taskId}
```

每項 schema 的 `input` properties 必須依對應 API 文件建立：GET 搜尋工具列出文件中的 query 欄位；path 工具列出 path ID；POST 工具將文件的 request body 欄位放入 object schema 並在 dispatch 時原樣送出。長者活動 status tool 要求 `resource_type` 為 `registration` 或 `phone_assistance`，並依 `registration_id` 或 `assistance_id` 選擇固定 route。每個 root schema 都使用 `context` 與 `input` required，context schema 只允許 `mock_user_id`、`patient_id`、`authorization`、`accept_language`、`request_id`、`idempotency_key`。

- [ ] **Step 4: 執行測試確認通過**

Run: `python3 -m unittest MCP.tests.test_registry -v`

Expected: 4 tests PASS，且 catalog 數量為 21。

- [ ] **Step 5: Commit**

```bash
git add MCP/registry.py MCP/tests/test_registry.py
git commit -m "feat: register documented Ponte MCP tools"
```

### Task 3: 實作受控 REST adapter

**Files:**
- Modify: `MCP/models.py`
- Modify: `MCP/errors.py`
- Create: `MCP/rest_adapter.py`
- Test: `MCP/tests/test_rest_adapter.py`

**Interfaces:**
- Produces `HttpResponse(status: int, headers: Mapping[str, str], body: Any)`。
- Produces `HttpTransport.request(request: RestRequest, timeout: float) -> HttpResponse`。
- Produces `UrllibTransport`，使用 `urllib.request`，只接受 `RestRequest`。
- Produces `RestAdapter(base_url: str, transport: HttpTransport, timeout: float = 10.0)` 及 `RestAdapter.invoke(definition: ToolDefinition, arguments: Mapping[str, Any]) -> dict[str, Any]`。

- [ ] **Step 1: 寫 failing tests**

```python
# MCP/tests/test_rest_adapter.py
import unittest

from MCP.registry import build_registry
from MCP.rest_adapter import HttpResponse, RestAdapter


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def request(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


class RestAdapterTests(unittest.TestCase):
    def test_maps_medical_get_to_query_and_headers(self):
        transport = RecordingTransport(HttpResponse(200, {}, {"data": {"departments": []}}))
        adapter = RestAdapter("http://backend.test", transport)
        definition = build_registry().get("medical.search_registration_slots")

        result = adapter.invoke(definition, {
            "context": {
                "authorization": "Bearer mock-user-token",
                "patient_id": "P-10001",
                "request_id": "REQ-1",
            },
            "input": {
                "department_id": "CARDIO",
                "date_from": "2026-08-10",
            },
        })

        request, _ = transport.requests[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.path, "/mock/medical/v1/registration-slots")
        self.assertEqual(request.query["department_id"], "CARDIO")
        self.assertEqual(request.headers["Authorization"], "Bearer mock-user-token")
        self.assertEqual(result["data"], {"departments": []})

    def test_maps_activity_post_body_without_context(self):
        transport = RecordingTransport(HttpResponse(201, {}, {"data": {"registration": {"registration_id": "REG-1"}}}))
        adapter = RestAdapter("http://backend.test/", transport)
        definition = build_registry().get("one_account.submit_activity_registration")

        adapter.invoke(definition, {
            "context": {
                "mock_user_id": "USR-DEMO-001",
                "request_id": "REQ-2",
                "idempotency_key": "KEY-2",
            },
            "input": {"activity_id": "ACT-1", "form_id": "FORM-1", "confirmation": {"confirmed": True}},
        })

        request, _ = transport.requests[0]
        self.assertEqual(request.headers["X-Mock-User-Id"], "USR-DEMO-001")
        self.assertEqual(request.headers["Idempotency-Key"], "KEY-2")
        self.assertEqual(request.body["activity_id"], "ACT-1")
        self.assertNotIn("context", request.body)

    def test_converts_backend_error_to_adapter_error(self):
        transport = RecordingTransport(HttpResponse(409, {}, {
            "error": {"code": "SLOT_NOT_AVAILABLE", "message": "所選時段已滿", "retryable": False}
        }))
        adapter = RestAdapter("http://backend.test", transport)
        with self.assertRaisesRegex(Exception, "SLOT_NOT_AVAILABLE"):
            adapter.invoke(build_registry().get("medical.create_registration"), {
                "context": {
                    "authorization": "Bearer mock-user-token",
                    "patient_id": "P-10001",
                    "idempotency_key": "KEY-3",
                },
                "input": {"slot_id": "SLOT-1", "consent": True},
            })


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python3 -m unittest MCP.tests.test_rest_adapter -v`

Expected: FAIL，因為 `MCP.rest_adapter` 尚未存在。

- [ ] **Step 3: 寫最小實作**

`RestAdapter.invoke` 必須先用 `ToolContext.from_arguments` 驗證 envelope，再由 `ToolDefinition` 產生 path、query、body 和 headers。query 只取 definition 的 `query_fields`；list/boolean 使用 API 文件的逗號分隔／`true`、`false` 格式；path ID 使用 `urllib.parse.quote(..., safe="")`。POST body 必須等於 `arguments["input"]`，不得把 context 混入 body。base URL 只能來自 constructor 或 `PONTE_BACKEND_URL`，以 `base_url.rstrip("/") + path` 組合。

`UrllibTransport` 必須設定 `Accept: application/json`，POST 設定 `Content-Type: application/json`，以 `HTTPError` 讀取 backend error body；connection refused 映射 `BACKEND_UNAVAILABLE`，socket timeout 映射 `BACKEND_TIMEOUT`，非 JSON success body 映射 `BACKEND_INVALID_RESPONSE`。HTTP 4xx/5xx 仍保留 status、後端 error code、message、details 和 retryable。

- [ ] **Step 4: 執行測試確認通過**

Run: `python3 -m unittest MCP.tests.test_rest_adapter -v`

Expected: 3 tests PASS，且測試不會發出真實網絡請求。

- [ ] **Step 5: Commit**

```bash
git add MCP/models.py MCP/errors.py MCP/rest_adapter.py MCP/tests/test_rest_adapter.py
git commit -m "feat: add documented REST tool adapter"
```

### Task 4: 實作 stdio MCP JSON-RPC server

**Files:**
- Create: `MCP/server.py`
- Modify: `MCP/__main__.py`
- Test: `MCP/tests/test_server.py`

**Interfaces:**
- Produces `MCPServer(registry: ToolRegistry, adapter: RestAdapter, server_name: str = "ponte-mcp-adapter", server_version: str = "0.1.0")`。
- Produces `MCPServer.handle(message: Mapping[str, Any]) -> dict[str, Any] | None`。
- Produces `MCPServer.run(stdin: TextIO, stdout: TextIO) -> None`，一行處理一個 JSON-RPC message。
- `python -m MCP` 從環境變數建立 `build_registry()`、`RestAdapter.from_environment()` 和 `MCPServer`，讀 stdin、寫 stdout。

- [ ] **Step 1: 寫 failing tests**

```python
# MCP/tests/test_server.py
import io
import json
import unittest

from MCP.registry import build_registry
from MCP.server import MCPServer


class NoopAdapter:
    def invoke(self, definition, arguments):
        return {"request_id": "REQ-1", "data": {"ok": True, "tool": definition.name}}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer(build_registry(), NoopAdapter())

    def test_initialize_returns_capabilities(self):
        result = self.server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1"}},
        })
        self.assertEqual(result["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", result["result"]["capabilities"])

    def test_tools_list_returns_21_tools(self):
        result = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(result["result"]["tools"]), 21)

    def test_tools_call_returns_structured_content(self):
        result = self.server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "medical.list_departments", "arguments": {"context": {}, "input": {}}},
        })
        self.assertFalse(result["result"].get("isError", False))
        self.assertEqual(result["result"]["structuredContent"]["data"]["ok"], True)

    def test_initialized_notification_has_no_response(self):
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python3 -m unittest MCP.tests.test_server -v`

Expected: FAIL，因為 `MCP.server` 和 `MCP.__main__` 尚未存在。

- [ ] **Step 3: 寫最小實作**

`handle` 必須返回標準 JSON-RPC 2.0 response。`initialize` 返回 protocol version `2025-03-26`、serverInfo 和 `capabilities.tools.listChanged=false`；`notifications/initialized` 返回 `None`。`tools/list` 返回 `{"tools": registry.list_mcp_tools()}`。`tools/call` 以 `params.name` 查 registry 並呼叫 adapter；成功結果包含 `content` 的 `text` item 和 `structuredContent`，adapter/backend error 結果包含 `content`、`structuredContent.error` 及 `isError: true`。未知 method 使用 `-32601`，缺少或錯誤的 params 使用 `-32602`，不把 Python traceback 放進 response。

`run` 必須逐行 `json.loads`，忽略空白行；解析錯誤寫 JSON-RPC `-32700` response；request 沒有 `id` 時視為 notification，不輸出 response。stdout 每行只輸出一個 JSON object，使用 `ensure_ascii=False`；stderr 可輸出錯誤診斷。

- [ ] **Step 4: 執行測試確認通過**

Run: `python3 -m unittest MCP.tests.test_server -v`

Expected: 4 tests PASS。

- [ ] **Step 5: Commit**

```bash
git add MCP/server.py MCP/__main__.py MCP/tests/test_server.py
git commit -m "feat: expose Ponte tools over MCP stdio"
```

### Task 5: 建立 fixture backend 並完成端到端連通性測試

**Files:**
- Create: `MCP/tests/fixture_backend.py`
- Create: `MCP/tests/test_smoke.py`

**Interfaces:**
- Produces `FixtureBackend` context manager，提供 `base_url`、`requests` 及可關閉的 `ThreadingHTTPServer`。
- Produces `FixtureBackend` 對文件中的 GET/POST path 返回可解析的 `request_id`／`data` success envelope，並能用指定 path 返回 `409` error envelope。
- Produces subprocess smoke test，證明 MCP stdio → REST adapter → fixture HTTP backend → MCP response 的完整鏈路。

- [ ] **Step 1: 寫 failing smoke test**

```python
# MCP/tests/test_smoke.py
import json
import os
import subprocess
import sys
import unittest

from MCP.tests.fixture_backend import FixtureBackend


class MCPStdioSmokeTests(unittest.TestCase):
    def test_initialize_list_and_post_tool_reach_backend(self):
        with FixtureBackend() as backend:
            env = os.environ.copy()
            env["PONTE_BACKEND_URL"] = backend.base_url
            process = subprocess.Popen(
                [sys.executable, "-m", "MCP"],
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                def call(message):
                    process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                    process.stdin.flush()
                    return json.loads(process.stdout.readline())

                initialize = call({
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                               "clientInfo": {"name": "smoke", "version": "1"}},
                })
                self.assertEqual(initialize["result"]["serverInfo"]["name"], "ponte-mcp-adapter")

                listed = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                self.assertEqual(len(listed["result"]["tools"]), 21)

                called = call({
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {
                        "name": "one_account.submit_activity_registration",
                        "arguments": {
                            "context": {
                                "mock_user_id": "USR-DEMO-001",
                                "request_id": "REQ-SMOKE-1",
                                "idempotency_key": "KEY-SMOKE-1",
                            },
                            "input": {"activity_id": "ACT-1", "form_id": "FORM-1"},
                        },
                    },
                })
                self.assertFalse(called["result"]["isError"])
                request = backend.requests[-1]
                self.assertEqual(request["method"], "POST")
                self.assertEqual(request["path"], "/mock/elderly-activities/v1/registrations")
                self.assertEqual(request["headers"]["X-Mock-User-Id"], "USR-DEMO-001")
                self.assertEqual(request["headers"]["Idempotency-Key"], "KEY-SMOKE-1")
                self.assertEqual(request["body"]["activity_id"], "ACT-1")
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python3 -m unittest MCP.tests.test_smoke -v`

Expected: FAIL，因為 fixture backend 和 MCP subprocess 尚未存在。

- [ ] **Step 3: 寫 fixture 與補齊錯誤案例**

以 `ThreadingHTTPServer` 綁定 `127.0.0.1` 的 ephemeral port。handler 將每個 request 記錄為 method、path、query、headers、JSON body；對 `GET /mock/medical/v1/departments` 返回 `200`，對上述活動 POST 返回 `201`，對 `POST /mock/medical/v1/registrations` 且 body 的 `slot_id` 為 `SLOT-CONFLICT` 返回 `409`，其他文件 path 返回 `200` 空 data。另加測試：backend 返回 409 時 MCP result 為 `isError=true` 且保留 `SLOT_NOT_AVAILABLE`，停止 fixture backend 後 call 返回 `BACKEND_UNAVAILABLE`，REST transport 收到非 object JSON 時返回 `BACKEND_INVALID_RESPONSE`。

- [ ] **Step 4: 執行完整測試確認通過**

Run: `python3 -m unittest discover -s MCP/tests -v`

Expected: 所有 model、registry、REST adapter、server 及 smoke tests PASS，且 subprocess 在測試結束後已關閉。

- [ ] **Step 5: Commit**

```bash
git add MCP/tests/fixture_backend.py MCP/tests/test_smoke.py
git commit -m "test: verify MCP backend connectivity"
```

### Task 6: 撰寫 MCP 使用說明並完成交付前驗證

**Files:**
- Create: `MCP/README.md`
- Verify: `docs/PonteArch.md`
- Verify: `docs/api/one-account-api.md`
- Verify: `docs/api/elderly-cultural-activities-api.md`
- Verify: `docs/api/jinghu-medical-mock-api.md`

**Interfaces:**
- Produces 一份繁體中文 README，說明安裝前提、啟動命令、`PONTE_BACKEND_URL`、context envelope、21 個工具範圍、POST idempotency、醫療 authorization，以及 backend 尚未啟動時的錯誤。
- Produces 可重現的驗證命令和結果摘要，不宣稱未啟動的真實 backend 已連通。

- [ ] **Step 1: 寫 README 驗收檢查**

```bash
rg -n "python3 -m MCP|PONTE_BACKEND_URL|context|idempotency_key|authorization|21|tools/list|tools/call" MCP/README.md
```

Expected: 每個 pattern 至少有一個匹配；README 不含 `TBD`、`TODO` 或未完成句子。

- [ ] **Step 2: 寫 README**

README 必須包含：

```text
PONTE_BACKEND_URL=http://127.0.0.1:8080 python3 -m MCP
python3 -m unittest discover -s MCP/tests -v
python3 -m compileall -q MCP
```

並提供一個 `tools/call` 的 JSON 範例，清楚區分 `context` header metadata 與 `input` backend body；列出不支援 social-welfare、notification 及任意 REST proxy 的原因。

- [ ] **Step 3: 執行交付前完整驗證**

Run:

```bash
python3 -m unittest discover -s MCP/tests -v
python3 -m compileall -q MCP
git diff --check
rg -n "TBD|TODO|待補|待定|PLACEHOLDER|FIXME" MCP docs/superpowers/specs/2026-08-03-mcp-tool-adapter-layer-design.md || true
```

Expected: unittest exit code 0、compileall exit code 0、`git diff --check` 無輸出、placeholder search 無輸出。最後查看 `git status --short`，確認本計畫新增／修改範圍只在 `MCP/`、本 README 及本 plan；backend 相關未追蹤變更保持不動。

- [ ] **Step 4: Commit**

```bash
git add MCP/README.md docs/superpowers/plans/2026-08-03-mcp-tool-adapter-layer.md
git commit -m "docs: add MCP adapter usage plan"
```
