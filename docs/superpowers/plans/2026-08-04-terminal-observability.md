# Terminal Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在同一個 terminal 中呈現 frontend、middleware/intent、MCP adapter 及 mock backend 的安全請求摘要，並讓 LLM 僅輸出 metadata、解析結果與 latency。

**Architecture:** 新增 repository-root 的 `ponte_logging.py`，以 standard-library logging 統一輸出到 stderr，並以 `PONTE_LOG_LEVEL` 控制級別。LLM 與 MCP 由 middleware 端記錄安全摘要；HTTP handlers 記錄各自的 method/path/status/latency；MCP server stdout 維持純 JSON-RPC，`run_stack.py` 讓 child processes 繼承相同環境與 terminal streams。

**Tech Stack:** Python 3 standard library `logging`, `time`, `urllib.parse`、既有 `unittest` 測試、既有 `scripts/run_stack.py`，不新增第三方 dependency。

## Global Constraints

- Logger 寫到 stderr，避免干擾 MCP server stdout 的 JSON-RPC stream。
- 預設使用 `INFO`，由 `PONTE_LOG_LEVEL` 控制級別；未知值回退至 `INFO`。
- 絕不記錄 API key、Authorization header、cookie、完整 URL query、prompt、response、患者姓名、患者 ID、病歷內容、預約 payload 或原始 exception body。
- 即使提高 `PONTE_LOG_LEVEL`，也不提供 raw LLM content 開關，維持 safe-by-default。
- MCP server stdout 維持只輸出 JSON-RPC；本次的 MCP diagnostics 由 middleware 端 adapter 以安全摘要輸出。
- logging 發生問題時不得影響原本的 business request 或 JSON-RPC response。
- 不改變 intent schema、醫療查詢/預約 API contract 或 MCP tool behavior。
- 不需要新增第三方 logging dependency。
- 既有 middleware、MCP、mock backend、frontend 與 integration tests 必須保持通過。

## File Map

- Create `ponte_logging.py`: component whitelist、level parsing、stderr handler、safe scalar formatting 及 endpoint summary。
- Create `tests/test_ponte_logging.py`: shared logger 的 level、格式、field allowlist 與 failure isolation 測試。
- Modify `middleware/intent.py`: LLM send/receive/error 與 hybrid source/fallback summaries。
- Modify `middleware/tests/test_intent.py`: LLM/keyword fallback logs 的安全摘要測試。
- Modify `middleware/mcp_client.py`: initialize 與 `tools/call` 的 MCP adapter summaries；保留 child stderr 為 `DEVNULL`。
- Modify `middleware/tests/test_mcp_client.py`: MCP operation、tool/input key、success/error、latency logs 測試。
- Modify `frontend/server.py`: static asset request summaries。
- Modify `middleware/server.py`: API request start/end summaries。
- Modify `mock_backends/server.py`: backend request summaries。
- Create `tests/test_terminal_observability.py`: 三個 HTTP layer 的 captured logging 與 negative secret assertions。
- Modify `scripts/run_stack.py`: 在啟動 child processes 前載入 `.env`，使 `PONTE_LOG_LEVEL` 一致傳入整個 stack。
- Modify `tests/test_run_stack.py`: 驗證 runner 保留並傳遞 logging environment。
- Modify `.env.example`, `README.md`, `middleware/README.md`: 記錄 logging 設定、component prefix、safe-by-default 保證與 terminal filter 範例。

---

### Task 1: 建立 safe shared terminal logger

**Files:**
- Create: `ponte_logging.py`
- Test: `tests/test_ponte_logging.py`

**Interfaces:**
- Produces `log_event(component: str, event: str, **fields: object) -> None`。
- Produces `endpoint_label(url: str) -> str`，只返回 URL 的 host/path，不包含 query 或 fragment。
- Supported components are exactly `frontend`, `middleware`, `llm`, `mcp`, and `backend`。
- Supported fields are exactly `request_id`, `model`, `endpoint`, `message_count`, `message_chars`, `intent`, `confidence`, `latency_ms`, `source`, `fallback_reason`, `method`, `path`, `status`, `bytes`, `operation`, `tool`, `input_keys`, `outcome`, `error_code`, and `error_type`。

