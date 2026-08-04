# Ponte Frontend MCP/API Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ] / - [x]) syntax for tracking.

**Goal:** Let frontend text input exercise bounded natural-language workflows and all fixed MCP tools through the real middleware to MCP stdio to mock backend path, with safe confirmation for state-changing tools.

**Architecture:** Keep the browser-facing POST /api/interactions/message contract. Recognized domain intents use bounded workflows, while messages beginning with mcp use a strict diagnostic parser. Both paths share ExecutionPipeline, McpExecutionStage, the fixed 21-tool MCP registry, and the real python -m MCP child. Diagnostic responses reuse the existing response renderer and add registry HTTP metadata plus backend payload details.

**Tech Stack:** Python 3.13+ standard library, existing MCP registry/rest adapter, Python unittest, vanilla ES modules, localhost process-boundary tests.

## Global Constraints

- The frontend calls only middleware; it must not call MCP or mock backend URLs.
- Tool names, methods, paths, headers, required fields, and envelopes remain controlled by MCP.registry and MCP.rest_adapter.
- Diagnostic syntax is exactly mcp <tool-name> <JSON input>; omitted JSON means {}.
- Middleware re-parses and validates every diagnostic command.
- GET diagnostic tools execute immediately; every POST diagnostic tool requires confirm_tool before dispatch.
- Confirmation stores the pending tool name/input in the middleware session; the confirmation request cannot replace them.
- Every POST call receives a generated idempotency key through the controlled context builder.
- Do not add dependencies or modify the fixed 21-tool catalog.
- Bind HTTP tests to 127.0.0.1 and use ephemeral ports and temporary backend data directories.
- Preserve DirectMcpExecutionStage and existing medical appointment confirmation behavior.
- After each implemented step, change that checkbox from [ ] to [x], per AGENTS.md.
- Keep feature commits separate: feat: extend natural language workflows; feat: add frontend MCP diagnostic commands.

## File Map

- Modify: middleware/intent.py, middleware/controller.py, middleware/server.py
- Create: middleware/diagnostics.py, middleware/tests/test_diagnostics.py
- Modify: middleware/tests/test_intent.py, middleware/tests/test_controller.py, middleware/tests/test_server.py
- Modify: tests/test_full_stack_integration.py, tests/test_frontend_static.py
- Modify: frontend/index.html, frontend/README.md, README.md

---

### Task 1: Extend natural-language workflows (feature commit 1)

**Files:**
- Modify: middleware/intent.py
- Modify: middleware/controller.py
- Modify: middleware/server.py
- Modify: middleware/tests/test_intent.py
- Modify: middleware/tests/test_controller.py
- Modify: middleware/tests/test_server.py
- Modify: .env.example, README.md, frontend/README.md for the new read-only examples

**Interfaces:**
- IntentName accepts medical_appointment, cash_sharing, elderly_activity, and general.
- IntentDecision exposes is_cash_sharing and is_elderly_activity alongside is_medical.
- InteractionController(..., mock_user_id="USR-DEMO-001") includes mock_user_id in generated contexts.
- create_application(..., mock_user_id="USR-DEMO-001") passes it to the controller; main() reads PONTE_MOCK_USER_ID.
- Cash-sharing natural language calls one_account.get_cash_sharing_plan with input {}.
- Elderly-activity natural language calls one_account.search_elderly_activities with input {"available_only": True}.

- [x] Step 1: Add failing intent tests

Append to middleware/tests/test_intent.py:

~~~python
def test_keyword_recognizer_matches_cash_sharing_and_activity_terms(self):
    recognizer = KeywordIntentRecognizer()
    self.assertTrue(recognizer.recognize("我想查現金分享計劃").is_cash_sharing)
    self.assertTrue(recognizer.recognize("我想找長者文娛活動").is_elderly_activity)
    self.assertFalse(recognizer.recognize("你好").is_cash_sharing)
~~~

