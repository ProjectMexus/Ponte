# LLM Medical Intents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split medical intent recognition into querying existing patient appointments and booking medical services, then make the complete booking-and-readback flow usable through the frontend.

**Architecture:** Keep the existing controlled MCP registry and medical mock backend contracts. Extend the intent layer with `medical_query` and `medical_booking`, route the query intent to a read-only appointment lookup, and retain the existing confirmation-gated booking sequence for the booking intent. Add a deterministic recognizer injection point for tests and a frontend renderer that turns returned services, dates, and slots into action payloads.

**Tech Stack:** Python 3.13+ standard library, `unittest`, existing MCP stdio bridge, existing mock medical HTTP backend, browser-native JavaScript and CSS.

## Global Constraints

- Use the existing OpenAI-compatible Gemini endpoint configured by `.env`; never commit `PONTE_LLM_API_KEY`.
- `medical.create_appointment` can run only after an explicit `confirm` action and must retain `consent: true`, patient context, and idempotency protection.
- Keep the existing medical backend endpoint schemas and MCP registry unchanged.
- The LLM may classify intent only; it may not select arbitrary tools, URLs, methods, headers, or bypass confirmation.
- Tests must not make real Gemini requests; inject `KeywordIntentRecognizer` or a fake recognizer/transport.
- Keep the existing in-memory session model and safe middleware error boundaries.
- Preserve unrelated user changes and do not add third-party dependencies.

---

## File and Interface Map

- Modify `middleware/intent.py`: canonical medical intent names, keyword rules, LLM classification prompt, aliases, and intent properties.
- Modify `middleware/controller.py`: separate read-only appointment lookup from booking initialization and allow injected recognizers through application construction.
- Modify `middleware/server.py`: accept an optional `IntentRecognizer` in `MiddlewareApplication` and `create_application` for deterministic tests while keeping runtime defaults unchanged.
- Modify `middleware/tests/test_intent.py`: cover both medical intents, LLM JSON parsing, and keyword fallback boundaries.
- Modify `middleware/tests/test_controller.py`: cover query-only routing and retain booking/confirmation behavior.
- Modify `tests/test_middleware_integration.py`: verify real MCP-to-backend booking persistence and later readback in a new session.
- Modify `tests/test_full_stack_integration.py`: update the browser smoke expectation to the new query-only intent and inject a deterministic recognizer.
- Modify `frontend/interaction-view.js`: render service/date/slot controls with valid middleware action payloads.
- Modify `frontend/styles.css`: style the booking date controls and service/slot action groups.
- Modify `tests/test_frontend_static.py`: assert the static frontend contains the new action-flow contract.
- Modify `.env.example`, `README.md`, `middleware/README.md`, and `frontend/README.md`: document Gemini configuration and the two medical phrases/flows.

---

### Task 1: Split medical intents and make LLM classification explicit

**Files:**
- Modify: `middleware/intent.py`
- Test: `middleware/tests/test_intent.py`

**Interfaces:**
- `IntentName` gains `medical_query` and `medical_booking`.
- `IntentDecision.is_medical_query -> bool` is true only for `medical_query`.
- `IntentDecision.is_medical_booking -> bool` is true only for `medical_booking`.
- `IntentDecision.is_medical -> bool` remains true for either medical intent.
- `KeywordIntentRecognizer.recognize(message: str) -> IntentDecision` classifies appointment-record queries separately from booking/slot searches.
- `LlmIntentRecognizer._normalize_intent(value: Any) -> IntentName` accepts the new canonical names and maps legacy `medical_appointment`, `appointment`, and `booking` to `medical_booking`.

- [x] **Step 1: Write failing intent tests**

Add tests alongside the current intent tests:

```python
    def test_keyword_recognizer_separates_my_appointments_from_booking(self):
        recognizer = KeywordIntentRecognizer()
        query = recognizer.recognize("我想查詢自己的醫療預約")
        booking = recognizer.recognize("我想預約醫療服務")
        slots = recognizer.recognize("我想查詢可預約時段")
        self.assertTrue(query.is_medical_query)
        self.assertFalse(query.is_medical_booking)
        self.assertTrue(booking.is_medical_booking)
        self.assertTrue(slots.is_medical_booking)

    def test_llm_recognizer_parses_both_medical_intents(self):
        for expected, message in (
            ("medical_query", "查詢自己的預約"),
            ("medical_booking", "預約檢查服務"),
        ):
            recognizer = LlmIntentRecognizer(
                "https://llm.example.test/v1/chat/completions",
                transport=lambda request, timeout, value=expected: {
                    "choices": [{"message": {"content": json.dumps({"intent": value})}}]
                },
            )
            self.assertEqual(recognizer.recognize(message).intent, expected)
```

