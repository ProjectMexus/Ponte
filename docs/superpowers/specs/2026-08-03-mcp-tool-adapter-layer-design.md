# Ponte MCP／工具轉接層設計說明

## 目標

在 `./MCP` 建立一個可由 MCP 用戶端透過 `stdio` 啟動的 MCP／工具轉接層，將 `docs/api/` 已定義的 mock 後端 REST API 暴露為固定、可檢查及可測試的 MCP 工具。

本層只負責 MCP 協議、工具 schema、輸入驗證、REST 請求映射、context header 傳遞及錯誤轉換；不負責 Workflow 順序、風險判斷、身份驗證、長期 task state、人工接管或 Action Receipt。

## 契約來源與範圍

唯一的後端 contract 來源是以下文件：

- `docs/api/one-account-api.md`
- `docs/api/elderly-cultural-activities-api.md`
- `docs/api/jinghu-medical-mock-api.md`

`docs/PonteArch.md` 只用於確定 MCP 的架構邊界、Workflow-first 原則及工具命名方向。由於 `docs/api/` 沒有社會福利或 notification 的 HTTP contract，本版本不猜測或暴露這兩類工具。

預設 catalog 包含：

| 領域 | 工具數量 | 來源 |
| --- | ---: | --- |
| `one_account` | 5 | 一戶通 API |
| `one_account` elderly activities | 6 | 長者文娛活動 API |
| `medical` | 10 | 鏡湖通醫療 API |

實際工具名稱、HTTP method、path、query/body 欄位和風險 metadata 必須由 registry 明確列出，不接受用戶端傳入任意 URL、method 或 header。

## 架構

```text
MCP 用戶端
    │ stdio JSON-RPC
    ▼
MCP 伺服器（`python -m MCP`）
    │
    ├── 協議生命週期與工具分派
    ├── 固定工具 registry 與 JSON schema
    ├── context/header 驗證
    └── MCP 安全錯誤轉換
    │ typed REST 請求
    ▼
REST 轉接器（`PONTE_BACKEND_URL`）
    │ HTTP JSON
    ▼
`docs/api/` 定義的 Ponte mock 後端
```

### MCP 伺服器

`MCP/server.py` 讀取 stdin 的 newline-delimited JSON-RPC 訊息，向 stdout 寫回 MCP response；logging 只能寫 stderr，避免污染 stdio protocol。至少支援：

- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call`

`MCP/__main__.py` 提供 `python -m MCP` 啟動入口。伺服器不保存跨 request 的業務狀態。

### 工具 registry

`MCP/registry.py` 保存固定的 `ToolDefinition`，每項定義包含：

- MCP 工具名稱、description 及 `inputSchema`；
- domain、risk metadata 和所需 context；
- HTTP method、path template、query/body mapping；
- 是否要求 `X-Mock-User-Id`、`X-Patient-Id`、`Idempotency-Key`。

registry 提供 `tools/list` 所需的 JSON schema，也提供 `tools/call` 的 dispatch metadata，確保宣告與執行使用同一份 contract。

### REST 轉接器

`MCP/rest_adapter.py` 使用 Python 標準庫 HTTP client，從 `PONTE_BACKEND_URL` 讀取後端 base URL，預設值為 `http://127.0.0.1:8080`。它只接受 registry 產生的 request，負責：

1. 組合固定 path 與 query；
2. 編碼 JSON request body；
3. 傳遞文件指定的 context headers；
4. 解析 JSON response；
5. 將 HTTP status、timeout、connection failure 和 invalid JSON 轉為轉接器錯誤。

所有 POST tool 都要求 `context.idempotency_key`；醫療 tool 都要求 `context.authorization`，並在 API 文件要求時以 `context.patient_id` 映射到 `X-Patient-Id`。`context.accept_language` 可選，預設由 adapter 使用 `zh-TW`，並映射到醫療 API 的 `Accept-Language`。一戶通和長者活動 API 所需的 user context 依文件映射到 `X-Mock-User-Id`。不允許 client 覆寫 `Host`、`Content-Length` 或傳入未列入 allowlist 的 header。

## 工具契約

### 一戶通工具