Update the LLM test to parse {"intent":"cash_sharing","confidence":0.8}, and add an unsupported-intent error case.

Run:

~~~bash
python3 -m unittest middleware.tests.test_intent -v
~~~

Expected: FAIL because the new intent names/properties and keyword mappings do not exist.

- [x] Step 2: Implement intent normalization

In middleware/intent.py, use:

~~~python
IntentName = Literal[
    "medical_appointment",
    "cash_sharing",
    "elderly_activity",
    "general",
]
~~~

Add these domain-specific term groups before generic medical terms:

~~~python
DEFAULT_CASH_SHARING_TERMS = ("現金分享", "現金分享計劃")
DEFAULT_ELDERLY_ACTIVITY_TERMS = ("長者活動", "文娛活動", "興趣班")
DEFAULT_MEDICAL_TERMS = ("醫療", "預約", "覆診", "睇醫生", "改期")
~~~

Update the LLM prompt and normalization to accept cash_sharing/cash and elderly_activity/activity aliases while preserving medical/general aliases and fallback behavior.

- [x] Step 3: Run intent tests

Run:

~~~bash
python3 -m unittest middleware.tests.test_intent -v
~~~

Expected: PASS for existing medical/general and new cash-sharing/activity cases.

- [x] Step 4: Add failing controller tests

Extend middleware/tests/test_controller.py using the existing RecordingPipeline:

~~~python
def test_cash_sharing_message_calls_one_account_tool(self):
    response = self.controller.handle_message(
        InteractionRequest("S-CASH", "我想查現金分享計劃")
    )
    self.assertEqual(response["task_state"], "completed")
    self.assertEqual(
        [call.name for call in self.pipeline.calls],
        ["one_account.get_cash_sharing_plan"],
    )
    self.assertEqual(
        self.pipeline.calls[0].arguments["context"]["mock_user_id"],
        "USR-DEMO-001",
    )

def test_activity_message_calls_activity_search_tool(self):
    response = self.controller.handle_message(
        InteractionRequest("S-ACTIVITY", "我想找長者文娛活動")
    )
    self.assertEqual(response["task_state"], "completed")
    self.assertEqual(
        [event["tool_name"] for event in response["tool_events"]],
        ["one_account.search_elderly_activities"],
    )
    self.assertEqual(
        self.pipeline.calls[0].arguments["input"],
        {"available_only": True},
    )
~~~

Add fake payloads for both tool names to RecordingPipeline.dispatch() and run:

~~~bash
python3 -m unittest middleware.tests.test_controller -v
~~~

Expected: FAIL because the controller still treats both intents as general.

- [x] Step 5: Implement workflows and shared mock-user context

In middleware/controller.py:

- For cash_sharing, call one_account.get_cash_sharing_plan with step load_cash_sharing_plan and input {}; save data under state.data["cash_sharing_plan"]; return task_state="completed" and current_step="cash_sharing_plan".
- For elderly_activity, call one_account.search_elderly_activities with step search_elderly_activities and input {"available_only": True}; save data under state.data["activities"]; return task_state="completed" and current_step="elderly_activities".
- Use the existing _result_data() safe error path for failures.

Add mock_user_id to the controller constructor and _context(). Pass it through MiddlewareApplication/create_application and read PONTE_MOCK_USER_ID in main(), defaulting to USR-DEMO-001.

- [x] Step 6: Run controller/server tests

Run:

~~~bash
python3 -m unittest middleware.tests.test_controller middleware.tests.test_server -v
~~~

Expected: PASS, including existing medical confirmation tests and mock-user context behavior.

- [x] Step 7: Document and commit feature 1

Document both read-only natural-language examples. Then run:

~~~bash
git diff --check
git diff --stat
git add middleware/intent.py middleware/controller.py middleware/server.py middleware/tests/test_intent.py middleware/tests/test_controller.py middleware/tests/test_server.py .env.example README.md frontend/README.md
git commit -m "feat: extend natural language workflows"
~~~

