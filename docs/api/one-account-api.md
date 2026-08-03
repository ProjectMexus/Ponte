# Mock 一戶通 API 文檔

> 版本：`v1`  
> 更新日期：`2026-08-03`  
> API 類型：Demo / Mock  
> 對應架構：`docs/PonteArch.md` 的 Mock 一戶通 Service Layer

本 API 用於 Ponte Demo，模擬一戶通相關公共服務。它不連接真實政府系統、不執行真實身份驗證，也不代表澳門政府的正式 API 規格。所有姓名、身份證號、銀行帳戶、籌號及金額均為測試資料。

本版本提供以下功能：

1. 養老金申請
2. 現金分享計劃查詢
3. 預約政府綜合服務中心取籌
4. 預約身份證明局取籌
5. 查詢我的籌號

---

## 1. API 基本規範

### 1.1 Base URL

```text
/mock/one-account
```

例如：

```text
POST /mock/one-account/pension/applications
```

### 1.2 Content Type

所有 request body 使用 `application/json`，所有 response 使用 `application/json`。

### 1.3 Headers

| Header | 必填 | 說明 |
| --- | --- | --- |
| `X-Mock-User-Id` | 是 | Mock 使用者上下文，例如 `USR-DEMO-001`。這不是正式身份驗證。 |
| `X-Request-Id` | 否 | 呼叫方指定的請求 ID；未提供時由 API 生成。 |
| `Idempotency-Key` | POST 必填 | 防止重試造成重複申請或重複取籌，例如 `TASK-3821-STEP-03`。 |

`Idempotency-Key` 在相同 `X-Mock-User-Id` 和相同 endpoint 下重複使用時，Mock API 必須返回第一次提交的結果；如果 request body 不同，返回 `409 IDEMPOTENCY_KEY_REUSED`。

### 1.4 日期、時間及金額

- 日期使用 `YYYY-MM-DD`，例如 `2026-08-04`。
- 時間使用 ISO 8601，時區固定為澳門時間 `+08:00`，例如 `2026-08-03T14:05:00+08:00`。
- 金額使用數字及貨幣代碼，例如 `{ "amount": 10000, "currency": "MOP" }`。
- API 回應中的 mock 時間可按測試時鐘推進，方便展示 Durable Task 的狀態變化。

### 1.5 統一 response envelope

成功回應：

```json
{
  "request_id": "REQ-20260803-0001",
  "data": {}
}
```

錯誤回應：

```json
{
  "request_id": "REQ-20260803-0002",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "requested_date 必須是有效日期。",
    "details": [
      {
        "field": "requested_date",
        "reason": "invalid_date"
      }
    ],
    "retryable": false
  }
}
```

### 1.6 常用 HTTP 狀態碼

| Status | 使用情況 |
| --- | --- |
| `200 OK` | 查詢成功，或重放已成功處理的 idempotent request |
| `201 Created` | 成功建立申請或籌號 |
| `400 Bad Request` | JSON 格式或 query parameter 不正確 |
| `401 Unauthorized` | 缺少 `X-Mock-User-Id` |
| `404 Not Found` | 找不到指定的 mock 資源 |
| `409 Conflict` | 重複提交、籌號已存在或 idempotency key 衝突 |
| `422 Unprocessable Entity` | 欄位格式正確，但資料不符合服務要求 |
| `429 Too Many Requests` | 模擬服務暫時限制請求 |
| `500 Internal Server Error` | 模擬服務未預期錯誤 |

---

## 2. 風險及 Workflow 對應

API 本身只提供受控的 mock 能力；身份驗證、確認節點、工具權限及 Durable Task 狀態由 Ponte Workflow Orchestrator 管理。

