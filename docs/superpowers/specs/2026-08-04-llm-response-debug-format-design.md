# LLM Response Debug Logging and JSON Formatting Design

## Goal

補足 `PONTE_LOG_LEVEL=DEBUG` 的 LLM observability：只要 provider 有返回內容，不論是正常 JSON、非 JSON、HTTP error body 或無法通過 intent schema 的 JSON，都要在 `receive_debug` 事件中記錄；只有 timeout、DNS、connection failure 等沒有 HTTP response 的情況，才記錄明確的 response-unavailable 狀態。所有 JSON 型 debug payload 改為易讀的多行縮排格式。

## Existing Context

目前 `LlmIntentRecognizer.recognize()` 在 `_transport()` 返回後先執行 `_parse_response()`，只有 parse 成功才呼叫 `log_debug_event(..., response=response)`。因此：

- provider 返回 invalid JSON、JSON schema 不符合預期時，看不到 response；
- `_request_json()` 對 HTTPError、JSON decode error 只保留固定 `IntentRecognitionError`，丟失 status/body；
- logger 以 compact JSON 將整個 payload 放在單行，長醫療 response 不易閱讀。

本次只改善 LLM DEBUG response logging 與 JSON terminal formatting，不改變 intent fallback、MCP 行為或 INFO safe summary。

## Design

### 1. Preserve provider response information

在 `middleware/intent.py` 增加內部可攜帶 response snapshot 的 intent transport error。`IntentRecognitionError` 的公開行為與錯誤文字維持不變，但可選擇保存已取得的 response snapshot，供 DEBUG logger 使用；snapshot 只包含 provider HTTP status（若有）及 response body/value，不包含 request headers。

`_request_json()` 的處理規則：

- 正常 HTTP response：讀取完整 body；若可解析為 JSON，回傳既有 mapping，供 parser 正常工作。
- HTTP error：讀取 `HTTPError` body，能解析就保存 JSON value，否則保存 decode 後文字與 status code，再轉成既有 `IntentRecognitionError`。
- HTTP 200 但 body 不是合法 JSON：保存 status 與原始 decode 後文字，再轉成既有 `IntentRecognitionError`。
- JSON 是合法但不是 object：保存 status 與 JSON value，再轉成既有 `IntentRecognitionError`。
- `URLError`、timeout、OSError 或 decode 無法取得 body：不虛構 provider response，只讓 caller 以 `response_unavailable=true` 和固定 error type 記錄。

任何保存的 body/value 都會經過既有 debug logger 的遞迴 credential redaction；不可把 exception message 原文直接寫入 log。

### 2. Always emit LLM receive DEBUG event

`recognize()` 對每次已發送的 LLM request 至多輸出一筆 `receive_debug`：

- transport 返回且 parse 成功：`response` 為完整 provider value，另附 parsed intent、confidence、latency、`outcome="success"`。
- transport 返回但 parse 或 schema validation 失敗：`response` 為完整 provider value，另附 `outcome="parse_error"`、固定 error type 與 latency。
- transport 拋出帶 response snapshot 的 `IntentRecognitionError`：`response` 為 snapshot，另附 `outcome="error"`、固定 error type 與 latency。
- transport 沒有取得 response：附 `response_unavailable=true`、`outcome="error"`、固定 error type 與 latency，不輸出 exception message。

DEBUG event 必須在現有 safe `llm/error` event 之前完成；無論 DEBUG logger 本身失敗與否，原本的 exception conversion、keyword fallback 和 HTTP response 都不受影響。INFO 永遠不渲染這些內容型欄位。

### 3. Pretty JSON terminal format

`log_debug_event()` 對 mapping/list/tuple 及 response/prompt 等 JSON 型欄位使用 `json.dumps(..., ensure_ascii=False, sort_keys=True, indent=2)`。每個 debug field 分開輸出，並讓 logger handler 為每一個續行重新加上完整 timestamp、level 與 component prefix：

```text
2026-08-04 14:35:00,000 DEBUG [llm] receive_debug
2026-08-04 14:35:00,000 DEBUG [llm]   response={
2026-08-04 14:35:00,000 DEBUG [llm]     "error": "invalid request",
2026-08-04 14:35:00,000 DEBUG [llm]     "status": 400
2026-08-04 14:35:00,000 DEBUG [llm]   }
2026-08-04 14:35:00,000 DEBUG [llm]   outcome="error"
```

這保持 terminal grep 可用，也避免長 JSON 變成一條難以閱讀的行。INFO safe events 維持現有單行格式。

### 4. Security boundary

pretty formatting 不改變既有 redaction：`PONTE_LLM_API_KEY`、Authorization/Bearer、Cookie/Set-Cookie、常見 token/secret fields 在 body、prompt、response 或 nested JSON 中仍以 `<redacted>` 顯示。醫療資料在 DEBUG 仍按已批准的 local-development 行為顯示。若 redaction 或 serialization 失敗，不輸出該 debug payload。

## Testing

新增測試確認：

1. provider 返回正常 mapping 時，DEBUG 有一筆 `receive_debug`，包含 response。
2. provider 返回 invalid schema mapping、invalid JSON body、HTTP error JSON/text body 時，DEBUG 仍包含 response snapshot、status/body 或固定 parse/error outcome。
3. transport timeout/connection failure 沒有 response 時，DEBUG 包含 `response_unavailable` 與 error type，但不包含 exception message。
4. INFO 不包含任何上述 response/body marker。
5. pretty JSON 的每行都包含 `[llm]` 或 `[mcp]` component prefix，nested JSON 可讀且 credentials 仍被遮罩。
6. 既有 LLM、MCP、HTTP integration、fallback 與 JSON-RPC tests 保持通過。

## Non-goals

- 不把 HTTP request headers、API key 或 Authorization 寫入 log。
- 不在 INFO 顯示 prompt/response/medical data。
- 不改變 LLM timeout、fallback 或 intent schema contract。
- 不把 frontend/backend HTTP body 加入 DEBUG。
- 不建立新的 log level 或 `raw` 模式。

## Acceptance criteria

當 Gemini 返回成功或錯誤 response 時，`PONTE_LOG_LEVEL=DEBUG` terminal 都能在 `receive_debug` 看到經遮罩的 response snapshot；當 request timeout 或無法連線時，能看到 response-unavailable/error type。LLM/MCP JSON payload 以多行縮排顯示，且每行保留完整 log prefix；INFO、credential redaction、fallback 及既有測試行為不變。
