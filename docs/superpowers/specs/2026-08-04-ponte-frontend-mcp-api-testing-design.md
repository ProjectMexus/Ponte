# Ponte 前端 MCP／後端 API 測試設計

## 目標

讓 Ponte 前端文字輸入同時支援兩種可驗證的路徑：

1. 以自然語言啟動既有及新增的 domain workflow，驗證 middleware、MCP stdio server 和 mock backend 的整合。
2. 以受控的 `mcp <tool-name> <JSON input>` 命令逐一呼叫固定 registry 的 21 個 MCP tools，檢查 MCP tool mapping 及 backend 回應。

瀏覽器永遠只呼叫 middleware，不直接呼叫 MCP child 或 mock backend。所有 tool 名稱、HTTP method、path、context headers 及 input contract 仍由 `MCP.registry` 和 `MCP.rest_adapter` 控制。

## 現況與範圍

目前 Ponte 已由 middleware 管理一個 `python -m MCP` stdio child，並透過 MCP 的 `tools/call` 將固定 registry tool 轉為 mock backend HTTP request。現有前端自然語言流程涵蓋醫療預約；registry 共公開 21 個 tools，包含一戶通、長者活動和醫療 tools。現有 registry 沒有公開 social-welfare service/referral tools，因此本功能不臆造或新增該 domain 的自然語言路由。

本次範圍包括：

- 擴展 deterministic keyword intent 與 workflow，至少支援一戶通現金分享查詢及長者活動搜尋，並保留醫療流程。
- 讓前端文字輸入辨認 `mcp <tool-name> <JSON input>`，由 middleware 重新驗證並透過真實 MCP 呼叫。
- 立即執行只讀 GET tools；POST tools 必須先由使用者確認，再執行。
- 顯示 tool name、request id、registry HTTP contract、風險等級、執行狀態及 backend JSON data。
- 以單元、middleware HTTP、真實 process-boundary full-stack 測試驗證成功、錯誤及確認邊界。

本次不包括：

- 瀏覽器直接連接 MCP 或 backend。
- 任意 URL、HTTP method、header、filesystem path 或不在 registry 的 tool。
- 把現有醫療預約的 workflow confirmation 改成通用診斷命令。
- 引入第三方前端 build/runtime dependency。
- 把未在 registry 公開的 social-welfare backend route 加入 catalog。

## 方案選擇

### 方案 A：為每個 domain 建立完整自然語言 workflow

這會為 21 個 tools 建立各自的意圖、欄位收集和流程狀態。使用體驗最像產品，但需要大量 domain-specific prompt、session state 和確認分支，容易把「測試 MCP」和「產品 workflow」耦合，且每增加一個 API 都要新增一條流程。

### 方案 B：只增加通用 MCP 測試面板

前端只提供 tool selector 和 JSON editor。它最容易完整覆蓋 21 個 tools，但不能用自然語言驗證現有產品入口，也不符合目前前端以對話為主的交互方式。

### 方案 C：自然語言 workflow + 明確 MCP diagnostic command（採用）

自然語言只擴展到可穩定定義的只讀 demo workflow；完整 tool coverage 由固定命令提供。兩者共用 middleware pipeline、registry 和真正 MCP child。這個邊界能以少量新增 workflow 提供產品式體驗，同時用一種穩定語法覆蓋全部 21 個工具。

## 使用者流程

### 自然語言

既有輸入如「我想查詢醫療預約」維持原流程，返回醫療預約及服務的 tool events。

新增只讀 smoke workflow：

- 包含「現金分享／現金分享計劃」的輸入呼叫 `one_account.get_cash_sharing_plan`，未指定年份時使用 mock clock 的當年。
- 包含「長者活動／文娛活動／興趣班」的輸入呼叫 `one_account.search_elderly_activities`，預設只查可報名活動。

每個 workflow 都回傳一致的 `assistant_message`、`task_state`、`steps`、`tool_events`、`data` 和 `actions`，因此沿用現有 `interaction-view.js`。

### MCP diagnostic command

前端 textarea 接受以下格式：

```text
mcp <tool-name> <JSON input>
```

其中 `<JSON input>` 是 registry tool 的 `input` object，不需要使用者手寫 `context`。JSON 缺省時視為 `{}`。例如：

```text
mcp medical.list_departments {}
mcp one_account.get_cash_sharing_plan {"year":2026}
mcp one_account.search_elderly_activities {"available_only":true}
```

前端只做輸入體驗與 JSON 初步解析；middleware 必須再次解析 command、檢查 tool 存在、檢查 input 是 object、套用安全 context，不能信任瀏覽器的 validation。

### 寫入型命令

registry 的 GET tools 立即執行。POST tools 的 diagnostic command 只會建立 pending confirmation，不會呼叫 pipeline；回應狀態為 `awaiting_confirmation`，並帶有一個確認 action。確認 action 只可執行 middleware 保存的 tool name 和 input，不能由瀏覽器在第二個請求中改寫任意欄位。

每次寫入命令使用固定 demo payload／idempotency key 的 input 由使用者提供但由 middleware contract 驗證；若缺少必填欄位或 backend contract 不接受，回傳安全的 validation error。原本 `medical.create_appointment` 的既有 workflow confirmation 保持獨立，direct diagnostic 仍不得繞過其確認政策。

## 架構與資料流

```text
Frontend textarea
    |
    | POST /api/interactions/message
    v
Middleware InteractionController
    |-- natural-language intent -> bounded workflow
    |-- mcp command parser -> diagnostic pending/execute
    v
ExecutionPipeline -> McpExecutionStage -> McpStdioClient
                                      |
                                      | newline JSON-RPC tools/call
                                      v
                                 python -m MCP
                                      |
                                      v
                           registry + RestAdapter
                                      |
                                      v
                              Mock Backend HTTP
```