| 功能 | Risk | 建議 Workflow | 提交前條件 |
| --- | --- | --- | --- |
| 養老金申請 | `R2` | `one_account_pension_apply_v1` | 已完成模擬身份驗證、資料回讀及本人確認 |
| 現金分享計劃查詢 | `R0` | `one_account_cash_sharing_query_v1` | 只需建立 mock user context |
| 政府綜合服務中心取籌 | `R1` | `one_account_gsc_queue_v1` | 使用者確認服務中心、日期及服務類型 |
| 身份證明局取籌 | `R1` | `one_account_idb_queue_v1` | 使用者確認服務中心、日期及辦理事項 |
| 查詢我的籌號 | `R0` | `one_account_my_queue_v1` | 只返回目前 mock user 的籌號 |

建議 Workflow 在每次工具呼叫前後記錄 `TaskEvent`：

```json
{
  "event_type": "mock_api.completed",
  "service": "one_account",
  "operation": "pension.submit_application",
  "request_id": "REQ-20260803-0001",
  "status": "success"
}
```

---

## 3. Endpoint：提交養老金申請

### `POST /pension/applications`

建立一份養老金申請。這是高影響操作，Mock API 只接受已由 Workflow 產生的確認資料。

#### Request headers

```http
X-Mock-User-Id: USR-DEMO-001
X-Request-Id: REQ-20260803-0001
Idempotency-Key: TASK-3821-STEP-05
Content-Type: application/json
```

#### Request body

```json
{
  "applicant": {
    "full_name": "陳美玲",
    "id_document_type": "MACAU_ID",
    "id_document_number": "MOCK-1234567(8)",
    "date_of_birth": "1946-05-22",
    "phone": "+853-6234-5678",
    "address": {
      "street": "澳門半島測試街 1 號",
      "district": "澳門半島"
    }
  },
  "payment_account": {
    "account_type": "bank_account",
    "bank_code": "MOCK-001",
    "account_name": "陳美玲",
    "account_number": "MOCK-000123"
  },
  "documents": [
    {
      "document_type": "identity_document",
      "file_id": "FILE-MOCK-001",
      "file_name": "mock-id-card.pdf"
    },
    {
      "document_type": "bank_account_proof",
      "file_id": "FILE-MOCK-002",
      "file_name": "mock-bank-proof.pdf"
    }
  ],
  "consents": {
    "data_processing": true,
    "cross_service_access": true
  },
  "confirmation": {
    "confirmation_id": "CONF-20260803-0001",
    "confirmed_at": "2026-08-03T14:01:20+08:00",
    "displayed_summary_hash": "sha256:mock-pension-summary-001"
  }
}
```

#### Input 欄位

| 欄位 | 類型 | 必填 | 說明 |
| --- | --- | --- | --- |
| `applicant.full_name` | string | 是 | 申請人姓名；Demo 只作資料回讀 |
| `applicant.id_document_number` | string | 是 | Mock 身份證明文件號碼 |
| `applicant.date_of_birth` | date | 是 | 出生日期 |
| `applicant.phone` | string | 是 | 聯絡電話 |
| `payment_account` | object | 是 | 收款帳戶 mock 資料 |
| `documents` | array | 是 | 已上傳的文件引用；至少需要身份證明及銀行帳戶證明 |
| `consents.data_processing` | boolean | 是 | 必須為 `true` |
| `consents.cross_service_access` | boolean | 否 | 是否允許一戶通 mock 服務共用申請資料 |
| `confirmation` | object | 是 | Workflow 確認節點的結果 |

#### Response `201 Created`

```json
{
  "request_id": "REQ-20260803-0001",
  "data": {
    "application": {
      "application_id": "PEN-20260803-0001",
      "application_type": "pension",
      "applicant_name": "陳美玲",
      "status": "SUBMITTED",
      "submitted_at": "2026-08-03T14:01:25+08:00",
      "next_action": {
        "type": "WAIT_FOR_REVIEW",
        "message": "申請已提交，Mock 審核服務將在下一次狀態檢查時返回結果。"
      }
    },
    "receipt": {
      "receipt_id": "REC-20260803-0001",
      "official_reference": "PEN-MOCK-88219",
      "received_at": "2026-08-03T14:01:25+08:00"
    }
  }
}
```