Import `json` in the test module if it is not already present. Also update the existing unsupported-intent and hybrid fallback expectations to use `medical_query`/`medical_booking` where the test is exercising a medical response.

- [x] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
python3 -m unittest middleware.tests.test_intent -v
```

Expected: the new properties and intent values fail because the current recognizer only emits `medical_appointment`.

- [x] **Step 3: Implement the smallest intent-layer change**

In `middleware/intent.py`:

1. Change the `IntentName` literal to include `medical_query` and `medical_booking` and remove `medical_appointment` as a canonical emitted value.
2. Add the two properties described above and make `is_medical` return true for both values.
3. Add keyword groups with booking/slot phrases checked before query phrases so `查詢可預約時段` is booking, while `查詢自己的醫療預約` is query. Keep the existing cash-sharing, elderly-activity, and general behavior unchanged.
4. Replace the LLM system prompt's single medical category with explicit JSON instructions for `medical_query` versus `medical_booking`; say that a request about the user's existing records is query and a request to arrange a service or find available slots is booking.
5. Normalize `medical_query`, `appointment_query`, `my_appointments`, and `query_medical_appointment` to `medical_query`; normalize `medical_booking`, `medical_appointment`, `appointment`, and `booking` to `medical_booking`.

- [x] **Step 4: Run intent tests and inspect the request contract**

Run:

```bash
python3 -m unittest middleware.tests.test_intent -v
python3 -m compileall -q middleware
```

Expected: all intent tests pass; the LLM request still uses the existing OpenAI-compatible `messages` JSON shape and no API key is printed.

- [x] **Step 5: Commit the intent layer**

```bash
git add middleware/intent.py middleware/tests/test_intent.py
git commit -m "feat: split medical query and booking intents"
```

### Task 2: Route query and booking flows separately

**Files:**
- Modify: `middleware/controller.py`
- Modify: `middleware/server.py`
- Test: `middleware/tests/test_controller.py`

**Interfaces:**
- `InteractionController.handle_message` routes `medical_query` to `_handle_medical_query` and `medical_booking` to `_handle_medical_booking`.
- `_handle_medical_query(state: SessionState) -> dict[str, Any]` calls only `medical.get_my_appointments`, stores `state.data["appointments"]`, and returns a completed response with no actions.
- `_handle_medical_booking(state: SessionState) -> dict[str, Any]` contains the current appointments-plus-services initialization and returns `selecting_service`.
- `MiddlewareApplication(..., intent_recognizer: IntentRecognizer | None = None)` and `create_application(..., intent_recognizer: IntentRecognizer | None = None)` allow tests to bypass network LLM calls; `None` keeps the runtime `build_intent_recognizer()` default.

- [x] **Step 1: Write failing controller tests**

Replace the current test that treats `我想查詢醫療預約` as `selecting_service` with a query-only assertion and add a separate booking assertion:

```python
    def test_medical_query_loads_only_my_appointments(self):
        response = self.controller.handle_message(
            InteractionRequest("S-QUERY", "我想查詢自己的醫療預約")
        )
        self.assertEqual(response["task_state"], "completed")
        self.assertEqual(response["current_step"], "load_appointments")
        self.assertEqual(response["data"]["appointments"], [])
        self.assertEqual(
            [call.name for call in self.pipeline.calls],
            ["medical.get_my_appointments"],
        )

    def test_medical_booking_loads_appointments_and_services(self):
        response = self.controller.handle_message(
            InteractionRequest("S-BOOKING", "我想預約醫療服務")
        )
        self.assertEqual(response["task_state"], "selecting_service")
        self.assertEqual(
            [call.name for call in self.pipeline.calls],
            ["medical.get_my_appointments", "medical.list_appointment_services"],
        )
```

Add a `medical_query`/`medical_booking` injected recognizer test only if needed to isolate controller routing; the real `KeywordIntentRecognizer` should cover the normal messages.

- [x] **Step 2: Run controller tests and confirm failure**

Run:

```bash
python3 -m unittest middleware.tests.test_controller -v
```

Expected: the existing controller sends both query and booking messages through the same selecting-service branch.

- [x] **Step 3: Implement separate controller handlers and test injection**

In `handle_message`, keep cash-sharing and elderly-activity branches first, then route:

```python
if intent.is_medical_query:
    return self._handle_medical_query(state)
if intent.is_medical_booking:
    return self._handle_medical_booking(state)