Expected: one commit containing only natural-language workflow and shared mock-user context changes.

### Task 2: Build the diagnostic parser foundation (parallel sub-agent)

**Files:**
- Create: middleware/diagnostics.py
- Create: middleware/tests/test_diagnostics.py

**Interfaces:**
- DiagnosticCommand(tool_name: str, input_data: dict[str, Any]) is an immutable dataclass.
- DiagnosticCommand.parse(message: str) -> DiagnosticCommand | None returns None for ordinary text; a message beginning with mcp but not matching the grammar raises DiagnosticCommandError(code, message).
- describe_diagnostic_command(registry, command) -> dict[str, Any] validates the fixed registry and returns tool_name, http_method, resolved path, and risk_level.
- diagnostic_requires_confirmation(registry, command) -> bool returns True for registry methods other than GET.
- build_diagnostic_call(command, context, step_id) -> ToolCall creates the existing envelope and accepts no arbitrary URL/header fields.

- [x] Step 1: Add failing parser and descriptor tests

Create middleware/tests/test_diagnostics.py:

~~~python
class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()

    def test_parse_read_command_with_json_input(self):
        command = DiagnosticCommand.parse(
            'mcp one_account.get_cash_sharing_plan {"year":2026}'
        )
        self.assertEqual(command.tool_name, "one_account.get_cash_sharing_plan")
        self.assertEqual(command.input_data, {"year": 2026})

    def test_parse_missing_json_as_empty_object(self):
        command = DiagnosticCommand.parse("mcp medical.list_departments")
        self.assertEqual(command.input_data, {})

    def test_non_command_returns_none(self):
        self.assertIsNone(DiagnosticCommand.parse("我想查詢醫療預約"))

    def test_malformed_command_has_safe_error(self):
        with self.assertRaises(DiagnosticCommandError) as raised:
            DiagnosticCommand.parse("mcp medical.list_departments {")
        self.assertEqual(raised.exception.code, "INVALID_DIAGNOSTIC_COMMAND")

    def test_descriptor_resolves_path_and_risk(self):
        descriptor = describe_diagnostic_command(
            self.registry,
            DiagnosticCommand("medical.get_appointment", {"appointment_id": "APT-1"}),
        )
        self.assertEqual(descriptor["http_method"], "GET")
        self.assertEqual(descriptor["path"], "/mock/medical/v1/appointments/APT-1")
        self.assertEqual(descriptor["risk_level"], "R0")

    def test_post_requires_confirmation(self):
        command = DiagnosticCommand(
            "one_account.book_government_service_center_queue",
            {
                "service_type": "general",
                "requested_date": "2026-08-20",
                "confirmation": {"confirmation_id": "demo"},
            },
        )
        self.assertTrue(diagnostic_requires_confirmation(self.registry, command))
~~~

Run:

~~~bash
python3 -m unittest middleware.tests.test_diagnostics -v
~~~

Expected: FAIL because middleware.diagnostics does not exist.

- [x] Step 2: Implement strict parser and registry helpers

Implement middleware/diagnostics.py with:

- A parser requiring the first token to be exactly mcp and the second token to be a non-empty tool name; remaining text is one JSON object.
- Missing JSON becomes {}; JSON values other than dict raise INVALID_DIAGNOSTIC_COMMAND.
- DiagnosticCommandError carries stable code and safe message.
- describe_diagnostic_command() calls registry.get() and definition.path_for(command.input_data); unknown tools and missing route fields become safe errors.
- diagnostic_requires_confirmation() uses definition.method.upper() != "GET".
- build_diagnostic_call() returns ToolCall(command.tool_name, {"context": dict(context), "input": deepcopy(command.input_data)}, step_id).

Do not call RestAdapter, construct HTTP URLs, or validate arbitrary fields here; execution remains in the existing MCP path.

- [x] Step 3: Run diagnostic unit tests