#### Mock 狀態

`application.status` 可按測試場景依次變為：

```text
SUBMITTED → UNDER_REVIEW → NEEDS_ADDITIONAL_INFORMATION
                         → APPROVED
                         → REJECTED
```

初始成功提交固定返回 `SUBMITTED`。如需展示補件或完成流程，Mock fixture 可在 scheduler 執行後改變狀態；本版本不額外提供申請狀態 endpoint。

#### 可能錯誤

| Status | Error code | 情況 |
| --- | --- | --- |
| `409` | `CONFIRMATION_REQUIRED` | 缺少 confirmation，或未確認提交 |
| `409` | `DUPLICATE_SUBMISSION` | 同一 mock user 已有相同申請 |
| `409` | `IDEMPOTENCY_KEY_REUSED` | 同一 key 對應不同 request body |
| `422` | `MISSING_DOCUMENT` | 缺少身份證明或銀行帳戶證明 |
| `422` | `CONSENT_REQUIRED` | `data_processing` 不為 `true` |

---

## 4. Endpoint：查詢現金分享計劃

### `GET /cash-sharing-plan`

查詢指定年度的現金分享計劃 mock 資料，包括資格、金額及發放狀態。此 endpoint 只模擬查詢，不代表真實計劃規則或金額。

#### Query parameters

| 參數 | 類型 | 必填 | 預設值 | 說明 |
| --- | --- | --- | --- | --- |
| `year` | integer | 否 | 當前 mock 年度 | 查詢年度，例如 `2026` |
| `include_history` | boolean | 否 | `false` | 是否包含同一 mock user 的過往年度資料 |

#### Request

```http
GET /mock/one-account/cash-sharing-plan?year=2026&include_history=false
X-Mock-User-Id: USR-DEMO-001
```

#### Response `200 OK`

```json
{
  "request_id": "REQ-20260803-0003",
  "data": {
    "plan": {
      "plan_id": "CSP-2026",
      "plan_name": "現金分享計劃",
      "year": 2026,
      "status": "OPEN",
      "eligibility": {
        "eligible": true,
        "status": "ELIGIBLE",
        "reason": "符合本 Demo 測試用的基本資格資料。"
      },
      "payout": {
        "amount": 10000,
        "currency": "MOP",
        "payment_status": "SCHEDULED",
        "scheduled_date": "2026-09-30"
      },
      "last_updated_at": "2026-08-03T09:00:00+08:00"
    },
    "history": []
  }
}
```

`include_history=true` 時，`history` 可返回：

```json
[
  {
    "year": 2025,
    "eligibility_status": "ELIGIBLE",
    "amount": 10000,
    "currency": "MOP",
    "payment_status": "PAID",
    "paid_at": "2025-09-30"
  }
]
```

#### 可能錯誤

| Status | Error code | 情況 |
| --- | --- | --- |
| `400` | `INVALID_YEAR` | `year` 不是四位數字或不在 mock 資料範圍 |
| `404` | `PLAN_NOT_FOUND` | 指定年度沒有 mock 計劃 |

---

## 5. Endpoint：預約政府綜合服務中心取籌

### `POST /queue-tickets/government-service-center`

為目前 mock user 預約政府綜合服務中心的取籌服務。這裡的「預約」表示預先取得一個可在指定日期使用的 mock 籌號，不代表真實櫃檯預約。

#### Request body

```json
{
  "service_center_id": "GSC-MAIN",
  "service_type": "general_counter",
  "requested_date": "2026-08-04",
  "party_size": 1,
  "contact_phone": "+853-6234-5678",
  "confirmation": {
    "confirmation_id": "CONF-20260803-0002",
    "confirmed_at": "2026-08-03T14:05:10+08:00"
  }
}
```

