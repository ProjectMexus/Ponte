# Ponte Full-Stack MCP E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ([ ]/[x]) syntax for tracking.

**Goal:** Make the running Ponte stack verify Frontend → Middleware → MCPServer → Mock Backend through a browser-driven smoke test and deterministic process-boundary integration tests.

**Architecture:** Middleware will own one long-lived python -m MCP child process and communicate with it using newline-delimited JSON-RPC. The MCP process will continue to own the fixed registry and REST adapter, while middleware owns sessions, workflow actions, error presentation, and child-process cleanup. A local stack runner will start the mock backend, middleware, and static frontend on localhost for manual browser verification.

**Tech Stack:** Python 3.13+ standard library, subprocess, selectors, threading, http.server, urllib, unittest, newline-delimited JSON-RPC, browser UI smoke testing.

## Global Constraints

- The MCP process must be started as python -m MCP; middleware must not reimplement REST mapping or bypass the MCP protocol in production wiring.
- Tool names, REST paths, methods, headers, and input envelopes remain controlled by MCP.registry and MCP.rest_adapter.
- MCP stdout is protocol-only; child stderr must never be merged into stdout.
- The frontend continues to call only the middleware HTTP API and must not call MCP or mock backend URLs directly.
- Tests bind only to 127.0.0.1, use ephemeral ports or the documented default ports, and use temporary mock data directories.
- Existing direct adapter and MCP unit tests remain valid; DirectMcpExecutionStage remains available for isolated middleware tests.
- Do not modify the existing untracked middleware/intent.py unless a test proves the stack cannot import it.

---

### Task 1: Add a managed stdio MCP client

Files:

- Create: middleware/mcp_client.py
- Create: middleware/tests/test_mcp_client.py

Interfaces:

- Produces McpStdioClient(backend_url, *, python_executable=None, project_root=None, timeout=10.0, process_factory=None).
- Produces start() -> None, call_tool(name, arguments) -> dict[str, Any], and close() -> None.
- Produces McpClientError, a structured AdapterError subclass with codes MCP_UNAVAILABLE, MCP_PROTOCOL_ERROR, and MCP_TIMEOUT.
- Consumes MCP's existing initialize, notifications/initialized, and tools/call JSON-RPC surface.

- [x] Step 1: Write the failing tests

Create a fake process with line-oriented stdin/stdout so protocol tests do not depend on a real backend. The fake process records written JSON lines and returns queued JSON responses. Cover the following concrete cases:

    def test_start_performs_initialize_and_initialized_notification(self):
        process = FakeProcess([
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "ponte-mcp-adapter", "version": "0.1.0"},
                },
            },
        ])
        client = McpStdioClient(
            "http://127.0.0.1:8080",
            process_factory=process.factory,
        )

        client.start()

        self.assertEqual(json.loads(process.writes[0])["method"], "initialize")
        self.assertEqual(
            json.loads(process.writes[1])["method"],
            "notifications/initialized",
        )

Also cover successful call_tool structured content, MCP tool errors becoming AdapterError, malformed JSON, wrong response id, EOF, and a read timeout. Use unittest.TestCase and assertRaises; do not introduce pytest as a dependency.

- [x] Step 2: Run test to verify it fails

Run:

    python3 -m unittest middleware.tests.test_mcp_client -v

Expected: FAIL because middleware.mcp_client and McpStdioClient do not exist.

- [x] Step 3: Implement the minimal client