Run:

~~~bash
python3 -m unittest middleware.tests.test_diagnostics -v
~~~

Expected: PASS for parsing, safe errors, route resolution, and POST confirmation classification.

- [x] Step 4: Inspect the disjoint foundation

The sub-agent must report exactly the two created paths and public signatures. It must not modify middleware/controller.py, middleware/server.py, or frontend files; the main agent integrates those after the natural-language commit.

- [x] Step 5: Mark completed parser steps

Change completed Task 2 checkboxes from [ ] to [x] in this plan. The diagnostic feature commit will include these files plus Task 3 integration files.

---

### Task 3: Integrate diagnostic text commands and safe confirmation (feature commit 2)

**Files:**
- Modify: middleware/controller.py
- Modify: middleware/server.py
- Modify: middleware/tests/test_controller.py
- Modify: middleware/tests/test_server.py
- Modify: frontend/index.html
- Modify: frontend/README.md
- Modify: README.md
- Modify: tests/test_frontend_static.py

**Interfaces:**
- InteractionController.handle_message() recognizes DiagnosticCommand before intent recognition.
- Diagnostic GET responses contain mode="mcp_diagnostic" and data.diagnostic with backend response details.
- Diagnostic POST responses contain task_state="awaiting_confirmation", data.diagnostic and a confirm_tool action but no tool event for the pending call.
- handle_action() accepts confirm_tool and executes only the pending session command.
- Existing /api/mcp/tools/call rejects all non-GET methods with CONFIRMATION_REQUIRED.

- [x] Step 1: Add failing controller diagnostic tests

Add to middleware/tests/test_controller.py:

~~~python
def test_diagnostic_get_returns_contract_and_backend_data(self):
    response = self.controller.handle_message(
        InteractionRequest(
            "S-DIAG-1",
            'mcp medical.list_departments {"keyword":"心臟"}',
        )
    )
    self.assertEqual(response["mode"], "mcp_diagnostic")
    self.assertEqual(response["task_state"], "completed")
    self.assertEqual(response["data"]["diagnostic"]["http_method"], "GET")
    self.assertEqual(
        response["data"]["diagnostic"]["path"],
        "/mock/medical/v1/departments",
    )
    self.assertEqual(response["tool_events"][0]["tool_name"], "medical.list_departments")

def test_diagnostic_post_requires_confirmation_and_confirm_dispatches(self):
    pending = self.controller.handle_message(
        InteractionRequest(
            "S-DIAG-2",
            'mcp one_account.book_government_service_center_queue '
            '{"service_type":"general","requested_date":"2026-08-20",'
            '"confirmation":{"confirmation_id":"DEMO-CONF"}}',
        )
    )
    self.assertEqual(pending["task_state"], "awaiting_confirmation")
    self.assertEqual(pending["tool_events"], [])
    self.assertEqual(pending["actions"][0]["kind"], "confirm_tool")
    self.assertFalse(any(call.name.startswith("one_account.book_") for call in self.pipeline.calls))

    confirmed = self.controller.handle_action(
        InteractionActionRequest("S-DIAG-2", "confirm_tool", {"ignored":"value"})
    )
    self.assertEqual(confirmed["task_state"], "completed")
    self.assertEqual(
        [call.name for call in self.pipeline.calls],
        ["one_account.book_government_service_center_queue"],
    )
~~~

Add deterministic fake payloads and assert generated context has patient, authorization, mock user and idempotency key.

Run:

~~~bash
python3 -m unittest middleware.tests.test_controller -v
~~~

Expected: FAIL because the controller does not parse commands or recognize confirm_tool.

- [x] Step 2: Add failing HTTP boundary tests

In middleware/tests/test_server.py add tests for:

- A read diagnostic message returning HTTP 200 with mode="mcp_diagnostic".
- A mutating diagnostic message returning HTTP 200 with awaiting_confirmation and no backend call.
- A /api/interactions/action confirm_tool request returning the successful tool event.
- A /api/mcp/tools/call non-GET request returning HTTP 400 CONFIRMATION_REQUIRED.