- [ ] **Step 1: Write the failing logger tests**

```python
import os
import unittest
from unittest.mock import patch

from ponte_logging import endpoint_label, log_event


class PonteLoggingTests(unittest.TestCase):
    def test_event_has_component_and_only_safe_fields(self):
        with self.assertLogs("ponte", level="INFO") as captured:
            log_event(
                "llm",
                "send",
                request_id="LLM-ABC",
                model="gemini-2.5-flash-lite",
                message_chars=12,
                prompt="PATIENT_SECRET_PROMPT",
                api_key="SECRET_KEY",
            )

        output = "\n".join(captured.output)
        self.assertIn("[llm]", output)
        self.assertIn("model=gemini-2.5-flash-lite", output)
        self.assertNotIn("PATIENT_SECRET_PROMPT", output)
        self.assertNotIn("SECRET_KEY", output)
        self.assertNotIn("prompt=", output)
        self.assertNotIn("api_key=", output)

    def test_endpoint_label_removes_query_and_fragment(self):
        self.assertEqual(
            endpoint_label("https://llm.example/v1/chat?api_key=SECRET#x"),
            "llm.example/v1/chat",
        )

    def test_unknown_level_falls_back_to_info(self):
        with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "NOT_A_LEVEL"}):
            with self.assertLogs("ponte", level="INFO") as captured:
                log_event("backend", "request_end", status=200)
        self.assertTrue(captured.output)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python3 -m unittest tests.test_ponte_logging -v`

Expected: FAIL because `ponte_logging.py` and its exported interfaces do not exist yet.

- [ ] **Step 3: Implement the minimal shared logger**

Implement `ponte_logging.py` with these exact behaviors:

1. Keep one logger named `ponte`, one stderr `StreamHandler`, and one formatter containing `%(asctime)s %(levelname)s [%(component)s] %(message)s`.
2. On every `log_event` call, read `PONTE_LOG_LEVEL`, map valid names through `logging._nameToLevel`, and use `logging.INFO` for missing or unknown values.
3. Drop fields not in the supported-field set before formatting. Never accept mappings, lists, or arbitrary exception messages as field values; convert permitted scalar values to one line and cap strings at 120 characters.
4. Normalize `endpoint` with `urlsplit`, remove query/fragment, and normalize `path` similarly. Format `None` as `none`, booleans as lowercase `true`/`false`, and floats with at most six decimal places.
5. Wrap logger setup and emission in `try/except Exception: return` so logging cannot break a request or JSON-RPC response. Use `extra={"component": component}` only after validating the component.

The emitted line must look like:

```text
2026-08-04 12:00:00,000 INFO [llm] send request_id=LLM-ABC model=gemini-2.5-flash-lite message_chars=12
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python3 -m unittest tests.test_ponte_logging -v`

Expected: all logger tests PASS, including the negative assertions for API key and prompt markers.

- [ ] **Step 5: Commit the shared logger**

```bash
git add ponte_logging.py tests/test_ponte_logging.py
git commit -m "feat: add safe terminal logging helper"
```

### Task 2: Instrument LLM intent and hybrid fallback

**Files:**
- Modify: `middleware/intent.py:129-297`
- Test: `middleware/tests/test_intent.py`

**Interfaces:**
- Consumes `log_event` and `endpoint_label` from Task 1.
- Produces `llm send`, `llm receive`, `llm error`, and `middleware intent_decision` events with no raw message or response content.
- Preserves `IntentDecision`, `IntentRecognitionError`, and all existing recognizer behavior.

- [ ] **Step 1: Add failing LLM summary tests**

Extend the existing transport-based tests with a secret marker in the user message and response transport, then assert:

```python
with self.assertLogs("ponte", level="INFO") as captured:
    decision = recognizer.recognize("PATIENT_SECRET_MESSAGE")

output = "\n".join(captured.output)
self.assertEqual(decision.intent, "medical_query")
self.assertIn("[llm]", output)
self.assertIn("send", output)
self.assertIn("receive", output)
self.assertIn("intent=medical_query", output)
self.assertIn("confidence=0.9", output)
self.assertNotIn("PATIENT_SECRET_MESSAGE", output)
self.assertNotIn('response_secret', output)
self.assertNotIn("Authorization", output)
```

