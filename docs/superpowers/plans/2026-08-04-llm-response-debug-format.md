# LLM Response Debug Logging and JSON Formatting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every LLM request attempt emits a DEBUG receive event with any available provider response, including error bodies, and render DEBUG JSON payloads as readable prefixed multi-line JSON.

**Architecture:** Keep `log_debug_event(component, event, **fields)` as the only content logger. Extend it to render each field with indented JSON and make the shared stderr handler prefix every continuation line. Extend `IntentRecognitionError` with an optional response snapshot, preserve HTTP error/invalid-body data in `_request_json`, and centralize one receive-debug emission per LLM attempt before the existing safe error/fallback path.

**Tech Stack:** Python 3.13 standard library `logging`, `json`, `re`, `urllib.error`, `unittest`, `io`; existing OpenAI-compatible HTTP transport and middleware intent recognizer.

## Global Constraints

- A provider response is logged in DEBUG whether it is valid JSON, invalid JSON, an HTTP error body, or an invalid intent schema.
- No HTTP response is represented as `response_unavailable=true` with fixed error type; exception messages are never logged verbatim.
- DEBUG JSON uses `json.dumps(..., ensure_ascii=False, sort_keys=True, indent=2)` and every continuation line keeps the full timestamp/level/component prefix.
- INFO safe summaries remain single-line and never include prompt, response, medical data, HTTP body, or credentials.
- `PONTE_LLM_API_KEY`, Authorization/Bearer, Cookie/Set-Cookie, and common token/secret fields remain recursively redacted.
- DEBUG logger failures cannot alter intent conversion, keyword fallback, HTTP responses, or MCP JSON-RPC transport.
- Do not add a new level, `raw` mode, third-party dependency, log file, or unrelated refactor.

---

### Task 1: Render DEBUG JSON as readable prefixed multi-line output

**Files:**
- Modify: `ponte_logging.py`
- Test: `tests/test_ponte_logging.py`

**Interfaces:**
- Keeps `log_debug_event(component: str, event: str, **fields: object) -> None` unchanged.
- `log_debug_event` emits one event whose content fields are separated onto multiple lines.
- `_PonteStreamHandler.format(record: logging.LogRecord) -> str` prefixes every rendered continuation line with the same timestamp, level, and component.

- [x] **Step 1: Write failing formatting tests**

Add tests that capture actual stderr under `PONTE_LOG_LEVEL=DEBUG` and assert the JSON is indented and every output line has the complete prefix:

```python
def test_debug_json_is_pretty_and_each_line_has_component_prefix(self):
    stderr = io.StringIO()
    with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "DEBUG"}):
        with contextlib.redirect_stderr(stderr):
            log_debug_event(
                "llm",
                "receive_debug",
                response={"status": 400, "error": {"message": "invalid"}},
                outcome="error",
            )

    lines = [line for line in stderr.getvalue().splitlines() if line]
    self.assertGreater(len(lines), 4)
    self.assertTrue(all(" DEBUG [llm] " in line for line in lines))
    self.assertIn('response={', stderr.getvalue())
    self.assertIn('    "message": "invalid"', stderr.getvalue())
    self.assertIn('  outcome="error"', stderr.getvalue())
```

Retain the existing tests that assert INFO safe events remain one-line and that redaction still hides nested credentials.

- [x] **Step 2: Run the focused formatting tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_ponte_logging -v
```

Expected: FAIL because the current logger serializes JSON compactly and does not prefix continuation lines.

- [x] **Step 3: Implement pretty JSON rendering and continuation prefixes**

In `log_debug_event`:

1. Keep the existing DEBUG level gate and recursive redaction.
2. Serialize every accepted debug field with `json.dumps(redacted_value, ensure_ascii=False, sort_keys=True, indent=2)`.
3. Build the message as the component/event line followed by one `  field=` line per field; retain the JSON indentation after each `field=` label.
4. Add `response_unavailable` to `_DEBUG_FIELDS` so error events can express no response without using an unapproved field.

In `_PonteStreamHandler.format`:

1. Strip the duplicated `[component]` prefix from the record message as today.
2. Call the base formatter once to establish the timestamp/level/component prefix.
3. For a message containing newlines, derive the complete prefix from the first formatted line and prepend it to every later message line, preserving the JSON indentation.
4. Leave single-line INFO formatting unchanged.

Never log unredacted values while computing the formatted message; any serialization exception must return without emitting the DEBUG event.

- [x] **Step 4: Run formatting tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_ponte_logging -v
```

Expected: PASS, including INFO gating, redaction, stderr, path redaction, and pretty DEBUG formatting.

- [x] **Step 5: Commit the logger formatting unit**

```bash
git add ponte_logging.py tests/test_ponte_logging.py
git commit -m "feat: format debug json logs for terminal"
```

### Task 2: Preserve and always log LLM provider responses

**Files:**
- Modify: `middleware/intent.py`
- Test: `middleware/tests/test_intent.py`