```

Move the current medical initialization into `_handle_medical_booking`. Implement `_handle_medical_query` with the existing `_run_tool` and `_result_data` helpers, setting `task_state`, `current_step`, data, and user message without loading services. Keep the existing booking search, selection, confirmation, idempotency, and task-status code unchanged.

Add `IntentRecognizer` imports/type annotations to `middleware/server.py`. Thread the optional recognizer from `create_application` to `MiddlewareApplication` and then to `InteractionController`, without changing the default behavior when the argument is omitted.

- [x] **Step 4: Run middleware unit tests**

Run:

```bash
python3 -m unittest middleware.tests.test_intent middleware.tests.test_controller -v
```

Expected: query calls only `medical.get_my_appointments`; booking still reaches `selecting_service`; confirmation still calls `medical.create_appointment` only after `confirm`.

- [x] **Step 5: Commit the controller split**

```bash
git add middleware/controller.py middleware/server.py middleware/tests/test_controller.py
git commit -m "feat: route medical query and booking workflows"
```

### Task 3: Prove booking persistence and appointment readback through MCP

**Files:**
- Modify: `tests/test_middleware_integration.py`
- Modify: `tests/test_full_stack_integration.py`

**Interfaces:**
- Integration setup passes `KeywordIntentRecognizer()` to `create_application` so tests remain offline and deterministic.
- The existing action API sequence remains the public integration contract: `search_slots`, `select_slot`, and `confirm`.

- [x] **Step 1: Update the existing read-only smoke expectations**

In the full-stack smoke test, use `我想查詢自己的醫療預約` and assert:

```python
self.assertEqual(response["task_state"], "completed")
self.assertEqual(
    [event["tool_name"] for event in response["tool_events"]],
    ["medical.get_my_appointments"],
)
```

Pass `intent_recognizer=KeywordIntentRecognizer()` to the application setup in both integration test modules.

- [x] **Step 2: Add the persistence/readback integration assertion**

After the existing booking action sequence in `test_message_to_medical_tool_reaches_mock_backend`, capture the created appointment ID from the `medical.create_appointment` tool event, then issue a new message request with a different session:

```python
created = next(
    event for event in final_response["tool_events"]
    if event["tool_name"] == "medical.create_appointment"
)
appointment_id = created["data"]["data"]["id"]

queried = post_json(
    self.opener,
    f"http://127.0.0.1:{self.middleware.server_port}/api/interactions/message",
    {"session_id": "S-QUERY-AFTER-BOOKING", "message": "查詢自己的醫療預約", "source": "text"},
)
self.assertEqual(queried["task_state"], "completed")
self.assertIn(appointment_id, [item["id"] for item in queried["data"]["appointments"]])
```

Keep the existing `search_slots` assertion so the test also proves available slots are returned by `medical.search_appointment_slots` before the write.

- [x] **Step 3: Run the integration tests**

Run:

```bash
python3 -m unittest tests.test_middleware_integration tests.test_full_stack_integration -v
```

Expected: the real middleware → MCP stdio → REST adapter → mock backend path creates a persisted appointment and a later query reads it back; no external Gemini request is made.

- [x] **Step 4: Commit persistence coverage**

```bash
git add tests/test_middleware_integration.py tests/test_full_stack_integration.py
git commit -m "test: verify medical booking persistence and readback"
```

### Task 4: Make the frontend complete the booking actions

**Files:**
- Modify: `frontend/interaction-view.js`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend_static.py`

**Interfaces:**
- `renderResponse(response)` continues to receive the existing middleware response shape.
- `onAction({ kind: string, label: string, payload: object })` remains the callback used by `frontend/app.js` and `MiddlewareClient`.
- Service controls send `{service_id, date_from, date_to}` with `kind: "search_slots"`.
- Slot controls send `{slot_id}` with `kind: "select_slot"`.

- [x] **Step 1: Add static contract assertions**

Extend `tests/test_frontend_static.py` to load `frontend/interaction-view.js` and assert it contains the booking states and payload field names:

```python
source = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
for marker in ("selecting_service", "date_from", "date_to", "service_id", "selecting_slot", "slot_id"):
    self.assertIn(marker, source)
```

- [x] **Step 2: Run the static test and confirm the new contract is absent**

Run:

```bash
python3 -m unittest tests.test_frontend_static -v
```

Expected: the new field/state assertions fail before the renderer is updated.

- [x] **Step 3: Implement deterministic service/date/slot controls**

Refactor `renderActions` in `frontend/interaction-view.js` to receive the response data in addition to `actions`. When `response.current_step === "select_service"` or `response.task_state === "selecting_service"`:

1. Render two native date inputs with default values of today and today plus 14 days.
2. Render one action button per `response.data.services` item.
3. On service click, call `onAction` with `kind: "search_slots"` and the selected service plus the current date values.

