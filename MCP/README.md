# Ponte MCP／工具轉接層

這個目錄提供一個以 Python 標準庫實作的 MCP stdio server，將 `docs/api/` 定義的 mock backend REST API 暴露為固定工具。它不實作 Workflow、身份驗證、風險判斷、持久化、Action Receipt 或任意 REST proxy。

## 啟動

需要 Python 3.13 或以上版本，不需要安裝第三方套件。backend 預設為 `http://127.0.0.1:8080`，可用 `PONTE_BACKEND_URL` 覆寫：

```bash
PONTE_BACKEND_URL=http://127.0.0.1:8080 python3 -m MCP
```

MCP server 使用 newline-delimited JSON-RPC。stdout 只輸出 protocol response；診斷訊息應寫到 stderr。server 支援：

- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call`

## 工具範圍

catalog 固定有 21 個工具，所有 HTTP method/path 均來自 `docs/api/`：

| 領域 | 工具 |
| --- | --- |
| 一戶通 | `one_account.submit_pension_application` |
| 一戶通 | `one_account.get_cash_sharing_plan` |
| 一戶通 | `one_account.book_government_service_center_queue` |
| 一戶通 | `one_account.book_identification_services_bureau_queue` |
| 一戶通 | `one_account.list_my_queue_tickets` |
| 長者活動 | `one_account.search_elderly_activities` |
| 長者活動 | `one_account.get_elderly_activity` |
| 長者活動 | `one_account.get_activity_registration_form` |
| 長者活動 | `one_account.submit_activity_registration` |
| 長者活動 | `one_account.start_phone_registration_assistance` |
| 長者活動 | `one_account.get_activity_registration_status` |
| 醫療 | `medical.list_departments` |
| 醫療 | `medical.list_department_doctors` |
| 醫療 | `medical.search_registration_slots` |
| 醫療 | `medical.create_registration` |
| 醫療 | `medical.list_appointment_services` |
| 醫療 | `medical.search_appointment_slots` |
| 醫療 | `medical.create_appointment` |
| 醫療 | `medical.get_my_appointments` |
| 醫療 | `medical.get_appointment` |
| 醫療 | `medical.get_task_status` |

社會福利和 notification 暫不暴露，因為 `docs/api/` 沒有對應的 HTTP request/response contract。

## Tool call 輸入

每個工具使用 adapter envelope；`context` 會轉成 backend headers，`input` 會保留 API 文件中的欄位名稱：

```json
{
  "context": {
    "mock_user_id": "USR-DEMO-001",
    "patient_id": "P-10001",
    "authorization": "Bearer mock-user-token",
    "request_id": "REQ-DEMO-001",
    "idempotency_key": "TASK-001-STEP-01",
    "accept_language": "zh-TW"
  },
  "input": {
    "department_id": "DEPT-CARDIO",
    "date": "2026-08-12"
  }
}
```

MCP request 範例：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "medical.search_registration_slots",
    "arguments": {
      "context": {
        "authorization": "Bearer mock-user-token",
        "patient_id": "P-10001",
        "request_id": "REQ-DEMO-001"
      },
      "input": {
        "department_id": "DEPT-CARDIO",
        "date": "2026-08-12",
        "session": "morning"
      }
    }
  }
}
```

所有 POST 工具必須提供 `context.idempotency_key`。醫療工具必須提供 mock `authorization`；API 要求病人資料時也必須提供 `context.patient_id`。`confirmation` 和 `consent` 必須由上層 Workflow 放在 `input`，adapter 不會自行產生或繞過。

## 測試

執行單元、registry、REST、protocol 和本地 fixture backend smoke tests：

```bash
python3 -m unittest discover -s MCP/tests -v
python3 -m compileall -q MCP
```

smoke tests 會啟動只綁定 `127.0.0.1` 的 ephemeral fixture server，驗證 stdio MCP → REST adapter → HTTP backend → MCP response 的鏈路，以及 409、malformed response 和 backend unavailable 錯誤。受限 sandbox 可能禁止 local socket bind；若出現 `PermissionError: [Errno 1] Operation not permitted`，需要在允許本地測試 socket 的環境執行 smoke tests。
