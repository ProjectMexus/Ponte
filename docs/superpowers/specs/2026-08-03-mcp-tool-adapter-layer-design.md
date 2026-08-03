# Ponte MCP / Tool Adapter Layer 設計說明

## 目標

在 `./MCP` 建立一個可由 MCP client 透過 `stdio` 啟動的 Tool Adapter Layer，將 `docs/api/` 已定義的 mock backend REST API 暴露為固定、可檢查及可測試的 MCP tools。

本層只負責 MCP protocol、tool schema、輸入驗證、REST request mapping、context header 傳遞及錯誤轉換；不負責 Workflow 順序、風險判斷、身份驗證、長期 task state、人工接管或 Action Receipt。

## Contract 來源與範圍

唯一的 backend contract 來源是以下文件：

- `docs/api/one-account-api.md`
- `docs/api/elderly-cultural-activities-api.md`
- `docs/api/jinghu-medical-mock-api.md`

`docs/PonteArch.md` 只用於確定 MCP 的架構邊界、Workflow-first 原則及 tool 命名方向。由於 `docs/api/` 沒有社會福利或 notification 的 HTTP contract，本版本不猜測或暴露這兩類 tools。

預設 catalog 包含：

| Domain | Tools | 來源 |
| --- | ---: | --- |
| `one_account` | 5 | 一戶通 API |
| `one_account` elderly activities | 6 | 長者文娛活動 API |
| `medical` | 10 | 鏡湖通醫療 API |

實際 tool 名稱、HTTP method、path、query/body 欄位和風險 metadata 必須由 registry 明確列出，不接受 client 傳入任意 URL、method 或 header。

## 架構

```text
MCP client
    │ stdio JSON-RPC
    ▼
MCP server (`python -m MCP`)
    │
    ├── protocol lifecycle and tool dispatch
    ├── fixed tool registry and JSON schemas
    ├── context/header validation
    └── MCP-safe error conversion
    │ typed REST request
    ▼
REST adapter (`PONTE_BACKEND_URL`)
    │ HTTP JSON
    ▼
Ponte mock backend defined by docs/api/
```

### MCP server

`MCP/server.py` 讀取 stdin 的 newline-delimited JSON-RPC messages，向 stdout 寫回 MCP responses；logging 只能寫 stderr，避免污染 stdio protocol。至少支援：

- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call`

`MCP/__main__.py` 提供 `python -m MCP` 啟動入口。server 不保存跨 request 的業務狀態。

### Tool registry

`MCP/registry.py` 保存固定的 `ToolDefinition`，每項定義包含：

- MCP tool name、description 及 `inputSchema`；
- domain、risk metadata 和所需 context；
- HTTP method、path template、query/body mapping；
- 是否要求 `X-Mock-User-Id`、`X-Patient-Id`、`Idempotency-Key`。

registry 提供 `tools/list` 所需的 JSON schema，也提供 `tools/call` 的 dispatch metadata，確保宣告與執行使用同一份 contract。

### REST adapter

`MCP/rest_adapter.py` 使用 Python 標準庫 HTTP client，從 `PONTE_BACKEND_URL` 讀取 backend base URL，預設值為 `http://127.0.0.1:8080`。它只接受 registry 產生的 request，負責：

1. 組合固定 path 與 query；
2. 編碼 JSON request body；
3. 傳遞文件指定的 context headers；
4. 解析 JSON response；
5. 將 HTTP status、timeout、connection failure 和 invalid JSON 轉為 adapter errors。

所有 POST tool 都要求 `context.idempotency_key`；醫療 tool 都要求 `context.authorization`，並在 API 文件要求時以 `context.patient_id` 映射到 `X-Patient-Id`。`context.accept_language` 可選，預設由 adapter 使用 `zh-TW`，並映射到醫療 API 的 `Accept-Language`。一戶通和長者活動 API 所需的 user context 依文件映射到 `X-Mock-User-Id`。不允許 client 覆寫 `Host`、`Content-Length` 或傳入未列入 allowlist 的 header。

## Tool contract

### 一戶通 tools

- `one_account.submit_pension_application` → `POST /mock/one-account/pension/applications`
- `one_account.get_cash_sharing_plan` → `GET /mock/one-account/cash-sharing-plan`
- `one_account.book_government_service_center_queue` → `POST /mock/one-account/queue-tickets/government-service-center`
- `one_account.book_identification_services_bureau_queue` → `POST /mock/one-account/queue-tickets/identification-services-bureau`
- `one_account.list_my_queue_tickets` → `GET /mock/one-account/my/queue-tickets`