Run:

~~~bash
python3 -m unittest middleware.tests.test_server -v
~~~

Expected: FAIL because the HTTP handler has no diagnostic action branch and currently allows some direct POST tools.

- [x] Step 3: Implement controller diagnostic routing and response shape

In handle_message(), call DiagnosticCommand.parse(request.message) before intent recognition. If a command is returned:

1. Call describe_diagnostic_command.
2. For POST, save a deep-copied pending record in state.data["pending_diagnostic"], set task_state="awaiting_confirmation", current_step="confirm_tool", and state.data["diagnostic"]; return mode="mcp_diagnostic" with confirm_tool and cancel actions.
3. For GET, build the controlled ToolCall with self._context(include_idempotency=False), dispatch through the existing pipeline, append the normal tool event via _run_tool(), and return mode="mcp_diagnostic" with data.diagnostic and data.backend_response equal to the safe result dictionary.

In handle_action():

- Add confirm_tool to the action names.
- Read only state.data["pending_diagnostic"]; ignore replacement tool/input values in request.payload.
- Dispatch the pending input with include_idempotency=True, clear the pending record, set completed/error state, and store data.backend_response.
- If cancel arrives while diagnostic is pending, clear it without dispatching and return a cancelled diagnostic response.
- Preserve medical appointment actions unchanged.

- [x] Step 4: Harden the low-level tool-call endpoint

In middleware/server.py::_call_tool(), keep registry membership and envelope validation, then reject every registry definition whose method is not GET:

~~~python
ClientRequestError(
    400,
    "CONFIRMATION_REQUIRED",
    "此 tool 必須經由前端確認 action。",
)
~~~

Continue using _safe_tool_arguments() so callers cannot inject authorization, patient, language, request ID or idempotency key.

Run:

~~~bash
python3 -m unittest middleware.tests.test_server middleware.tests.test_middleware_integration -v
~~~

Expected: PASS for existing endpoint contracts and the new non-GET safety behavior.

- [x] Step 5: Make the frontend command discoverable

In frontend/index.html add:

~~~html
<p class="field-help">測試 MCP 可輸入：mcp medical.list_departments {}</p>
~~~

Do not add a direct MCP fetch. Existing app.js sends all text through MiddlewareClient.sendMessage(); existing interaction-view.js renders tool events and nested data with text nodes; existing action rendering can send confirm_tool. Document examples and confirmation in frontend/README.md and README.md. Add static assertions in tests/test_frontend_static.py for the example command and confirm_tool.

- [x] Step 6: Run diagnostic integration tests

Run:

~~~bash
python3 -m unittest middleware.tests.test_controller middleware.tests.test_server tests.test_frontend_static -v
~~~

Expected: PASS; the frontend still exposes only middleware client code and POST confirmation remains enforced.

- [x] Step 7: Commit feature 2

Review git diff and stage only parser, diagnostic integration, frontend help and tests:

~~~bash
git add middleware/diagnostics.py middleware/tests/test_diagnostics.py middleware/controller.py middleware/server.py middleware/tests/test_controller.py middleware/tests/test_server.py frontend/index.html frontend/README.md README.md tests/test_frontend_static.py
git commit -m "feat: add frontend MCP diagnostic commands"
~~~

Expected: the second feature commit contains no unrelated refactor or natural-language-only change.

---

### Task 4: Exercise all paths through the real stack and complete verification

**Files:**
- Modify: tests/test_full_stack_integration.py
- Modify: docs/superpowers/plans/2026-08-03-ponte-full-stack-e2e.md only if existing tracking needs a new checked item

**Interfaces:**
- Full-stack tests start mock backend, middleware with its real MCP stdio child, and frontend static server.
- Tests use urllib.request.ProxyHandler({}) and temporary data directories.
- Tests assert response payloads, not private mock-backend files.

