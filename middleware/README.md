# Ponte Middleware

Ponte middleware 是前端唯一需要呼叫的 HTTP bridge。它以 Python 標準庫提供固定 API，將 Interaction Controller 的醫療預約流程接到既有 21 個 MCP registry tools 和 mock backend；前端不需要知道 backend URL、HTTP method、headers 或 MCP envelope。

## 啟動

需要 Python 3.13+，不需要額外 pip dependency。先啟動 mock backend：

```bash
python3 -m mock_backends.server --host 127.0.0.1 --port 8080 --data-dir /tmp/ponte-mock-data
```

再啟動 middleware：

```bash
PONTE_BACKEND_URL=http://127.0.0.1:8080 python3 -m middleware.server --host 127.0.0.1 --port 8090
```

檢查 middleware 和 backend：

```bash
curl http://127.0.0.1:8090/api/health
```

`/api/health` 會實際呼叫 `medical.list_departments`；bridge 本身仍然運作但 backend 未啟動時，HTTP 仍回 200，`backend_reachable` 會是 `false`。session state 只保存在記憶體，middleware 重啟後會遺失。

Intent Recognition 預設使用 keyword recognizer。若設定 `PONTE_LLM_API_URL`，middleware 會優先使用 OpenAI-compatible chat-completions API；LLM 未設定、回應格式錯誤或網絡呼叫失敗時，會自動 fallback 到 keyword recognizer。

## 環境設定

| 變數 | 預設值 | 用途 |
| --- | --- | --- |
| `PONTE_BACKEND_URL` | `http://127.0.0.1:8080` | 由 `RestAdapter` 使用的 backend base URL；path 和 method 仍由固定 registry 決定。 |
| `PONTE_FRONTEND_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 逗號分隔的 CORS origin allowlist。 |
| `PONTE_PATIENT_ID` | `PAT-DEMO-001` | Interaction Controller 使用的 mock patient context。 |
| `PONTE_AUTHORIZATION` | `Bearer mock-user-token` | Interaction Controller 使用的 mock authorization context。 |
| `PONTE_LLM_API_URL` | 空值 | LLM intent endpoint，例如 `https://api.example.com/v1/chat/completions`；未設定時只使用 keyword。 |
| `PONTE_LLM_API_KEY` | 空值 | LLM API bearer token；不要寫入 repository。 |
| `PONTE_LLM_MODEL` | `gpt-4o-mini` | LLM 使用的 model 名稱。 |

## HTTP API

所有 POST body 都必須是 JSON object。錯誤回應使用安全格式，例如：

```json
{"error": {"code": "INVALID_JSON", "message": "request body 不是有效 JSON。"}}
```

### `GET /api/health`

回傳 bridge 狀態、固定 tool count 及 backend connectivity：

```json
{
  "status": "ok",
  "backend_url": "http://127.0.0.1:8080",
  "tool_count": 21,
  "backend_reachable": true
}
```

### `GET /api/mcp/tools`

回傳既有固定 registry catalog。middleware 不接受瀏覽器提供任意 URL、method、header 或 filesystem path。

### `POST /api/interactions/message`

這是前端文字或語音 transcript 的入口：

```json
{
  "session_id": "demo-session-1",
  "message": "我想查詢醫療預約",
  "source": "text"
}
```

`source` 可為 `text` 或 `voice`。辨識到醫療意圖後，controller 會依序查詢我的預約和可預約服務，並回傳 `task_state`、`current_step`、`steps`、`tool_events`、`actions` 和 `data`。

### `POST /api/interactions/action`

所有流程 action 都由 middleware 決定結果：

搜尋時段：

```json
{
  "session_id": "demo-session-1",
  "action": "search_slots",
  "payload": {
    "service_id": "SERVICE-US-001",
    "date_from": "2026-08-10",
    "date_to": "2026-08-14"
  }
}
```

選擇時段：

```json
{
  "session_id": "demo-session-1",
  "action": "select_slot",
  "payload": {"slot_id": "SLOT-US-20260812-1400"}
}
```

明確確認後才可正式提交；`confirmation` 不會被放入 backend body，backend 只會收到 registry contract 定義的欄位和 `consent: true`：

```json
{
  "session_id": "demo-session-1",
  "action": "confirm",
  "payload": {
    "referring_appointment_id": "APT-REF-1",
    "administrative_note": "請按指示提前報到"
  }
}
```

其他固定 action 是 `cancel`、`retry` 和 `human_help`。未確認前的 cancel 不會呼叫 `medical.create_appointment`；直接呼叫該 tool 也會被拒絕並回 `CONFIRMATION_REQUIRED`。

### `POST /api/mcp/tools/call`

此 endpoint 只供 middleware contract / backend connectivity diagnostics 使用；tool name 必須存在於固定 registry，arguments 只能包含 `context` 和 `input`：

```json
{
  "name": "medical.list_departments",
  "arguments": {
    "context": {"authorization": "Bearer mock-user-token"},
    "input": {}
  }
}
```

middleware 會以設定值覆蓋 authorization、patient、language 和 request ID，再交給受控 adapter；client 不能注入任意 backend headers。adapter 的 backend error 會以 `ok: false` 安全返回，malformed request、unknown tool 和 invalid arguments 則回 HTTP 400。

## CORS 與前端

前端預設在 `http://127.0.0.1:5173` 啟動。若前端使用其他 origin，設定 `PONTE_FRONTEND_ORIGINS` 的逗號分隔 allowlist；middleware 會提供 `OPTIONS` preflight、`Content-Type` allow header，以及固定的 GET/POST methods。