- `one_account.submit_pension_application` → `POST /mock/one-account/pension/applications`
- `one_account.get_cash_sharing_plan` → `GET /mock/one-account/cash-sharing-plan`
- `one_account.book_government_service_center_queue` → `POST /mock/one-account/queue-tickets/government-service-center`
- `one_account.book_identification_services_bureau_queue` → `POST /mock/one-account/queue-tickets/identification-services-bureau`
- `one_account.list_my_queue_tickets` → `GET /mock/one-account/my/queue-tickets`

### 長者文娛活動工具

- `one_account.search_elderly_activities` → `GET /mock/elderly-activities/v1/activities`
- `one_account.get_elderly_activity` → `GET /mock/elderly-activities/v1/activities/{activityId}`
- `one_account.get_activity_registration_form` → `GET /mock/elderly-activities/v1/activities/{activityId}/registration-form`
- `one_account.submit_activity_registration` → `POST /mock/elderly-activities/v1/registrations`
- `one_account.start_phone_registration_assistance` → `POST /mock/elderly-activities/v1/phone-registration-assists`
- `one_account.get_activity_registration_status` → 按明確的 `resource_type` 輸入，分派至文件定義的填表報名或電話協助狀態 endpoint

### 醫療工具

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

registry 必須保留 API 文件中的原有欄位名稱和 enum 值。它可以使用只屬於轉接器的 `{ "context": {}, "input": {} }` envelope 包裝輸入，但不得重新命名或重新解釋後端欄位。

## Context 與安全政策

MCP 工具參數使用以下 envelope：

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

`context` 是轉接器 metadata，不是後端業務資料。只會發送文件定義的 headers。醫療工具必須提供 `authorization`，並以文件指定的 mock token 傳遞；它不會被驗證為真正的 OAuth。`confirmation` 和 `consent` 保留在 `input` 中並傳給後端；轉接器不會自行建立這些欄位，也不會把欄位存在當作授權。除非後端返回成功 response，轉接器不會聲稱請求已完成。

## Response 與錯誤處理

成功的工具呼叫會將後端 JSON 作為 structured content 返回，並提供適合 MCP 用戶端閱讀的精簡文字表示。後端 error envelope 會保留為 structured error details，同時在 MCP result 設定 `isError=true`。傳輸及解析失敗使用穩定的轉接器錯誤代碼：

- `BACKEND_UNAVAILABLE`
- `BACKEND_TIMEOUT`
- `BACKEND_INVALID_RESPONSE`
- `INVALID_TOOL_ARGUMENTS`
- `UNKNOWN_TOOL`

Traceback 和本機 filesystem path 絕不返回給 MCP 用戶端。HTTP status 和後端 error code 會保留在 structured details，供 Workflow 處理和決定是否重試。

## 測試與驗收

測試只使用 Python 標準庫和暫存本地資源：

1. 單元測試驗證工具 catalog 數量、名稱、schema、path template 及 risk/context metadata。
2. 轉接器測試驗證 GET query 映射、POST JSON 映射、allowlist headers、必要的 idempotency context 及錯誤轉換。
3. 協議測試以 subprocess 啟動 `python -m MCP`，透過 stdio 執行 `initialize`、`tools/list` 和 `tools/call`。
4. 程序內 fixture HTTP backend 記錄請求，並返回具代表性的 `200`、`201`、`202`、`400`、`409` 及 malformed response 情況。
5. 冒煙測試證明 MCP 呼叫會以預期的 HTTP method、path、body 和 headers 到達後端，且用戶端能使用返回結果。

當所有測試通過、MCP 程序完成 initialize/list/call handshake、每個 catalog 工具均映射至 `docs/api/` 定義的 endpoint，且沒有測試依賴真實網絡服務時，即符合本設計的驗收條件。

## 非目標

- 不建立 Workflow Orchestrator 或 durable task runtime。
- 不建立 policy engine、risk decision、身份驗證或 consent UI。
- 不建立資料庫、receipt store 或 screenshot store。
- 在 `docs/api/` 出現對應 API contract 前，不建立 notification 或 social-welfare 轉接器。
- 不提供任意 REST proxy 能力。