**Interfaces:**
- Extend `IntentRecognitionError.__init__(message: str, *, response: object = _NO_RESPONSE) -> None` while preserving existing `str(error)` behavior; expose the snapshot as `error.response`.
- Keep `LlmIntentRecognizer.recognize(message: str) -> IntentDecision` and `_request_json(request: Request, timeout: float) -> Mapping[str, Any]` externally compatible.
- `_request_json` raises `IntentRecognitionError` with `response={"status": int, "body": object}` when an HTTP/JSON response was obtained but cannot be returned as a mapping.

- [x] **Step 1: Write failing response/error-path tests**

Add tests in `middleware/tests/test_intent.py` for these exact cases:

```python
def test_llm_debug_logs_invalid_schema_response(self):
    recognizer = LlmIntentRecognizer(
        "https://llm.example.test/v1/chat/completions",
        transport=lambda request, timeout: {
            "choices": [],
            "marker": "INVALID_SCHEMA_RESPONSE",
        },
    )
    with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "DEBUG"}):
        with self.assertLogs("ponte", level="DEBUG") as captured:
            with self.assertRaises(IntentRecognitionError):
                recognizer.recognize("我想預約醫療服務")
    output = "\n".join(captured.output)
    self.assertIn("INVALID_SCHEMA_RESPONSE", output)
    self.assertIn('outcome="parse_error"', output)

def test_llm_debug_logs_http_error_body(self):
    class ErrorOpener:
        def open(self, request, timeout):
            raise HTTPError(
                request.full_url,
                429,
                "rate limited",
                {},
                io.BytesIO(b'{"error":"PROVIDER_RESPONSE"}'),
            )

    recognizer = LlmIntentRecognizer(
        "https://llm.example.test/v1/chat/completions",
    )
    with patch("middleware.intent.build_opener", return_value=ErrorOpener()):
        with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "DEBUG"}):
            with self.assertLogs("ponte", level="DEBUG") as captured:
                with self.assertRaises(IntentRecognitionError):
                    recognizer.recognize("我想預約醫療服務")
    output = "\n".join(captured.output)
    self.assertIn("PROVIDER_RESPONSE", output)
    self.assertIn('"status": 429', output)

def test_llm_debug_logs_response_unavailable_without_exception_message(self):
    recognizer = LlmIntentRecognizer(
        "https://llm.example.test/v1/chat/completions",
        transport=lambda request, timeout: (_ for _ in ()).throw(
            RuntimeError("NETWORK_EXCEPTION_SECRET")
        ),
    )
    with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "DEBUG"}):
        with self.assertLogs("ponte", level="DEBUG") as captured:
            with self.assertRaises(IntentRecognitionError):
                recognizer.recognize("我想預約醫療服務")
    output = "\n".join(captured.output)
    self.assertIn("response_unavailable=true", output)
    self.assertIn('error_type="RuntimeError"', output)
    self.assertNotIn("NETWORK_EXCEPTION_SECRET", output)
```

Also add a normal-response parse-error test with a medical marker and an INFO-level assertion that all response/body markers are absent.

- [x] **Step 2: Run the response-path tests and verify they fail**

Run:

```bash
python3 -m unittest middleware.tests.test_intent -v
```

Expected: FAIL because parse errors and transport errors currently emit no `receive_debug`, and `_request_json` discards HTTP error bodies.

- [x] **Step 3: Preserve raw response snapshots in the HTTP transport**

In `middleware/intent.py`:

1. Define a private `_NO_RESPONSE = object()` sentinel before `IntentRecognitionError`.
2. Store `self.response = response` in `IntentRecognitionError`; use the sentinel to distinguish a real `None` body from no response.
3. Add a private `_decode_provider_body(raw: bytes) -> object` helper that decodes UTF-8 with replacement and returns `json.loads(text)` when valid, otherwise the text.
4. In `_request_json`, catch `HTTPError` first, read its body safely, and raise `IntentRecognitionError("LLM intent request failed", response={"status": error.code, "body": decoded_body})`.
5. For a normal HTTP response, read/decode the body before parsing. On JSON decode failure or a non-mapping JSON value, raise `IntentRecognitionError("LLM response must be a JSON object", response={"status": status, "body": decoded_body})`; on a mapping, return it unchanged.
6. For `URLError`, OSError and other body-unavailable failures, raise the existing fixed `IntentRecognitionError` without a response snapshot. Do not include exception messages in the error text or snapshot.

- [x] **Step 4: Emit exactly one receive DEBUG event for every attempt**

Refactor `LlmIntentRecognizer.recognize` around a local `response = _NO_RESPONSE`:

```python
try:
    response = self._transport(request, self.timeout)
    try:
        decision = self._parse_response(response)
    except Exception as parse_error:
        log_debug_event(
            "llm", "receive_debug", request_id=request_id,
            response=response, outcome="parse_error",
            error_type=type(parse_error).__name__,
            latency_ms=round((time.monotonic() - started_at) * 1000),
        )
        raise
    latency_ms = round((time.monotonic() - started_at) * 1000)
    log_debug_event(
        "llm", "receive_debug", request_id=request_id,
        response=response, outcome="success", intent=decision.intent,
        confidence=decision.confidence, latency_ms=latency_ms,
    )
except IntentRecognitionError as error:
    snapshot = getattr(error, "response", _NO_RESPONSE)
    if snapshot is _NO_RESPONSE:
        log_debug_event(
            "llm", "receive_debug", request_id=request_id,
            response_unavailable=True, outcome="error",
            error_type=type(error).__name__,
            latency_ms=round((time.monotonic() - started_at) * 1000),
        )
    else:
        log_debug_event(
            "llm", "receive_debug", request_id=request_id,
            response=snapshot, outcome="error",
            error_type=type(error).__name__,
            latency_ms=round((time.monotonic() - started_at) * 1000),
        )
    # Keep the existing safe llm/error event and re-raise.
```

Handle the generic exception branch analogously: use the local response if transport returned one, otherwise `response_unavailable=true`; then preserve the existing `IntentRecognitionError("LLM intent request failed")` conversion. The inner parse branch must log before re-raising so the outer error branch does not produce a duplicate receive event.

- [x] **Step 5: Run LLM response tests and verify they pass**

Run:

```bash
python3 -m unittest middleware.tests.test_intent -v
```

Expected: PASS for success, invalid schema, invalid JSON, HTTP JSON/text errors, no-response errors, INFO gating, redaction, and fallback behavior.

- [x] **Step 6: Commit the LLM response unit**

```bash
git add middleware/intent.py middleware/tests/test_intent.py
git commit -m "feat: log llm responses on every outcome"
```

### Task 3: Document error responses and pretty DEBUG output

**Files:**
- Modify: `README.md`
- Modify: `middleware/README.md`
- Test: `tests/test_run_stack.py`

**Interfaces:**
- Documents the existing `PONTE_LOG_LEVEL=DEBUG` configuration; no new environment variable or public API.

- [x] **Step 1: Add failing documentation assertions**

Extend `RunStackTests.test_terminal_logging_configuration_is_documented` with:

```python
self.assertIn("provider error response", document)
self.assertIn("response_unavailable", document)
self.assertIn("multi-line", document)
self.assertIn("每行", document)
```

- [x] **Step 2: Run the documentation test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_run_stack.RunStackTests.test_terminal_logging_configuration_is_documented -v
```

Expected: FAIL because the current docs describe content logging but not error-response capture or multi-line formatting.

- [x] **Step 3: Update both READMEs without changing the security contract**

In both Terminal logging sections, state that DEBUG logs provider success/error response bodies when available, logs `response_unavailable` plus fixed error type when no body exists, formats JSON as multi-line indented records with a full prefix on every line, and still masks credentials. Retain the warning that DEBUG may contain medical data and HTTP bodies remain excluded.

- [x] **Step 4: Run documentation tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_run_stack -v
```

Expected: PASS.

- [x] **Step 5: Commit the documentation unit**

```bash
git add README.md middleware/README.md tests/test_run_stack.py
git commit -m "docs: describe llm debug error responses"
```

### Task 4: Run integration verification and finish the plan

**Files:**
- Modify: `docs/superpowers/plans/2026-08-04-llm-response-debug-format.md`

- [x] **Step 1: Run focused tests**

```bash
python3 -m unittest tests.test_ponte_logging middleware.tests.test_intent tests.test_run_stack -q
```

Expected: all focused tests pass.

- [x] **Step 2: Run complete repository suites**

```bash
PONTE_LOG_LEVEL=INFO python3 -m unittest discover -s tests -q
PONTE_LOG_LEVEL=INFO python3 -m unittest discover -s MCP/tests -q
PONTE_LOG_LEVEL=INFO python3 -m unittest discover -s middleware/tests -q
```

Expected: all suites pass; socket suites may require the approved local execution permission.

- [x] **Step 3: Run static checks**

```bash
python3 -m compileall -q MCP middleware mock_backends frontend scripts tests
node --check frontend/interaction-view.js
git diff --check
```

Expected: all commands exit 0.

- [x] **Step 4: Run a DEBUG error smoke test**

Run the LLM error-path test with `PONTE_LOG_LEVEL=DEBUG` and verify captured stderr contains a pretty `receive_debug` response/status/body or `response_unavailable`, while excluding API key, Authorization, and exception-secret markers. Also run the existing local stack DEBUG smoke to confirm MCP logs remain prefixed and unaffected.

- [x] **Step 5: Mark completed steps and commit the plan update**

Mark every completed checkbox in this plan with `x`, run `git diff --check`, and commit only the plan update:

```bash
git add docs/superpowers/plans/2026-08-04-llm-response-debug-format.md
git commit -m "docs: complete llm response debug plan"
```