#### Input 欄位

| 欄位 | 類型 | 必填 | 說明 |
| --- | --- | --- | --- |
| `service_center_id` | string | 是 | 服務中心 mock ID，例如 `GSC-MAIN` |
| `service_type` | string | 是 | `general_counter`、`social_service_counter` 或 `other` |
| `requested_date` | date | 是 | 預計到訪日期 |
| `party_size` | integer | 否 | 辦事人數，預設 `1`，範圍為 `1-4` |
| `contact_phone` | string | 是 | 取籌狀態通知電話 |
| `confirmation` | object | 是 | 使用者已確認服務中心、日期及服務類型 |

#### Response `201 Created`

```json
{
  "request_id": "REQ-20260803-0004",
  "data": {
    "ticket": {
      "ticket_id": "Q-GSC-20260803-0001",
      "service_category": "government_service_center",
      "service_center_id": "GSC-MAIN",
      "service_center_name": "政府綜合服務中心（Mock）",
      "service_type": "general_counter",
      "requested_date": "2026-08-04",
      "ticket_number": "A023",
      "status": "WAITING",
      "queue_position": 23,
      "now_serving": "A012",
      "estimated_wait_minutes": 52,
      "issued_at": "2026-08-03T14:05:15+08:00",
      "valid_until": "2026-08-04T17:00:00+08:00",
      "instructions": [
        "請於指定日期到服務中心報到。",
        "籌號接近時，Mock Notification Service 會發送提醒。"
      ]
    }
  }
}
```

#### 可能錯誤

| Status | Error code | 情況 |
| --- | --- | --- |
| `409` | `ACTIVE_TICKET_EXISTS` | 同一 mock user 在同一服務中心及日期已有有效籌號 |
| `409` | `QUEUE_NOT_AVAILABLE` | 該日期的 mock 籌號已派完 |
| `422` | `INVALID_SERVICE_CENTER` | 不支援的服務中心 ID |
| `422` | `INVALID_REQUESTED_DATE` | 日期已過或不在可取籌日期範圍 |

---

## 6. Endpoint：預約身份證明局取籌

### `POST /queue-tickets/identification-services-bureau`

為目前 mock user 預約身份證明局指定辦理事項的取籌服務。

#### Request body

```json
{
  "service_center_id": "IDB-MAIN",
  "service_type": "identity_card_replacement",
  "requested_date": "2026-08-05",
  "document_type": "MACAU_ID",
  "contact_phone": "+853-6234-5678",
  "confirmation": {
    "confirmation_id": "CONF-20260803-0003",
    "confirmed_at": "2026-08-03T14:08:20+08:00"
  }
}
```

#### Input 欄位

| 欄位 | 類型 | 必填 | 說明 |
| --- | --- | --- | --- |
| `service_center_id` | string | 是 | 身份證明局服務地點 mock ID，例如 `IDB-MAIN` |
| `service_type` | string | 是 | `identity_card_renewal`、`identity_card_replacement` 或 `travel_document` |
| `requested_date` | date | 是 | 預計到訪日期 |
| `document_type` | string | 是 | `MACAU_ID`、`TRAVEL_DOCUMENT` 或 `OTHER` |
| `contact_phone` | string | 是 | 取籌狀態通知電話 |
| `confirmation` | object | 是 | 使用者已確認辦理事項及日期 |

#### Response `201 Created`

```json
{
  "request_id": "REQ-20260803-0005",
  "data": {
    "ticket": {
      "ticket_id": "Q-IDB-20260803-0001",
      "service_category": "identification_services_bureau",
      "service_center_id": "IDB-MAIN",
      "service_center_name": "身份證明局（Mock）",
      "service_type": "identity_card_replacement",
      "document_type": "MACAU_ID",
      "requested_date": "2026-08-05",
      "ticket_number": "B008",
      "status": "WAITING",
      "queue_position": 8,
      "now_serving": "B003",
      "estimated_wait_minutes": 18,
      "issued_at": "2026-08-03T14:08:25+08:00",
      "valid_until": "2026-08-05T17:00:00+08:00",
      "instructions": [
        "請帶備與辦理事項相符的 mock 文件。",
        "如需取消或改期，應由 Workflow Orchestrator 建立新的受控操作。"
      ]
    }
  }
}
```

