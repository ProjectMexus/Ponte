# DEBUG Terminal Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `PONTE_LOG_LEVEL=DEBUG` content logging for LLM intent and MCP request/response flows while keeping INFO safe summaries and permanently masking credentials.

**Architecture:** Extend `ponte_logging.py` with a separate `log_debug_event(component, event, **fields)` path. It reads the same environment-controlled logger level, formats only at DEBUG, recursively redacts credential-shaped fields and the configured LLM API key, and writes to stderr. `middleware/intent.py` and `middleware/mcp_client.py` call it around their existing protocol boundaries; HTTP-layer loggers remain safe-summary-only. Documentation and tests make the level boundary and redaction contract executable.

**Tech Stack:** Python 3.13 standard library `logging`, `json`, `re`, `unittest`, existing stdio JSON-RPC MCP client, existing `run_stack.py` environment loading.

## Global Constraints

- `INFO` (default) outputs only the existing safe summaries.
- `DEBUG` outputs full LLM prompt/response and MCP JSON-RPC request/response, including medical data.
- API keys, Authorization/Bearer tokens, cookies, and common secret fields are masked at every level.
- DEBUG content events are limited to the LLM intent and MCP adapter; frontend, middleware HTTP server, and mock backend never log HTTP bodies.
- All logs go to stderr; MCP stdout remains JSON-RPC only.
- Do not add `raw` configuration, third-party logging dependencies, log files, rotation, collectors, or tracing backends.
- Logging failures must never change business responses or JSON-RPC transport behavior.
- Preserve unrelated existing worktree changes in `frontend/`, `middleware/session.py`, and existing tests.

---

### Task 1: Add the DEBUG logger boundary and recursive credential redaction

**Files:**
- Modify: `ponte_logging.py`
- Test: `tests/test_ponte_logging.py`

**Interfaces:**
- Produces `log_debug_event(component: str, event: str, **fields: object) -> None`.
- Keeps `log_event(component: str, event: str, **fields: object) -> None` unchanged for INFO safe summaries.
- `log_debug_event` accepts only debug content fields (`request_id`, `model`, `endpoint`, `prompt`, `response`, `request`, `result`, `intent`, `confidence`, `latency_ms`, `operation`, `tool`, `outcome`, `error_code`, `error_type`) and drops unknown fields.

- [x] **Step 1: Write failing logger tests**

Add tests to `tests/test_ponte_logging.py` that specify the exact level boundary and redaction contract:

```python
def test_debug_event_is_hidden_at_info(self):
    with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "INFO"}):
        with self.assertLogs("ponte", level="INFO") as captured:
            log_debug_event("llm", "send", prompt="PATIENT_PROMPT")
    self.assertNotIn("PATIENT_PROMPT", "\n".join(captured.output))

def test_debug_event_shows_content_and_masks_nested_credentials(self):
    with patch.dict(os.environ, {
        "PONTE_LOG_LEVEL": "DEBUG",
        "PONTE_LLM_API_KEY": "CONFIGURED_API_KEY",
    }):
        with self.assertLogs("ponte", level="DEBUG") as captured:
            log_debug_event(
                "mcp",
                "receive",
                result={
                    "patient_id": "PAT-001",
                    "authorization": "Bearer NESTED_TOKEN",
                    "nested": {"api_key": "INLINE_KEY"},
                },
                prompt="medical data CONFIGURED_API_KEY",
            )
    output = "\n".join(captured.output)
    self.assertIn("PAT-001", output)
    self.assertIn("<redacted>", output)
    for secret in ("CONFIGURED_API_KEY", "NESTED_TOKEN", "INLINE_KEY"):
        self.assertNotIn(secret, output)
```

Also add a test that an unknown field containing a medical marker is dropped and a logger failure does not escape.

- [x] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_ponte_logging -v
```

Expected: FAIL because `log_debug_event` is not exported or implemented.

- [x] **Step 3: Implement the minimal DEBUG logger API**

In `ponte_logging.py`:

1. Export `log_debug_event` in `__all__`.
2. Add a `_DEBUG_FIELDS` allowlist containing the fields in the interface above.
3. Add credential key matching for case-insensitive forms of `authorization`, `cookie`, `set-cookie`, `api_key`, `access_token`, `refresh_token`, `client_secret`, `password`, and `secret` (allow `-` and `_` separators).
4. Implement recursive `_redact_debug_value(value: object) -> object`:
   - Mapping values with credential keys become `"<redacted>"` without traversing their original value.
   - Lists and tuples are recursively copied as lists.
   - Strings are passed through `_redact_debug_text`, which replaces the configured `PONTE_LLM_API_KEY` and bearer/token-style inline values with `"<redacted>"`.
   - JSON scalars are retained; unsupported objects return `"<unserializable>"`.
5. Implement `log_debug_event` so it calls `_ensure_logger(_level_from_environment())`, returns before formatting when `not _LOGGER.isEnabledFor(logging.DEBUG)`, serializes redacted content with `json.dumps(..., ensure_ascii=False, separators=(",", ":"), sort_keys=True)`, and emits `_LOGGER.debug` with the existing component prefix. Wrap the whole function in the existing non-throwing logging guard.

Do not reuse `_safe_scalar` for content values because it would truncate or discard structured medical payloads. Never include raw exception messages in this helper.

- [x] **Step 4: Run focused tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_ponte_logging -v
```