Implement McpStdioClient.start() with the following process configuration:

    command = [python_executable, "-m", "MCP"]
    environment = os.environ.copy()
    environment["PONTE_BACKEND_URL"] = self.backend_url
    process = process_factory(
        command,
        cwd=str(project_root),
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

Resolve python_executable to sys.executable and project_root to the repository root containing MCP/ when omitted. Send an initialize request with id 1, validate the 2025-03-26 response, then send notifications/initialized without reading a response.

Implement call_tool() under a threading.Lock. Increment the request id, write one JSON object plus a newline, flush, wait for one stdout line with selectors.DefaultSelector for the configured timeout, and parse the response. Reject invalid JSON, non-2.0 responses, wrong ids, JSON-RPC errors, missing result, or missing structuredContent as MCP_PROTOCOL_ERROR. Convert an MCP tool result whose isError is true into AdapterError using the nested structuredContent.error fields. close() must close stdin, terminate a live child, wait briefly, then kill only if it did not exit; repeated close() calls must be safe.

- [x] Step 4: Run test to verify it passes

Run:

    python3 -m unittest middleware.tests.test_mcp_client MCP.tests.test_server -v

Expected: all MCP client and existing MCP protocol tests PASS.

- [x] Step 5: Mark the completed plan steps

Change every completed Task 1 checkbox from [ ] to [x] before moving to Task 2, as required by AGENTS.md.

### Task 2: Route middleware execution through the MCP client

Files:

- Modify: middleware/execution.py
- Modify: middleware/server.py
- Modify: middleware/tests/test_execution.py
- Modify: middleware/tests/test_server.py

Interfaces:

- Produces McpExecutionStage(registry, client) with the same handle(call, next_stage) -> ToolExecutionResult contract as DirectMcpExecutionStage.
- Produces MiddlewareApplication.close() -> None.
- create_application(backend_url, patient_id, authorization, *, mcp_client=None) -> MiddlewareApplication uses a real McpStdioClient when no client is injected and starts it before serving requests.
- Consumes the existing MCP.registry.ToolRegistry, ToolCall, ToolExecutionResult, and AdapterError contracts.

- [x] Step 1: Write the failing tests

Add a fake MCP client and tests proving the new terminal stage uses it rather than RestAdapter:

    class RecordingMcpClient:
        def __init__(self, payload=None, error=None):
            self.calls = []
            self.payload = payload or {
                "request_id": "REQ-MCP-1",
                "data": {"ok": True},
            }
            self.error = error
            self.closed = False

        def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            if self.error:
                raise self.error
            return self.payload

        def close(self):
            self.closed = True

    def test_mcp_stage_calls_stdio_client_with_registry_tool(self):
        client = RecordingMcpClient()
        result = ExecutionPipeline([
            McpExecutionStage(build_registry(), client),
        ]).dispatch(ToolCall(
            "medical.list_departments",
            {
                "context": {"authorization": "Bearer mock-user-token"},
                "input": {},
            },
            "load_departments",
        ))

        self.assertTrue(result.ok)
        self.assertEqual(client.calls[0][0], "medical.list_departments")

    def test_mcp_stage_converts_adapter_error_to_tool_result(self):
        client = RecordingMcpClient(error=AdapterError(
            code="MCP_UNAVAILABLE",
            message="MCP unavailable",
            status=503,
        ))
        result = ExecutionPipeline([
            McpExecutionStage(build_registry(), client),
        ]).dispatch(ToolCall(
            "medical.list_departments",
            {"context": {}, "input": {}},
            "health",
        ))

        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "MCP_UNAVAILABLE")

Update server tests to inject RecordingMcpClient for endpoint-shape tests and assert MiddlewareApplication.close() calls its client close method.

- [x] Step 2: Run test to verify it fails

Run:

    python3 -m unittest middleware.tests.test_execution middleware.tests.test_server -v

Expected: FAIL because McpExecutionStage and application lifecycle injection do not exist.

- [x] Step 3: Implement the stage and application wiring

Add McpExecutionStage beside DirectMcpExecutionStage. It must resolve call.name through the fixed registry, call client.call_tool(call.name, call.arguments), require a dict payload, use its request_id or generate REQ-MW-*, and convert AdapterError to the existing safe ToolExecutionResult error shape. Keep DirectMcpExecutionStage unchanged for isolated adapter tests.

Change MiddlewareApplication to store self.mcp_client, create and start McpStdioClient(backend_url) when no client is supplied, and build its pipeline with McpExecutionStage(self.registry, self.mcp_client). Add an idempotent close() method. Preserve dispatch_tool, controller behavior, and all existing HTTP paths.