#### 可能錯誤

| Status | Error code | 情況 |
| --- | --- | --- |
| `409` | `ACTIVE_TICKET_EXISTS` | 同一 mock user 已有同一辦理事項的有效籌號 |
| `409` | `QUEUE_NOT_AVAILABLE` | 該日期的 mock 籌號已派完 |
| `422` | `INVALID_SERVICE_CENTER` | 不支援的身份證明局服務地點 |
| `422` | `INVALID_SERVICE_TYPE` | 不支援的辦理事項 |
| `422` | `INVALID_REQUESTED_DATE` | 日期已過或不在可取籌日期範圍 |

---

## 7. Endpoint：查詢我的籌號

### `GET /my/queue-tickets`

返回 `X-Mock-User-Id` 對應使用者的籌號，不可查詢其他 mock user 的資料。

#### Query parameters

| 參數 | 類型 | 必填 | 預設值 | 說明 |
| --- | --- | --- | --- | --- |
| `status` | string | 否 | `active` | `active`、`waiting`、`called`、`completed`、`cancelled`、`all` |
| `service_category` | string | 否 | 無 | `government_service_center` 或 `identification_services_bureau` |
| `requested_date` | date | 否 | 無 | 只返回指定日期的籌號 |

#### Request

```http
GET /mock/one-account/my/queue-tickets?status=active
X-Mock-User-Id: USR-DEMO-001
```

#### Response `200 OK`

```json
{
  "request_id": "REQ-20260803-0006",
  "data": {
    "user_id": "USR-DEMO-001",
    "tickets": [
      {
        "ticket_id": "Q-GSC-20260803-0001",
        "service_category": "government_service_center",
        "service_center_name": "政府綜合服務中心（Mock）",
        "service_type": "general_counter",
        "requested_date": "2026-08-04",
        "ticket_number": "A023",
        "status": "WAITING",
        "queue_position": 23,
        "estimated_wait_minutes": 52,
        "last_updated_at": "2026-08-03T14:05:15+08:00"
      },
      {
        "ticket_id": "Q-IDB-20260803-0001",
        "service_category": "identification_services_bureau",
        "service_center_name": "身份證明局（Mock）",
        "service_type": "identity_card_replacement",
        "requested_date": "2026-08-05",
        "ticket_number": "B008",
        "status": "WAITING",
        "queue_position": 8,
        "estimated_wait_minutes": 18,
        "last_updated_at": "2026-08-03T14:08:25+08:00"
      }
    ],
    "summary": {
      "total": 2,
      "waiting": 2,
      "called": 0
    }
  }
}
```

沒有符合條件的籌號時，仍返回 `200`，`tickets` 為空 array，`summary.total` 為 `0`。

---

## 8. 共用資料模型

### 8.1 PensionApplication

```json
{
  "application_id": "PEN-20260803-0001",
  "application_type": "pension",
  "status": "SUBMITTED",
  "submitted_at": "2026-08-03T14:01:25+08:00",
  "next_action": {
    "type": "WAIT_FOR_REVIEW",
    "message": "等待 Mock 審核結果"
  }
}
```

允許的 `status`：

```text
SUBMITTED | UNDER_REVIEW | NEEDS_ADDITIONAL_INFORMATION |
APPROVED | REJECTED | CANCELLED
```

### 8.2 QueueTicket

