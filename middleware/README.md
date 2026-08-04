# Ponte Middleware

Ponte middleware 是前端唯一需要呼叫的 HTTP bridge。它以 Python 標準庫提供固定 API，將 Interaction Controller 的醫療查詢及預約流程接到既有 21 個 MCP tools；runtime 會由 middleware 啟動一個 `python3 -m MCP` stdio child，再由 MCP 的 RestAdapter 連接 mock backend。前端不需要知道 backend URL、HTTP method、headers 或 MCP envelope。

## 啟動

需要 Python 3.13+，不需要額外 pip dependency。第一次使用時先建立本地設定檔：

```bash
cp .env.example .env
```

在 `.env` 填入本地 backend、patient、authorization 及可選的 LLM 設定；`.env` 已被 Git ignore，不應提交 API key。shell 中已存在的同名環境變數會優先於 `.env`。

先啟動 mock backend：

```bash
python3 -m mock_backends.server --host 127.0.0.1 --port 8080 --data-dir /tmp/ponte-mock-data
```

再啟動 middleware；不需要每次在命令前 `set`：

```bash
python3 -m middleware.server --host 127.0.0.1 --port 8090
```

一般完整驗收可直接在 repo 根目錄執行：

```bash
python3 scripts/run_stack.py
```

這個 runner 會啟動 backend、middleware、middleware 管理的 MCP stdio server 和 frontend。瀏覽器輸入「我想查詢自己的醫療預約」後，應看到完成狀態、服務已連線，以及只讀的 `medical.get_my_appointments` tool event。輸入「我想預約醫療服務」則會進入服務選擇、日期範圍、可預約時段及確認流程；確認後可再用前一個查詢讀回 mock backend 的預約記錄。也可以輸入「我想查現金分享計劃」或「我想找長者文娛活動」測試只讀的一戶通／長者活動 workflow。

檢查 middleware 和 backend：

```bash
curl http://127.0.0.1:8090/api/health
```

`/api/health` 會實際呼叫 `medical.list_departments`；bridge 本身仍然運作但 backend 未啟動時，HTTP 仍回 200，`backend_reachable` 會是 `false`。session state 只保存在記憶體，middleware 重啟後會遺失。

Intent Recognition 預設使用 keyword recognizer。若設定 `PONTE_LLM_API_URL`，middleware 會優先使用 OpenAI-compatible chat-completions API；使用 Gemini 時，請設定 `PONTE_LLM_API_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` 及 `PONTE_LLM_MODEL=gemini-2.5-flash-lite`，再在本地填入 Google AI Studio API key。LLM 未設定、回應格式錯誤或網絡呼叫失敗時，會自動 fallback 到 keyword recognizer；API key 不應寫入 repository。

## 環境設定

| 變數 | 預設值 | 用途 |
| --- | --- | --- |
| `PONTE_BACKEND_URL` | `http://127.0.0.1:8080` | 傳給 middleware 管理的 MCP child，再由 MCP RestAdapter 使用；path 和 method 仍由固定 registry 決定。 |
| `PONTE_FRONTEND_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 逗號分隔的 CORS origin allowlist。 |
| `PONTE_PATIENT_ID` | `PAT-DEMO-001` | Interaction Controller 使用的 mock patient context。 |
| `PONTE_MOCK_USER_ID` | `USR-DEMO-001` | 一戶通及長者活動 workflow 使用的 mock user context。 |
| `PONTE_AUTHORIZATION` | `Bearer mock-user-token` | Interaction Controller 使用的 mock authorization context。 |
| `PONTE_LLM_API_URL` | 空值 | LLM intent endpoint；Gemini 示例為 `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`，未設定時只使用 keyword。 |
| `PONTE_LLM_API_KEY` | 空值 | LLM API bearer token；不要寫入 repository。 |
| `PONTE_LLM_MODEL` | `gpt-4o-mini` | LLM 使用的 model 名稱；`.env.example` 示範 `gemini-2.5-flash-lite`。 |

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
  "message": "我想查詢自己的醫療預約",
  "source": "text"
}
```

`source` 可為 `text` 或 `voice`。醫療意圖分為兩條流程：輸入「我想查詢自己的醫療預約」只會呼叫 `medical.get_my_appointments`，返回自己的預約記錄並完成，不會搜尋服務或改變 mock state；輸入「我想預約醫療服務」才會初始化服務選擇。所有 workflow 都會回傳 `task_state`、`current_step`、`steps`、`tool_events`、`actions` 和 `data`。

預約流程會先返回可預約服務。前端選擇服務和日期範圍後，透過 `search_slots` 呼叫 `medical.search_appointment_slots`；可預約時段會出現在回應的 `data.slots`。選擇一個時段後，只有再收到明確的 `confirm` action，middleware 才會呼叫 `medical.create_appointment` 並將記錄寫入 mock backend。之後用「我想查詢自己的醫療預約」即可讀回該記錄。

可直接輸入以下訊息測試自然語言 workflow：

```text
我想查現金分享計劃
我想找長者文娛活動
```

它們分別呼叫 `one_account.get_cash_sharing_plan`（input `{}`）及
`one_account.search_elderly_activities`（input `{"available_only": true}`）。

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

middleware 會以設定值覆蓋 authorization、patient、language 和 request ID，再透過 MCP stdio 傳給受控 adapter；client 不能注入任意 backend headers。MCP 或 backend error 會以 `ok: false` 安全返回，malformed request、unknown tool 和 invalid arguments 則回 HTTP 400。

前端文字輸入也支援 MCP 診斷命令，例如 `mcp medical.list_departments {}`。該命令會走 `/api/interactions/message`，回應會附上 `mode=mcp_diagnostic`、registry 的 HTTP contract、tool event 和 backend response。診斷 POST tool 必須透過 `confirm_tool` action 確認；低階 `/api/mcp/tools/call` 只允許 GET tool，避免繞過確認流程。

## CORS 與前端

前端預設在 `http://127.0.0.1:5173` 啟動。若前端使用其他 origin，設定 `PONTE_FRONTEND_ORIGINS` 的逗號分隔 allowlist；middleware 會提供 `OPTIONS` preflight、`Content-Type` allow header，以及固定的 GET/POST methods。