Add a hybrid fallback assertion that captures `[middleware] intent_decision`, checks `source=keyword` and `fallback_reason=llm_error`, and verifies the original failure message is absent.

- [ ] **Step 2: Run the intent tests and verify the new assertions fail**

Run: `python3 -m unittest middleware.tests.test_intent -v`

Expected: existing intent behavior passes, while the new log assertions fail because no intent events are emitted.

- [ ] **Step 3: Add safe LLM events**

In `LlmIntentRecognizer.recognize`:

1. Generate `request_id = "LLM-" + uuid.uuid4().hex[:12].upper()` and capture `time.monotonic()` before building the transport call.
2. Emit `log_event("llm", "send", request_id=..., model=self.model, endpoint=endpoint_label(self.api_url), message_count=len(request_body["messages"]), message_chars=len(message))`.
3. After `_parse_response`, emit `log_event("llm", "receive", request_id=..., intent=decision.intent, confidence=decision.confidence, latency_ms=...)` and return the decision.
4. For `IntentRecognitionError` and unexpected exceptions, emit `log_event("llm", "error", request_id=..., outcome="error", error_code="llm_intent_error", error_type=type(error).__name__, latency_ms=...)`; re-raise the existing safe `IntentRecognitionError` contract without logging its message.

In `HybridIntentRecognizer.recognize`, emit one middleware decision event for each result: `source=llm` on success; `source=keyword`, `fallback_reason=llm_error` on LLM failure; and `source=keyword`, `fallback_reason=llm_not_configured` when no LLM exists. Include only the normalized `intent` and `confidence`.

- [ ] **Step 4: Run all intent tests**

Run: `python3 -m unittest middleware.tests.test_intent -v`

Expected: all existing parsing/fallback tests and new safe-summary tests PASS.

- [ ] **Step 5: Commit intent observability**

```bash
git add middleware/intent.py middleware/tests/test_intent.py
git commit -m "feat: log safe llm intent summaries"
```

### Task 3: Instrument the middleware MCP adapter

**Files:**
- Modify: `middleware/mcp_client.py:73-173`
- Test: `middleware/tests/test_mcp_client.py`

**Interfaces:**
- Consumes `log_event` from Task 1.
- Produces `[mcp]` events for initialize and `tools/call` using MCP request IDs, tool names, input key names, outcome/error category, and latency.
- Leaves `MCP/server.py` unchanged and keeps `stderr=subprocess.DEVNULL`; no JSON-RPC body is written to terminal.

- [ ] **Step 1: Add failing MCP log tests**

Wrap the existing successful and error `call_tool` tests with `assertLogs("ponte", level="INFO")`. Assert the output contains `operation=tools/call`, `tool=medical.list_departments`, `input_keys=context,input`, and `outcome=success` (or `outcome=error` plus `error_code=SLOT_NOT_AVAILABLE`), while excluding a test argument value such as `PATIENT_SECRET` and the serialized JSON-RPC key `"jsonrpc"`.

- [ ] **Step 2: Run the focused MCP tests and verify the new assertions fail**

Run: `python3 -m unittest middleware.tests.test_mcp_client -v`

Expected: existing protocol tests pass, and only the new logging assertions fail.

- [ ] **Step 3: Add MCP start/call summaries**

In `McpStdioClient.start`, measure the initialize handshake and emit `log_event("mcp", "send", request_id=f"MCP-{self._next_id}", operation="initialize", input_keys="capabilities,clientInfo,protocolVersion")` before `_request`, followed by `receive` with `outcome=success` and latency. On an `AdapterError` or startup exception, emit `error` with a fixed `error_code` or `error_type` and latency before preserving the current exception behavior.

In `call_tool`, after validating the fixed tool name and mapping arguments, emit `send` with `operation="tools/call"`, the numeric MCP request ID, the validated tool name, and a sorted comma-separated list of top-level argument keys. Emit `receive` with `outcome=success` after a structured payload is returned. Catch `AdapterError` and unexpected exceptions only to emit safe `error`/`receive` summaries (`error_code` or exception class name), then re-raise unchanged. Do not pass `arguments`, `response`, `details`, or exception messages to `log_event`.