### Middleware

新增一個小型 diagnostic command/parser 模組，負責：

- 將 message 開頭的 `mcp` command 解析為 tool name、input object。
- 只接受固定格式，不接受 URL、method、headers 或 context 注入。
- 產生可序列化的 diagnostic response，包含 registry contract 摘要和 `ToolExecutionResult`。

`InteractionController` 在 intent workflow 前先檢查 diagnostic command；讀取命令直接 dispatch，寫入命令將受控 pending command 放入 session，並由 `confirm_tool` action 執行。現有 `/api/mcp/tools/call` 保留作低階 diagnostics／相容 API，新增前端對話路徑不應繞過 controller 的 confirmation policy。

### Diagnostic response

診斷回應沿用前端 response contract，並加入明確的 diagnostic data：

```json
{
  "mode": "mcp_diagnostic",
  "assistant_message": "已完成 MCP tool 測試。",
  "task_state": "completed",
  "tool_events": [
    {
      "tool_name": "medical.list_departments",
      "step_id": "diagnostic_medical_list_departments",
      "ok": true,
      "request_id": "REQ-..."
    }
  ],
  "data": {
    "diagnostic": {
      "tool_name": "medical.list_departments",
      "http_method": "GET",
      "path": "/mock/medical/v1/departments",
      "risk_level": "R0"
    },
    "backend_response": {
      "request_id": "REQ-...",
      "data": {}
    }
  },
  "actions": []
}
```

`path` 是 registry 根據 input resolve 後的受控 path；不顯示 authorization 等敏感 context。MCP protocol error、backend HTTP error、invalid input 和 unknown tool 都以現有安全 error contract 返回，並在 tool event 顯示失敗狀態。

### Frontend

`app.js` 在送出訊息時識別 diagnostic command，使用 `MiddlewareClient` 的 middleware endpoint；不新增對 MCP 或 backend 的 fetch。`interaction-view.js` 擴展 diagnostic data 的呈現，沿用既有 tool event 和 data card，並讓 `confirm_tool` action 由現有 action handler 提交。

前端會在輸入區提供簡短格式提示和至少一個 command example，但不建立第二套 JSON contract。自然語言與 diagnostic response 都寫入同一個 conversation/workspace，讓使用者可在同一頁交替測試。

## 錯誤處理與安全

- command 不是有效 JSON、input 不是 object、tool 不存在：HTTP 400，錯誤碼分別保持可區分，且不含 traceback。
- tool input 缺少 registry required field：不啟動 backend request，回傳 `INVALID_TOOL_ARGUMENTS`。
- MCP child 不可用、protocol error 或 timeout：回傳現有 `MCP_*` safe error，middleware process cleanup 不變。
- backend 回傳 4xx/5xx 或不合法 JSON：回傳 adapter 的 safe error，保留 request id、status、retryable 和公開 details。
- POST 在未確認前不執行；確認 action 只使用 session 內保存的 pending command。
- 前端呈現所有 backend data 時使用 textContent／既有安全 renderer，不把回應當成 HTML。
- 所有新的 HTTP 測試只綁定 `127.0.0.1`，使用 ephemeral ports 和 temporary data directories。

## 測試策略與完成判準

### 單元測試

- diagnostic parser 覆蓋空 JSON、有效 input、malformed JSON、unknown tool syntax 和額外欄位。
- keyword intent 覆蓋醫療、現金分享、長者活動及一般訊息。
- controller 覆蓋 GET 立即 dispatch、POST 產生 confirmation、確認後 dispatch、取消不 dispatch。
- response builder 覆蓋 registry metadata、backend payload 和錯誤 tool event。

### Middleware HTTP 測試

- 以 fake MCP client 驗證 endpoint/controller 的 tool name 和 input envelope。
- 以 real application + real MCP child + temporary backend 驗證多個 GET 命令真正回到 backend data。
- 驗證未確認的 POST 不會建立 backend record，確認後能以 tool event 和 response data 看到成功結果。

### Full-stack／前端測試

- 既有 static asset 和 Node syntax checks 保持通過。
- full-stack integration 至少測試醫療、現金分享、長者活動三個只讀命令，並斷言 MCP child 的 command 是 `python -m MCP`。
- browser smoke 驗證自然語言醫療流程與 diagnostic command 的可見 tool event／data；若 WSL browser binding 仍不可用，記錄環境限制並以 deterministic HTTP full-stack test 作為替代證據。

完成判準是：自然語言醫療流程不回歸；至少三個 domain 的文字輸入能經由真實 MCP 到達 backend；固定 command 能覆蓋 registry tool selection；POST 未確認不產生 side effect，確認後能正確寫入；完整既有測試、MCP/middleware 測試和 compile checks 通過。

## 實作分支與 commit 邊界

兩條功能線共用已存在的 `ToolRegistry`、`ExecutionPipeline`、`ToolExecutionResult` 和前端 response renderer，但分成兩個獨立 commit，方便逐步 review 和回退：

1. `feat: extend natural language workflows`：只修改 intent/workflow、自然語言 response 及其測試；不得引入 `mcp <tool>` command parser 或 diagnostic confirmation action。
2. `feat: add frontend MCP diagnostic commands`：只修改 diagnostic parser/controller path、通用 confirmation、前端命令入口／顯示及其測試；自然語言 workflow 的既有行為需保持通過。

實作時先建立兩條線共用的 response／session interface 定義，再由兩個 disjoint write-set sub-agent 並行完成各自 commit。主線負責整合、檢查 commit diff、處理衝突以及跑全套驗證；若兩條線都需要修改 `middleware/controller.py` 或 `frontend/app.js`，先將共用切點拆到獨立小模組，避免兩個 agent 同時編輯同一段程式碼。