### 長者文娛活動 tools

- `one_account.search_elderly_activities` → `GET /mock/elderly-activities/v1/activities`
- `one_account.get_elderly_activity` → `GET /mock/elderly-activities/v1/activities/{activityId}`
- `one_account.get_activity_registration_form` → `GET /mock/elderly-activities/v1/activities/{activityId}/registration-form`
- `one_account.submit_activity_registration` → `POST /mock/elderly-activities/v1/registrations`
- `one_account.start_phone_registration_assistance` → `POST /mock/elderly-activities/v1/phone-registration-assists`
- `one_account.get_activity_registration_status` → dispatches to the documented registration or phone-assistance status endpoint according to an explicit `resource_type` input

### Medical tools

- `medical.list_departments` → `GET /mock/medical/v1/departments`
- `medical.list_department_doctors` → `GET /mock/medical/v1/departments/{departmentId}/doctors`
- `medical.search_registration_slots` → `GET /mock/medical/v1/registration-slots`
- `medical.create_registration` → `POST /mock/medical/v1/registrations`
- `medical.list_appointment_services` → `GET /mock/medical/v1/appointment-services`
- `medical.search_appointment_slots` → `GET /mock/medical/v1/appointment-slots`
- `medical.create_appointment` → `POST /mock/medical/v1/appointments`
- `medical.get_my_appointments` → `GET /mock/medical/v1/appointments`
- `medical.get_appointment` → `GET /mock/medical/v1/appointments/{appointmentId}`
- `medical.get_task_status` → `GET /mock/medical/v1/tasks/{taskId}`

The registry must preserve the exact field names and enum values in the source API documents. It may wrap them in the adapter-only `{ "context": {}, "input": {} }` envelope, but it must not rename or reinterpret backend fields.

## Context and safety policy

MCP tool arguments use this envelope:

```json
{
  "context": {
    "mock_user_id": "USR-DEMO-001",
    "patient_id": "PAT-DEMO-001",
    "authorization": "Bearer mock-user-token",
    "accept_language": "zh-TW",
    "request_id": "REQ-DEMO-001",
    "idempotency_key": "TASK-001-STEP-01"
  },
  "input": {}
}
```

`context` is adapter metadata, not backend business data. Only documented headers are emitted. `authorization` is required for medical tools and is passed as the documented mock token; it is not validated as real OAuth. `confirmation` and `consent` remain in `input` and are passed to the backend; the adapter never manufactures them or treats their presence as authorization. The adapter does not claim a request is complete unless the backend returns a success response.

## Response and error handling

Successful tool calls return the backend JSON as structured content and a compact text representation suitable for MCP clients. Backend error envelopes are preserved as structured error details while the MCP result sets `isError=true`. Transport and parsing failures use stable adapter error codes:

- `BACKEND_UNAVAILABLE`
- `BACKEND_TIMEOUT`
- `BACKEND_INVALID_RESPONSE`
- `INVALID_TOOL_ARGUMENTS`
- `UNKNOWN_TOOL`

Tracebacks and local filesystem paths are never returned to the MCP client. HTTP status and backend error code remain available in structured details for Workflow handling and retry decisions.

## Testing and acceptance

Tests use only the Python standard library and temporary local resources:

1. Unit tests verify tool catalog count, names, schemas, path templates and risk/context metadata.
2. Adapter tests verify GET query mapping, POST JSON mapping, allowlisted headers, required idempotency context and error conversion.
3. Protocol tests spawn `python -m MCP` as a subprocess and exercise `initialize`, `tools/list` and `tools/call` over stdio.
4. An in-process fixture HTTP backend records requests and returns representative `200`, `201`, `202`, `400`, `409` and malformed-response cases.
5. The smoke test proves an MCP call reaches the backend with the expected HTTP method, path, body and headers, and that the result is usable by a client.

The implementation is accepted when all tests pass, the MCP process completes the initialize/list/call handshake, every catalog tool maps to a documented `docs/api/` endpoint, and no test requires a real network service.

## Non-goals

- No Workflow Orchestrator or durable task runtime.
- No policy engine, risk decision, identity verification or consent UI.
- No database, receipt store or screenshot store.
- No notification or social-welfare adapter before a corresponding API contract exists in `docs/api/`.
- No arbitrary REST proxy capability.