- [x] Step 1: Add full-stack natural-language coverage

Add to tests/test_full_stack_integration.py:

~~~python
def test_natural_language_cash_sharing_reaches_backend(self):
    response = self.post_middleware("/api/interactions/message", {
        "session_id": "FULL-CASH-1",
        "message": "我想查現金分享計劃",
        "source": "text",
    })
    self.assertEqual(response["task_state"], "completed")
    self.assertEqual(
        [event["tool_name"] for event in response["tool_events"]],
        ["one_account.get_cash_sharing_plan"],
    )
    self.assertEqual(response["data"]["cash_sharing_plan"]["plan"]["year"], 2026)

def test_natural_language_activity_search_reaches_backend(self):
    response = self.post_middleware("/api/interactions/message", {
        "session_id": "FULL-ACTIVITY-1",
        "message": "我想找長者文娛活動",
        "source": "text",
    })
    self.assertEqual(response["task_state"], "completed")
    self.assertEqual(
        [event["tool_name"] for event in response["tool_events"]],
        ["one_account.search_elderly_activities"],
    )
    self.assertIn("activities", response["data"]["activities"])
~~~

Run:

~~~bash
python3 -m unittest tests.test_full_stack_integration -v
~~~

Expected: FAIL until the new intent/workflow and mock-user context are wired.

- [x] Step 2: Add full-stack diagnostic read and write assertions

Assert the real middleware application owns a live process whose args contain ["-m", "MCP"]. Add assertions that:

- mcp medical.list_departments {} returns mode="mcp_diagnostic", the GET contract path, one successful event, and non-empty backend_response.data.departments.
- mcp one_account.get_cash_sharing_plan {"year":2026} returns a plan for 2026.
- A government queue POST first returns awaiting_confirmation with no booking event; posting confirm_tool returns one successful event and a queue ticket.
- Malformed diagnostic JSON returns HTTP 400 INVALID_DIAGNOSTIC_COMMAND without an MCP/backend call.

- [x] Step 3: Run full-stack tests and fix only evidence-backed failures

Run:

~~~bash
python3 -m unittest tests.test_full_stack_integration tests.test_middleware_integration -v
~~~

Trace failures at the actual boundary: request shape, middleware parsing/context, MCP protocol, REST adapter mapping, or backend contract. Make one minimal root-cause change at a time and rerun the smallest failing test before the full pair.

- [x] Step 4: Run complete verification

Run:

~~~bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s MCP/tests -v
python3 -m unittest discover -s middleware/tests -v
python3 -m compileall -q MCP middleware mock_backends frontend tests scripts
node --check frontend/app.js
node --check frontend/mcp-client.js
node --check frontend/interaction-view.js
~~~

Expected: every command exits 0 with no failing tests or compile errors.

- [x] Step 5: Perform browser/manual smoke verification

Start:

~~~bash
python3 scripts/run_stack.py
~~~

Open the printed frontend URL and verify:

- 我想查詢醫療預約 shows the existing two medical tool events.
- 我想查現金分享計劃 shows the cash-sharing event and plan data.
- mcp medical.list_departments {} shows GET contract, request id, tool event and departments.
- A diagnostic POST shows confirmation and no backend side effect until confirmed.
- Global error remains hidden after successful calls and health remains connected.

If in-app browser binding remains unavailable in this WSL environment, record that limitation and use the passing deterministic full-stack test as evidence; do not claim browser verification passed.

Verification note: the local stack runner reached ready state and was stopped cleanly, but the in-app browser runtime rejected the workspace sandbox URI file:///home/bill/tsinghua/Ponte. The deterministic full-stack tests passed; no browser visual claim is made.

- [x] Step 6: Mark completed plan steps

After reading complete test output and confirming the two feature commits contain only intended changes, change every completed checkbox in this plan to [x]. Record any environment-only browser limitation in the existing E2E plan.