Return a small MiddlewareHTTPServer(ThreadingHTTPServer) from create_http_server; its server_close() must call application.close() before superclass cleanup. Ensure main() also closes the application in its finally block. No child process may be left behind when tests call server.shutdown(); server.server_close().

- [x] Step 4: Run test to verify it passes

Run:

    python3 -m unittest middleware.tests.test_execution middleware.tests.test_server tests.test_middleware_integration -v

Expected: stage tests, server tests, and the existing middleware/backend flow PASS; the existing integration now traverses the real MCP stdio process.

- [x] Step 5: Mark the completed plan steps

Change every completed Task 2 checkbox from [ ] to [x] before moving to Task 3.

### Task 3: Add deterministic full-stack process coverage

Files:

- Create: tests/test_full_stack_integration.py
- Modify: tests/test_middleware_integration.py

Interfaces:

- Produces a unittest fixture that starts the real mock backend, middleware with its real MCP child, and frontend static server on 127.0.0.1.
- Produces assertions for /, /mcp-client.js, /api/health, and /api/interactions/message.
- Consumes mock_backends.server.create_http_server, middleware.server.create_application/create_http_server, and frontend.server.create_http_server.

- [x] Step 1: Write the failing test

Create a temporary-data fixture that starts backend and middleware, then frontend. Use urllib.request with ProxyHandler({}) so localhost is not sent through a proxy. The core test must assert the following:

    def test_frontend_to_mcp_to_backend_message_flow(self):
        html = self.get("/")
        client_js = self.get("/mcp-client.js")
        health = self.get_middleware("/api/health")
        response = self.post_middleware("/api/interactions/message", {
            "session_id": "BROWSER-SMOKE-1",
            "message": "我想查詢醫療預約",
            "source": "text",
        })

        self.assertIn("公共服務助手", html)
        self.assertIn("MiddlewareClient", client_js)
        self.assertTrue(health["backend_reachable"])
        self.assertEqual(response["task_state"], "selecting_service")
        self.assertEqual(
            [event["tool_name"] for event in response["tool_events"]],
            [
                "medical.get_my_appointments",
                "medical.list_appointment_services",
            ],
        )

The fixture must call server.shutdown() and server.server_close() for frontend, middleware, and backend in reverse startup order, then join threads and clean the temporary directory.

- [x] Step 2: Run test to verify process-boundary coverage

Run:

    python3 -m unittest tests.test_full_stack_integration -v

Expected: PASS after Task 2 wiring, with the new test file exercising frontend assets and the real MCP child.

- [x] Step 3: Implement the fixture and process-boundary assertions

Start the backend with create_backend_http_server("127.0.0.1", 0, temp_path). Start middleware with the backend's actual port and default application wiring, then start frontend from frontend/. Use each server's assigned server_port to build URLs. Keep the browser-facing fixed-port behavior in Task 4; this automated test can use ephemeral ports because it calls middleware HTTP directly.

Add an assertion against middleware.server.application.mcp_client that its child process is alive during the interaction and has command -m MCP, so a passing response cannot silently regress to the direct adapter stage. Do not inspect private backend files; verify the returned medical fixtures and tool event names.

- [x] Step 4: Run test to verify it passes

Run:

    python3 -m unittest tests.test_full_stack_integration tests.test_middleware_integration -v

Expected: both the new full-stack HTTP coverage and the existing workflow coverage PASS with a real MCP child.

- [x] Step 5: Mark the completed plan steps

Change every completed Task 3 checkbox from [ ] to [x] before moving to Task 4.

### Task 4: Add one-command local stack startup

Files:

- Create: scripts/run_stack.py
- Create: scripts/__init__.py
- Create: tests/test_run_stack.py
- Modify: README.md
- Modify: middleware/README.md
- Modify: frontend/README.md

Interfaces:

- Produces python3 scripts/run_stack.py [--backend-port 8080] [--middleware-port 8090] [--frontend-port 5173] [--data-dir PATH].
- Starts backend and middleware as child processes; middleware starts MCP as its own child. Starts frontend as the third visible service.
- Stops frontend, middleware, and backend in reverse order on SIGINT/SIGTERM or child failure.

- [x] Step 1: Write the failing test

Add a unit test for runner command construction and readiness helpers. Assert the middleware environment contains the selected backend URL and the commands are exactly:

    [python, "-m", "mock_backends.server", "--host", "127.0.0.1",
     "--port", str(backend_port), "--data-dir", str(data_dir)]
    [python, "-m", "middleware.server", "--host", "127.0.0.1",
     "--port", str(middleware_port)]
    [python, "-m", "frontend.server", "--host", "127.0.0.1",
     "--port", str(frontend_port)]

- [x] Step 2: Run test to verify it fails

Run:

    python3 -m unittest tests.test_run_stack -v

Expected: FAIL because the runner module and test do not exist.

- [x] Step 3: Implement the runner and documentation

Implement command construction with argument lists, never shell strings. If --data-dir is omitted, create a temporary directory and keep it alive until shutdown. Wait for each HTTP endpoint to respond before starting the next layer; middleware readiness is GET /api/health, and frontend readiness is GET /. Print the three URLs and the exact browser smoke input. On cleanup, send terminate, wait up to five seconds, then kill a child that remains alive; do not kill arbitrary processes.

Document the normal flow:

    python3 scripts/run_stack.py

Then open http://127.0.0.1:5173, verify the connected health status, type 我想查詢醫療預約, press 送出, and verify the response and visible tool events. Keep the three-terminal fallback documented for debugging individual services.

- [x] Step 4: Run test to verify it passes

Run:

    python3 -m unittest tests.test_run_stack -v

Expected: command and readiness tests PASS. Start the runner manually once and stop it with Ctrl-C; confirm no backend, middleware, frontend, or MCP child remains.

- [x] Step 5: Mark the completed plan steps

Change every completed Task 4 checkbox from [ ] to [x] before moving to Task 5.

### Task 5: Perform browser smoke verification and final regression checks

Files:

- Modify: docs/superpowers/plans/2026-08-03-ponte-full-stack-e2e.md

Interfaces:

- Uses the Task 4 stack runner and the browser-control skill for visible UI verification.
- Produces recorded verification output in the final handoff; no browser profile or microphone state is persisted.

- [x] Step 1: Start the full stack

Run:

    python3 scripts/run_stack.py

Expected: backend, middleware, MCP child, and frontend all report ready; the browser URL is http://127.0.0.1:5173.

- [ ] Step 2: Execute the browser interaction

Open the frontend URL in the in-app browser. Verify the connected health status, enter 我想查詢醫療預約 in #message-input, click #send-button, and wait for the response. Verify the visible page contains:

    我已查到你的預約和可預約服務
    請選擇服務
    medical.get_my_appointments
    medical.list_appointment_services

Verify global-error remains hidden and the health indicator remains connected. Do not click the later action in this smoke test because it requires service/date payloads outside the approved single-input scope.

Environment note: the in-app browser binding could not be created in this WSL workspace because the browser runtime rejected sandboxCwd file:///home/bill/tsinghua/Ponte as a non-local file URI; the desktop display also exposed no browser window. The deterministic HTTP full-stack test in Task 3 passed.

- [x] Step 3: Run the full regression suite

Run:

    python3 -m unittest discover -s tests -v
    python3 -m unittest discover -s MCP/tests -v
    python3 -m unittest discover -s middleware/tests -v
    python3 -m compileall -q MCP middleware mock_backends frontend tests scripts

Expected: all tests and compilation checks PASS, with no orphaned MCP process after the test run.

- [ ] Step 4: Mark the completed plan steps

Change every completed Task 5 checkbox from [ ] to [x]. Record any environment-only limitation, such as a browser connection or localhost socket permission issue, explicitly instead of claiming the corresponding check passed.