```json
{
  "ticket_id": "Q-GSC-20260803-0001",
  "service_category": "government_service_center",
  "service_center_id": "GSC-MAIN",
  "ticket_number": "A023",
  "requested_date": "2026-08-04",
  "status": "WAITING",
  "queue_position": 23,
  "estimated_wait_minutes": 52
}
```

允許的 `status`：

```text
WAITING | CALLED | COMPLETED | CANCELLED | EXPIRED
```

### 8.3 Error

```json
{
  "code": "MISSING_DOCUMENT",
  "message": "缺少銀行帳戶證明。",
  "details": [
    {
      "field": "documents",
      "reason": "bank_account_proof_required"
    }
  ],
  "retryable": false
}
```

`retryable=true` 只應用於網絡錯誤、模擬服務暫時不可用或 `5xx` 類錯誤；資料驗證、權限、確認及重複提交錯誤不可自動重試。

---

## 9. 建議 Mock fixture

為方便前端、Workflow 及 Demo 使用，初始資料可包含以下 mock user：

| User ID | 姓名 | 可展示情境 |
| --- | --- | --- |
| `USR-DEMO-001` | 陳美玲 | 養老金申請、現金分享計劃符合資格、兩個有效籌號 |
| `USR-DEMO-002` | 黃志強 | 現金分享計劃不符合資格、政府綜合服務中心無可用籌號 |
| `USR-DEMO-003` | 李秀蘭 | 養老金申請缺少銀行帳戶證明，觸發補件流程 |

建議的 mock 狀態場景：

1. `pension_submit_success`：確認資料完整，返回 `SUBMITTED` 及官方回執。
2. `pension_missing_document`：缺少 `bank_account_proof`，返回 `422 MISSING_DOCUMENT`。
3. `cash_sharing_eligible`：返回 `ELIGIBLE` 及 `SCHEDULED`。
4. `cash_sharing_not_eligible`：返回 `NOT_ELIGIBLE` 及原因。
5. `queue_ticket_waiting`：成功取得籌號，返回 `WAITING`。
6. `queue_ticket_duplicate`：已有有效籌號，返回 `409 ACTIVE_TICKET_EXISTS`。
7. `queue_ticket_called`：scheduler 將籌號更新為 `CALLED`，供前端展示通知。

---

## 10. 完整調用示例

以下示例展示 Ponte Workflow 可能採用的最短路徑：

```text
使用者確認養老金資料
  ↓
POST /mock/one-account/pension/applications
  ↓
收到 application_id 和 official_reference
  ↓
記錄 TaskEvent 及 Action Receipt
```

```text
使用者：「幫我睇下今年有冇現金分享。」
  ↓
GET /mock/one-account/cash-sharing-plan?year=2026
  ↓
以粵語解釋 eligibility、金額和 payment_status
```

```text
使用者確認到政府綜合服務中心辦事
  ↓
POST /mock/one-account/queue-tickets/government-service-center
  ↓
取得 ticket_number=A023
  ↓
GET /mock/one-account/my/queue-tickets?status=active
  ↓
持續展示籌號、目前叫號及預計等候時間
```

---

## 11. 實作注意事項

- API 只應由 One Account MCP Adapter 或受控 Backend 調用，不應讓 LLM 直接寫入 mock store。
- 養老金提交和取籌建立都必須支援 idempotency，避免 Workflow retry 造成重複結果。
- 查詢籌號時必須以 `X-Mock-User-Id` 作資料隔離，不能接受任意 `user_id` query parameter。
- `confirmation` 只證明 Ponte 已完成模擬確認，不等同政府身份驗證或電子簽署。
- 養老金申請的金額、資格及現金分享計劃資料只供 Demo 展示，不能在 UI 中表述為正式政策規則。
- Mock API 的所有成功及錯誤結果都應產生可追蹤的 `request_id`，並由上層 Workflow 保存為 evidence event。
- 真實身份驗證、政府正式規則、電子簽署、文件加密及正式通知不在本版本範圍內。