- [ ] **Step 4: Run all MCP client tests**

Run: `python3 -m unittest middleware.tests.test_mcp_client -v`

Expected: all MCP start, success, timeout, EOF, malformed response, ID mismatch and tool error tests PASS, with safe log assertions included.

- [ ] **Step 5: Commit MCP observability**

```bash
git add middleware/mcp_client.py middleware/tests/test_mcp_client.py
git commit -m "feat: log safe mcp adapter summaries"
```

### Task 4: Add HTTP summaries for frontend, middleware, and backend

**Files:**
- Modify: `frontend/server.py:12-28`
- Modify: `middleware/server.py:124-223,304-305`
- Modify: `mock_backends/server.py:86-160`
- Create: `tests/test_terminal_observability.py`

**Interfaces:**
- Consumes `log_event` from Task 1.
- Produces `[frontend]`, `[middleware]`, and `[backend]` request summaries with method/path/status/bytes or latency, never request body/header/query values.
- Preserves all existing HTTP status codes, response payloads and handler routing.

- [ ] **Step 1: Add failing HTTP log tests**

Create a `unittest` fixture that starts the existing `create_http_server` functions on port `0`, uses a temporary backend data directory, and sends:

```python
GET /                         # frontend
GET /api/mcp/tools            # middleware with RecordingMcpClient
GET /mock/medical/v1/departments  # mock backend
```

For each request, use `with self.assertLogs("ponte", level="INFO")` and assert the corresponding component, method, path, status and `latency_ms`/`bytes`. Send a body/header marker `PATIENT_SECRET_HTTP_VALUE` in one middleware/backend request and assert that the captured output contains neither that marker nor `Authorization`.

- [ ] **Step 2: Run the new HTTP logging test and verify it fails**

Run: `python3 -m unittest tests.test_terminal_observability -v`

Expected: the requests still return their existing payloads, but the new log assertions fail because the handlers currently suppress access logging.

- [ ] **Step 3: Implement frontend request logging**

Replace `_StaticRequestHandler.log_message` with a safe `log_request` override. Use `urlsplit(self.path).path`, `self.command`, the status code supplied by `SimpleHTTPRequestHandler`, the supplied response size, and `time.monotonic()` captured at the beginning of each request. Emit `log_event("frontend", "request_end", method=..., path=..., status=..., bytes=..., latency_ms=...)`. Do not log `self.headers`, cookies, query values, or file contents.

- [ ] **Step 4: Implement middleware request logging**

At the start of `_handle`, generate a handler-local ID with `f"HTTP-MW-{uuid.uuid4().hex[:12].upper()}"`, capture `time.monotonic()`, derive only `urlsplit(self.path).path`, and emit `request_start`. Set `self._response_status` in `_send_json`; in a `finally` block in `_handle`, emit `request_end` with method/path/status/request ID/latency. Use status `500` if response construction itself fails. Keep `_send_json`, `_send_error`, CORS behavior and all existing response contracts unchanged.

- [ ] **Step 5: Implement mock backend request logging**

At the start of `_handle`, retain the existing internal request ID, capture `time.monotonic()`, and emit `request_start` with method/path/request ID. In `_send`, set handler-local response status and byte count from the existing `BackendResponse`; in a `finally` block emit `request_end` with method/path/status/request ID/latency. Keep the parsed query and body inside the business request only; never pass them to `log_event`.

- [ ] **Step 6: Run the HTTP logging and regression tests**

Run:

```bash
python3 -m unittest tests.test_terminal_observability -v
python3 -m unittest tests.test_frontend_static middleware.tests.test_server -v
```

Expected: safe terminal assertions PASS and existing frontend/middleware HTTP behavior remains unchanged.

- [ ] **Step 7: Commit HTTP observability**

```bash
git add frontend/server.py middleware/server.py mock_backends/server.py tests/test_terminal_observability.py
git commit -m "feat: log safe http request summaries"
```

### Task 5: Propagate configuration and document terminal usage