Expected: PASS, including all existing INFO allowlist, path-redaction, level, stderr, and logger-failure tests.

- [x] **Step 5: Commit the logger unit**

```bash
git add ponte_logging.py tests/test_ponte_logging.py
git commit -m "feat: add debug terminal logging boundary"
```

### Task 2: Emit LLM prompt and response DEBUG events

**Files:**
- Modify: `middleware/intent.py`
- Test: `middleware/tests/test_intent.py`

**Interfaces:**
- Consumes `log_debug_event` from `ponte_logging.py`.
- Produces no new public API; `LlmIntentRecognizer.recognize(message: str) -> IntentDecision` remains unchanged.

- [x] **Step 1: Write failing LLM DEBUG tests**

Add tests that capture logger output under both levels:

```python
def test_llm_debug_logs_prompt_and_provider_response(self):
    recognizer = LlmIntentRecognizer(
        "https://llm.example.test/v1/chat/completions",
        api_key="CONFIGURED_API_KEY",
        model="test-model",
        transport=lambda request, timeout: {
            "choices": [{"message": {"content":
                '{"intent":"medical_query","confidence":0.91,'
                '"appointment_id":"APT-DEBUG-001"}'}}],
        },
    )
    with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "DEBUG", "PONTE_LLM_API_KEY": "CONFIGURED_API_KEY"}):
        with self.assertLogs("ponte", level="DEBUG") as captured:
            recognizer.recognize("查詢我的醫療預約 PATIENT-DEBUG-001")
    output = "\n".join(captured.output)
    self.assertIn("prompt=", output)
    self.assertIn("查詢我的醫療預約 PATIENT-DEBUG-001", output)
    self.assertIn("response=", output)
    self.assertIn("APT-DEBUG-001", output)
    self.assertNotIn("CONFIGURED_API_KEY", output)

def test_llm_debug_content_is_hidden_at_info(self):
    # Use the same transport marker and PONTE_LOG_LEVEL=INFO; assert neither
    # marker appears while safe send/receive summaries still do.
```

- [x] **Step 2: Run the focused LLM tests and verify they fail**

Run:

```bash
python3 -m unittest middleware.tests.test_intent -v
```

Expected: FAIL because the recognizer does not emit `prompt=` or `response=` DEBUG events.

- [x] **Step 3: Add LLM DEBUG calls around the existing transport boundary**

Import `log_debug_event` alongside `endpoint_label` and `log_event`.

After the existing safe `llm/send` event and before `_transport`, emit:

```python
log_debug_event(
    "llm",
    "send_debug",
    request_id=request_id,
    model=self.model,
    endpoint=endpoint_label(self.api_url),
    prompt=request_body["messages"],
)
```

After `_transport` returns and after `_parse_response` succeeds, emit a `receive_debug` event containing `request_id`, the complete `response` mapping, `intent`, `confidence`, and `latency_ms`; retain the existing safe `llm/receive` event. If parsing raises, emit no raw exception message and let the existing safe error event run.

The debug helper performs redaction and level gating; the recognizer must not manually serialize or print content. Preserve the existing exception conversion and fallback behavior.

- [x] **Step 4: Run LLM tests and verify they pass**

Run:

```bash
python3 -m unittest middleware.tests.test_intent -v
```

Expected: PASS, including existing safe-summary negative assertions and the new DEBUG/INFO boundary tests.

- [x] **Step 5: Commit the LLM unit**

```bash
git add middleware/intent.py middleware/tests/test_intent.py
git commit -m "feat: log llm debug prompt and response"
```

### Task 3: Emit MCP JSON-RPC request and response DEBUG events

**Files:**
- Modify: `middleware/mcp_client.py`
- Test: `middleware/tests/test_mcp_client.py`

**Interfaces:**
- Consumes `log_debug_event` from `ponte_logging.py`.
- Keeps `McpStdioClient.start()`, `call_tool(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]`, and JSON-RPC stdout behavior unchanged.

- [x] **Step 1: Write failing MCP DEBUG tests**

Add a test using the existing `FakeProcess` that sets `PONTE_LOG_LEVEL=DEBUG`, calls `medical.list_departments` or another medical tool with a visible medical marker plus a nested authorization marker, and asserts:

```python
output = "\n".join(captured.output)
self.assertIn('"method":"tools/call"', output)
self.assertIn("PATIENT-DEBUG-001", output)
self.assertIn("APPOINTMENT-DEBUG-001", output)
self.assertNotIn("BEARER_DEBUG_TOKEN", output)
self.assertIn("<redacted>", output)
```

Add an INFO-level test (or extend the existing safe test) asserting that the same JSON-RPC strings and medical values remain absent at INFO.

- [x] **Step 2: Run the focused MCP tests and verify they fail**

Run:

