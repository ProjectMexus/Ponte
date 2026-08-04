# DEBUG Terminal Observability Design

## Goal

在現有安全摘要 logging 之上，提供一個由 `PONTE_LOG_LEVEL=DEBUG` 明確控制的本機除錯模式。`INFO` 維持只輸出安全摘要；`DEBUG` 讓開發者在 terminal 看見 intent LLM 的完整 prompt/response，以及 MCP tool request/response（包括醫療資料），以便驗證 intent、醫療預約及醫療查詢的端到端流程。

DEBUG 不使用另一個 `raw` 模式名稱，也不改變 API、MCP protocol 或醫療功能行為。

## Existing Context

目前共用 logger 只接受安全欄位，所有事件都以 INFO level 發出，因此提高 `PONTE_LOG_LEVEL` 到 `DEBUG` 不會顯示完整內容。現有 observability 已覆蓋 frontend、middleware、LLM、MCP adapter 及 mock backend，但刻意不記錄 prompt、response、tool arguments 或 tool result。

本次需求只擴充 terminal debugging。LLM 與 MCP 的內容由 middleware 端集中記錄；MCP child process 的 stdout 必須繼續保留給 JSON-RPC transport，不能混入人類可讀 log。

## Design

### 1. Log levels and event API

保留 `PONTE_LOG_LEVEL` 作為唯一開關：

- `INFO`（預設）：只輸出現有安全摘要。
- `DEBUG`：除安全摘要外，輸出內容型除錯事件。
- 未知值：回退到 `INFO`。

共用 logger 提供獨立的 debug event path，避免把敏感欄位加入現有 INFO safe-field allowlist。debug event 只有在 logger level 為 DEBUG 時才格式化及輸出，避免 INFO 模式不必要地處理或意外渲染敏感內容。

所有 log 維持寫到 stderr，使用既有 component prefix 與 timestamp 格式。DEBUG 事件的欄位名稱應清楚標示內容來源，例如 `prompt=...`、`response=...`、`request=...`、`result=...`。

### 2. LLM debug events

在 LLM intent request 前輸出一筆 DEBUG event，包含：

- request id
- model
- endpoint 的 host/path（不含 query）
- 完整 prompt messages（包括 system instruction 與 user message）

在 LLM response parse 完成後輸出一筆 DEBUG event，包含：

- 同一 request id
- 完整 provider response content/JSON，保留足以判斷模型實際回傳的內容
- parsed intent、confidence 及 latency 等既有安全摘要

LLM error 只輸出既有分類錯誤摘要；如 provider 回應本身被納入 debug error，必須先經過同一套敏感資料遮罩，不直接輸出 exception message。

### 3. MCP debug events

在 middleware MCP adapter 發出 `initialize` 或 `tools/call` 時，DEBUG event 額外包含完整 JSON-RPC request（不包括 transport headers，因 stdio 沒有 HTTP headers）。

在收到 MCP response 後，DEBUG event 額外包含完整 JSON-RPC response。`tools/call` 的 arguments 與 structured result 可包含醫療預約、可預約時段及使用者自己的預約資料，DEBUG 模式下應保留這些內容供端到端除錯。

既有 INFO MCP event 仍只輸出 operation、tool、input key names、outcome、error category 及 latency。MCP stdout 仍只輸出 JSON-RPC，MCP child stderr 的處理方式不變。

### 4. Permanent credential redaction

DEBUG 允許醫療資料出現在 terminal，但下列憑證欄位不論 level 永遠不得原樣輸出：

- `PONTE_LLM_API_KEY` 及其實際值
- `Authorization`、Bearer token、Cookie/Set-Cookie
- 常見的 `api_key`、`access_token`、`refresh_token`、`client_secret`、`password`、`secret` 欄位

遮罩應在 debug value 進入 logger 前遞迴套用於 mapping、list、tuple 及字串；log formatter 不應依賴 caller 自己先遮罩。若設定的 API key 出現在 prompt、provider response 或 MCP payload 的字串中，也要以 `<redacted>` 取代。遮罩失敗時不得輸出該 debug event。

除上述憑證外，DEBUG 不主動遮罩醫療資料，因為這正是本模式的除錯目的。文件與啟動提示必須明確警告 DEBUG 可能包含醫療資料，只應在受控的本機開發 terminal 使用。

### 5. Scope boundary

DEBUG 內容事件只加在 LLM intent 與 MCP adapter；frontend、middleware HTTP server、mock backend 仍只記錄 method/path/status/bytes/latency 等安全摘要，不輸出 HTTP body、cookie、authorization 或 query。這避免同一份醫療資料在多層重複輸出，同時保留 middleware 端能完整觀察資料流的單一位置。

不建立 log file、rotation、集中式 collector 或新的第三方 logging dependency。

### 6. Configuration and documentation

文件與 `.env.example` 說明：

```dotenv
PONTE_LOG_LEVEL=INFO
```

並提供本機除錯用法：

```bash
PONTE_LOG_LEVEL=DEBUG python3 scripts/run_stack.py
```

文件需列出 DEBUG 會顯示完整 LLM/MCP content、會顯示醫療資料、credential 仍會遮罩，以及回到 `INFO` 的方式。不可把 API key 寫入 log 設定或範例輸出。

## Testing

新增或更新測試確認：

1. `INFO` 預設只輸出 safe summaries；LLM prompt/response 與 MCP request/response 不出現。
2. `PONTE_LOG_LEVEL=DEBUG` 時，LLM captured stderr 包含 prompt 與 provider response；MCP captured stderr 包含 tool arguments 與 result。
3. DEBUG 仍不包含 API key、Authorization、cookie、token 或 secret marker，包括這些 marker 被嵌在 nested payload 或 prompt/response 字串內的情況。
4. HTTP frontend、middleware、mock backend 的 DEBUG 輸出仍不包含 request/response body。
5. DEBUG logging failure 不改變 intent、MCP 或既有 API response。
6. 現有 middleware、MCP、mock backend、frontend、integration tests 及 JSON-RPC stdout transport 全部保持通過。

測試使用明確的 prompt、response、醫療資料與 secret marker，並對整段 captured output 做正向及反向 assertions。

## Non-goals

- 不新增 `raw` 設定名稱或另一套 logging 開關。
- 不在 `INFO` 或預設模式顯示 prompt、response 或醫療資料。
- 不在 DEBUG 顯示 API key、Authorization、cookie 或其他 credentials。
- 不讓 frontend/backend HTTP request body 透過 DEBUG 進入 terminal。
- 不改變 intent schema、醫療預約/查詢 API contract、MCP tool behavior 或資料儲存行為。

## Acceptance criteria

執行 `PONTE_LOG_LEVEL=INFO python3 scripts/run_stack.py` 時，terminal 只看到現有安全摘要；執行 `PONTE_LOG_LEVEL=DEBUG python3 scripts/run_stack.py` 並發出醫療 intent、MCP 預約/查詢請求時，同一 terminal 可看到完整 LLM prompt/response 及 MCP request/response（包括醫療資料）。兩種 level 都不會輸出 API key、Authorization、cookie、token 或 secret；既有測試與 JSON-RPC transport 維持通過。