**Files:**
- Modify: `scripts/run_stack.py:118-159`
- Modify: `tests/test_run_stack.py`
- Modify: `.env.example:10-14`
- Modify: `README.md:113-140,155-170`
- Modify: `middleware/README.md:43-56`

**Interfaces:**
- Consumes existing `load_dotenv()` from `middleware.config` and `middleware_environment()`.
- Produces a stack runner that loads local `.env` before spawning backend, middleware/MCP, and frontend, while preserving shell environment precedence.
- Produces documentation for `PONTE_LOG_LEVEL=INFO`, component prefixes and safe-summary guarantees.

- [ ] **Step 1: Add failing runner/config documentation assertions**

Extend `tests/test_run_stack.py` with a `middleware_environment` assertion that an existing `PONTE_LOG_LEVEL=DEBUG` value is preserved, and add a source/documentation assertion that `.env.example` contains `PONTE_LOG_LEVEL=INFO` and README documents `frontend`, `middleware`, `llm`, `mcp`, and `backend` prefixes.

- [ ] **Step 2: Run the focused runner tests and verify the new assertions fail**

Run: `python3 -m unittest tests.test_run_stack -v`

Expected: existing runner tests pass and only the new configuration/documentation assertions fail.

- [ ] **Step 3: Load `.env` before starting the stack**

In `scripts/run_stack.py`, call `load_dotenv()` at the start of `run_stack` before constructing child environments. Keep `middleware_environment` copying the current environment and overriding only `PONTE_BACKEND_URL`; do not print any environment value. This makes the safe logger level and the already-supported Gemini intent settings available to every child process without exposing them.

- [ ] **Step 4: Add the documented configuration and terminal examples**

Add this line to `.env.example`:

```dotenv
PONTE_LOG_LEVEL=INFO
```

Document in both READMEs:

```bash
PONTE_LOG_LEVEL=INFO python3 scripts/run_stack.py
rg '\\[(frontend|middleware|llm|mcp|backend)\\]' ponte-terminal.log
```

Explain that logs show only safe metadata such as method/path/status, model/endpoint metadata, message character counts, normalized intent, tool name/input keys, outcome and latency; raw LLM content, credentials and medical payloads are never enabled by log level.

- [ ] **Step 5: Run runner tests and documentation checks**

Run:

```bash
python3 -m unittest tests.test_run_stack -v
rg -n "PONTE_LOG_LEVEL|frontend|middleware|llm|mcp|backend|raw|API key" .env.example README.md middleware/README.md
```

Expected: all runner tests PASS and the documented configuration/filter/safety text is present.

- [ ] **Step 6: Commit configuration and docs**

```bash
git add scripts/run_stack.py tests/test_run_stack.py .env.example README.md middleware/README.md
git commit -m "docs: document terminal observability configuration"
```

### Task 6: Full verification and terminal smoke check

**Files:**
- Modify only files needed to correct a failing test discovered in Tasks 1-5.

- [ ] **Step 1: Run the complete Python test suites**

Run:

```bash
python3 -m unittest discover -s tests -q
python3 -m unittest discover -s MCP/tests -q
python3 -m unittest discover -s middleware/tests -q
```

Expected: every suite exits with status 0; HTTP suites may require the local-socket test permission already used by this repository.

- [ ] **Step 2: Run syntax and static checks**

Run:

```bash
python3 -m compileall -q MCP middleware mock_backends frontend scripts tests
node --check frontend/interaction-view.js
git diff --check
```

Expected: no compiler, JavaScript syntax, or whitespace errors.

- [ ] **Step 3: Perform the safe-summary smoke test**

Start the stack with `PONTE_LOG_LEVEL=INFO python3 scripts/run_stack.py` in a terminal, send a frontend asset request and the existing read-only medical query through the browser or curl, and inspect the same terminal. Confirm prefixes `[frontend]`, `[middleware]`, `[llm]` when configured (or keyword fallback), `[mcp]`, and `[backend]`; confirm no API key, Authorization value, prompt, response body, patient data, or appointment payload appears.

- [ ] **Step 4: Review the final diff and status**

Run:

```bash
git diff HEAD~5..HEAD --stat
git status --short
```

Review that only observability files are in the feature commits and preserve any pre-existing unrelated working-tree changes.