```bash
python3 -m unittest middleware.tests.test_mcp_client -v
```

Expected: FAIL because no debug JSON-RPC fields are currently emitted.

- [x] **Step 3: Add DEBUG calls around each outbound/inbound JSON-RPC pair**

Import `log_debug_event`.

In `start()`, assign the initialize request to a local mapping, emit a `send_debug` event with `request=initialize_request`, call `_request`, then emit a `receive_debug` event with `response=response` before protocol validation. Keep the initialized notification unlogged as it has no response and existing safe initialize summary remains sufficient.

In `call_tool()`, assign the tools/call mapping to a local mapping, emit `send_debug` with `request=request`, call `_request`, and immediately emit `receive_debug` with `response=response` before extracting `result`. This ensures tool success and tool-error responses are visible while preserving the current error mapping. Do not log exception strings or details outside the redacting helper.

The `log_debug_event` calls must not change `stderr=subprocess.DEVNULL`, `_write`, `_read_response`, or the MCP JSON-RPC stream.

- [x] **Step 4: Run MCP tests and verify they pass**

Run:

```bash
python3 -m unittest middleware.tests.test_mcp_client -v
```

Expected: PASS, including protocol, timeout, tool-error, safe INFO, and DEBUG redaction tests.

- [x] **Step 5: Commit the MCP unit**

```bash
git add middleware/mcp_client.py middleware/tests/test_mcp_client.py
git commit -m "feat: log mcp debug request and response"
```

### Task 4: Document DEBUG usage and update configuration tests

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `middleware/README.md`
- Test: `tests/test_run_stack.py`

**Interfaces:**
- Documents the existing `PONTE_LOG_LEVEL` variable; no new environment variable is introduced.

- [x] **Step 1: Update documentation assertions first**

Change `tests/test_run_stack.py::test_terminal_logging_configuration_is_documented` so it expects DEBUG guidance instead of the old claim that higher levels can never show LLM content:

```python
self.assertIn("PONTE_LOG_LEVEL=DEBUG python3 scripts/run_stack.py", document)
self.assertIn("prompt", document)
self.assertIn("response", document)
self.assertIn("medical data", document)
self.assertIn("API key", document)
self.assertIn("INFO", document)
```

- [x] **Step 2: Run the documentation test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_run_stack.RunStackTests.test_terminal_logging_configuration_is_documented -v
```

Expected: FAIL because the existing documents still describe safe-only logging at all levels.

- [x] **Step 3: Update `.env.example` and both READMEs**

Keep `PONTE_LOG_LEVEL=INFO` in `.env.example` and add a comment that `DEBUG` is for a controlled local terminal only. In both READMEs, replace the safe-only/higher-level claim with:

```text
PONTE_LOG_LEVEL=DEBUG python3 scripts/run_stack.py
```

Explain that INFO shows safe summaries, DEBUG shows full LLM prompt/response and MCP request/response including medical data, HTTP bodies remain excluded, and API key/Authorization/Cookie/token fields remain masked. Include the command to return to INFO and retain the existing component grep example.

- [x] **Step 4: Run documentation tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_run_stack -v
```

Expected: PASS.

- [x] **Step 5: Commit the documentation unit**

```bash
git add .env.example README.md middleware/README.md tests/test_run_stack.py
git commit -m "docs: explain debug terminal content logging"
```

### Task 5: Run the complete verification matrix and update the plan

**Files:**
- Modify: `docs/superpowers/plans/2026-08-04-debug-terminal-observability.md`

- [x] **Step 1: Run focused tests for all changed behavior**

```bash
python3 -m unittest tests.test_ponte_logging middleware.tests.test_intent middleware.tests.test_mcp_client tests.test_run_stack -q
```

Expected: all focused tests pass.

- [x] **Step 2: Run all repository test suites**

```bash
PONTE_LOG_LEVEL=INFO python3 -m unittest discover -s tests -q
PONTE_LOG_LEVEL=INFO python3 -m unittest discover -s MCP/tests -q
PONTE_LOG_LEVEL=INFO python3 -m unittest discover -s middleware/tests -q
```

Expected: all existing suites pass, including HTTP and JSON-RPC integration tests.

- [x] **Step 3: Run static checks**

```bash
python3 -m compileall -q MCP middleware mock_backends frontend scripts tests
node --check frontend/interaction-view.js
git diff --check
```

Expected: all commands exit 0.

- [x] **Step 4: Run a DEBUG smoke check**

Use the existing fake-transport unit tests or start the local stack with `PONTE_LOG_LEVEL=DEBUG`, issue one medical intent and one MCP medical call, and verify terminal output contains `prompt=`, `response=`, JSON-RPC `request/response`, and the medical marker while excluding the configured API key and Authorization token.

- [x] **Step 5: Mark completed steps and commit the plan update**

Mark each completed checkbox in this plan with `x`, record the exact test commands/results in the final handoff, then commit only the plan update if it is not already included in the final implementation commit:

```bash
git add docs/superpowers/plans/2026-08-04-debug-terminal-observability.md
git commit -m "docs: complete debug observability implementation plan"
```
