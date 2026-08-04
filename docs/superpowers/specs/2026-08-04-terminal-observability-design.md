# Terminal Observability Design

## Goal

讓以 `scripts/run_stack.py` 啟動的 Ponte 開發堆疊，在同一個 terminal 中清楚顯示前端、middleware（intent 與 MCP）及 mock backend 的請求流程；LLM 部分只顯示可供除錯的安全摘要，不輸出完整 prompt、response 或任何機密資料。

## Existing Context

目前各服務會共用 `run_stack.py` 啟動時繼承的 stdout/stderr，但：

- frontend 與 mock backend 的 HTTP request log 被覆蓋為靜默輸出。
- middleware 只輸出啟動訊息，沒有 API、intent 或 MCP 階段摘要。
- middleware 的 MCP stdio client 將 MCP process 的 stderr 丟棄。
- MCP server 的 stdout 是 JSON-RPC transport，不能混入人類可讀的 log。

因此本功能將 logging 集中在各服務本身及 middleware 端的 MCP adapter，保留 MCP stdout 的 protocol 純度；子程序的 stderr/stdout 仍由 `run_stack.py` 直接呈現於同一 terminal。

## Design

### 1. Shared terminal logger

新增只使用 Python standard library 的共用 logging helper，供 frontend、middleware、MCP adapter 及 mock backend 使用。

Logger 必須：

- 寫到 stderr，避免干擾 MCP server stdout 的 JSON-RPC stream。
- 預設使用 `INFO`，由 `PONTE_LOG_LEVEL` 控制級別；未知值回退至 `INFO`。
- 使用固定 component 名稱與一致格式，例如：

  ```text
  2026-08-04 12:00:00 INFO [middleware] request_end method=POST path=/api/intent status=200 latency_ms=18
  ```

- 支援每個 process 僅設定一次 handler，避免重複輸出。
- logging 發生問題時不得影響原本的 business request 或 JSON-RPC response。
- 不依賴 `.env` 在 module import 時已經載入；第一次寫 log 時讀取當前環境設定。

Component 名稱固定為 `frontend`、`middleware`、`llm`、`mcp`、`backend`，讓 terminal grep 與人工閱讀都容易。

### 2. Safe LLM summaries

LLM request/response 只記錄摘要欄位，不記錄內容本身。

發送摘要包含：

- component：`llm`
- direction/event：`send`
- request id
- model
- endpoint 的 host/path（移除 query string）
- message 數量與總字元數

接收摘要包含：

- component：`llm`
- direction/event：`receive`
- request id
- parsed intent（例如 `medical_query` 或 `medical_booking`）
- confidence
- latency in milliseconds

失敗或 fallback 摘要只包含 request id、可分類的 error code/type、fallback 結果與 latency；不得輸出 exception message 中可能包含的完整 response body。

安全規則：

- 絕不記錄 API key、Authorization header、cookie、完整 URL query、prompt、response、患者姓名、患者 ID、病歷內容、預約 payload 或原始 exception body。
- 所有可變字串欄位都必須限制長度；錯誤資料只輸出固定分類或安全的 exception class name。
- intent 與 confidence 只在已完成 schema parsing 後輸出；不輸出原始模型文字。
- 即使提高 `PONTE_LOG_LEVEL`，也不提供 raw LLM content 開關，維持 safe-by-default。

預期摘要形式：

```text
INFO [llm] send request_id=llm-7f2 model=gemini-2.5-flash-lite endpoint=generativelanguage.googleapis.com/v1beta/openai/chat/completions messages=1 message_chars=12
INFO [llm] receive request_id=llm-7f2 intent=medical_query confidence=0.96 latency_ms=842
```

### 3. Middleware and intent flow

middleware 對每個 API request 記錄開始與結束摘要：

- HTTP method、path、request id
- response status、latency
- 不記錄 body、header 值或 query 值

intent flow 額外記錄：

- intent source：`llm` 或 `keyword_fallback`
- parsed task/intent
- confidence（若有）
- fallback reason 的固定分類（例如 `llm_unavailable`、`invalid_schema`、`unsupported_intent`）

這些 event 必須覆蓋醫療查詢、醫療預約及既有非醫療流程，方便在 terminal 中看出請求走到了哪一層，但不能暴露醫療資料。

### 4. MCP flow

MCP logs 由 middleware 端的 client/adapter 輸出，記錄：

- MCP request id
- operation（例如 `tools/call`）
- tool name
- input key names（只列 key，不列 value）
- success/error category
- latency

MCP server stdout 維持只輸出 JSON-RPC。若 MCP server 需要 diagnostics，必須寫 stderr，且由 middleware 端決定是否轉成安全摘要；本次不把原始 MCP protocol body 或 tool result 寫入 terminal。

### 5. Frontend and mock backend flow

frontend static server 記錄：

- method、path、status、response bytes、latency/request id（若可取得）
- 不記錄 cookie、authorization、query 值或 request body

mock backend 記錄：

- method、path、status、latency、request id
- 可選的 route operation 名稱
- 不記錄病人資料、預約資料、headers 或原始 body

`run_stack.py` 維持讓各 child process 繼承 terminal streams，並在啟動/停止時顯示 component 狀態。瀏覽器內的 JavaScript console 不納入本次功能範圍；需求是 terminal observability。

### 6. Configuration and documentation

在 `.env.example`（若存在）及開發文件加入：

```dotenv
PONTE_LOG_LEVEL=INFO
```

文件說明 component prefix、log level 及 safe-by-default 保證，並提供使用 `rg '\\[(frontend|middleware|llm|mcp|backend)\\]'` 篩選 terminal output 的例子。不得要求使用者把 API key 或其他 secret 放進 log 設定。

## Testing

新增或更新測試以確認：

1. logger 預設為 INFO，`PONTE_LOG_LEVEL` 可切換級別，未知級別不會讓服務啟動失敗。
2. LLM send/receive/error logs 包含允許的摘要欄位，但不包含測試用 API key、Authorization、prompt、response、患者資料或 payload 值。
3. intent log 能區分 LLM 成功與 keyword fallback，並輸出解析後的 intent，而不是原始模型文字。
4. MCP log 只輸出 tool name 與 input keys，不輸出 input values 或 JSON-RPC body；stdout transport 測試仍保持通過。
5. frontend、middleware、mock backend 的 request log 可在 captured stderr 中找到 method/path/status/latency。
6. logging 失敗或 log level 設定異常不改變既有 API response。
7. 現有 middleware、MCP、mock backend、frontend 與 integration tests 全部保持通過。

測試中的敏感字串使用明確 marker，並對整段 captured output 做 negative assertions，避免只檢查單一欄位而漏出 secrets。

## Non-goals

- 不記錄完整 LLM prompt、response 或任何醫療 payload。
- 不建立 log file、rotation、集中式 log collector、metrics 或 distributed tracing backend。
- 不改變 intent schema、醫療查詢/預約 API contract 或 MCP tool behavior。
- 不把瀏覽器 console 輸出轉發到 terminal。
- 不需要新增第三方 logging dependency。

## Acceptance criteria

在本地用 `python3 scripts/run_stack.py` 啟動後，對 frontend、醫療 intent、MCP tool 及 mock backend 發出請求時，同一 terminal 能看見帶 component prefix 的安全摘要；LLM 只出現 model/endpoint metadata、字元統計、parsed intent、confidence、status 與 latency 等欄位，且任何完整輸入、輸出、secret 或醫療資料均不出現。既有測試與 JSON-RPC transport 仍通過。