When `response.current_step === "select_slot"` or `response.task_state === "selecting_slot"`:

1. Render one button per `response.data.slots` item.
2. On slot click, call `onAction` with `kind: "select_slot"` and that slot's `id`.

For confirmation, cancellation, human help, and diagnostic actions, keep the existing generic renderer. Update `renderResponse` to pass the full response into the renderer; no changes are needed in `frontend/app.js` because it already forwards `action.kind` and `action.payload`.

Add small CSS rules for a readable date row, service choices, and slot choices while reusing the existing `.action-button` visual language. Do not add a frontend build dependency.

- [x] **Step 4: Run frontend static and compile checks**

Run:

```bash
python3 -m unittest tests.test_frontend_static -v
python3 -m compileall -q frontend
```

Expected: all static checks pass and the browser bundle remains syntax-valid.

- [x] **Step 5: Commit the frontend action flow**

```bash
git add frontend/interaction-view.js frontend/styles.css tests/test_frontend_static.py
git commit -m "feat: add frontend medical booking controls"
```

### Task 5: Align configuration and user-facing documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `middleware/README.md`
- Modify: `frontend/README.md`

**Interfaces:**
- `.env.example` must show the complete endpoint expected by Ponte: `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`.
- `.env.example` must use `gemini-2.5-flash-lite` and leave the API key value blank.
- Documentation must distinguish the read-only phrase `我想查詢自己的醫療預約` from the booking phrase `我想預約醫療服務` and explain that available slots are returned during booking.

- [x] **Step 1: Update configuration and documentation text**

Change `.env.example` from the blank OpenAI defaults to:

```env
# Optional OpenAI-compatible intent endpoint.
# Set PONTE_LLM_API_KEY to a Gemini API key from Google AI Studio.
PONTE_LLM_API_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
PONTE_LLM_API_KEY=
PONTE_LLM_MODEL=gemini-2.5-flash-lite
```

Update README examples and acceptance wording so the read-only smoke no longer claims that a query enters `selecting_service`. Document that a booking creates a mock appointment and a later query reads it back.

- [x] **Step 2: Verify no local secret was staged and check documentation formatting**

Run:

```bash
git diff --check
git status --short
git diff -- .env.example README.md middleware/README.md frontend/README.md
```

Expected: only the intended documentation/configuration files are modified; `.env` remains ignored and no API key appears in the diff.

- [x] **Step 3: Commit configuration and documentation**

```bash
git add .env.example README.md middleware/README.md frontend/README.md
git commit -m "docs: document llm medical query and booking flows"
```

### Task 6: Run the complete verification suite

**Files:**
- Verify: all modified source, test, config, and documentation files.

- [x] **Step 1: Run focused middleware and integration tests**

```bash
python3 -m unittest middleware.tests.test_intent middleware.tests.test_controller -v
python3 -m unittest tests.test_middleware_integration tests.test_full_stack_integration -v
```

Expected: all tests pass without external network calls.

- [x] **Step 2: Run the complete repository test suite and compile check**

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s MCP/tests -v
python3 -m unittest discover -s middleware/tests -v
python3 -m compileall -q MCP middleware mock_backends frontend scripts tests
git diff --check
```

Expected: all unittest modules pass, compileall exits successfully, and `git diff --check` reports no whitespace errors.

- [x] **Step 3: Perform a local runtime smoke with the configured `.env`**

Start the stack with a persistent data directory:

```bash
python3 scripts/run_stack.py --data-dir data/mock
```

In the frontend, verify this sequence:

1. Enter `我想預約醫療服務`.
2. Choose a service, date range, and returned slot.
3. Confirm the appointment.
4. Enter `我想查詢自己的醫療預約`.
5. Verify the created appointment appears in the displayed `appointments` data and the tool events include `medical.get_my_appointments`.

Stop the stack with `Ctrl-C` after the smoke. Do not include any API key or private response content in logs or the final report.

Verification note: local configuration loading confirmed `HybridIntentRecognizer` with `LlmIntentRecognizer` and `gemini-2.5-flash-lite`. A live Gemini request was attempted without printing the key, but the external connection did not complete in the available environment; the live LLM path is therefore not claimed as externally verified. Deterministic MCP/backend integration and fallback behavior are covered by the test suite.

- [x] **Step 4: Review final status and report evidence**

Run:

```bash
git status --short
git log -6 --oneline
```

Report the changed files, test commands and results, and any runtime limitation such as Gemini quota or unavailable external LLM service. Do not claim the live LLM path passed unless the configured runtime request actually succeeded.
