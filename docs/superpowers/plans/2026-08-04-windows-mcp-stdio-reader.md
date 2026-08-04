# Windows MCP stdio Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ponte's MCP stdio client work on Windows while preserving the existing public client and JSON-RPC behavior.

**Architecture:** Keep `McpStdioClient` as the protocol/process owner and inject a platform-specific stdout reader selected by a small factory. Unix-like systems use the existing selector-based reader; Windows uses a daemon thread and queue because Windows subprocess pipes are not selector-compatible.

**Tech Stack:** Python 3.13 standard library (`abc`, `os`, `queue`, `selectors`, `threading`), `unittest`, existing README documentation.

## Global Constraints

- Do not add third-party Python dependencies.
- Preserve `McpStdioClient`, `McpClientError`, JSON-RPC messages, and existing error codes.
- Windows commands in README use `python`; child processes continue to use `sys.executable`.
- Reader timeout remains controlled by the existing `McpStdioClient.timeout` value.

---

### Task 1: Add platform-specific stdout reader abstraction

**Files:**
- Modify: `middleware/mcp_client.py`
- Test: `middleware/tests/test_mcp_client.py`

**Interfaces:**
- Produces `McpStdoutReader.read_line(timeout: float) -> str`.
- Produces `create_stdout_reader(stdout) -> McpStdoutReader`.

- [x] **Step 1: Add tests for factory selection and Windows reader behavior**

Patch the existing MCP tests to import `create_stdout_reader`, patch `middleware.mcp_client.os.name` to `nt` for factory selection, and use an in-memory pipe-like object whose `readline()` blocks until a test thread releases a line. Assert the Windows reader returns the line before timeout and that a delayed line raises the existing timeout at the client boundary.

- [x] **Step 2: Run the focused tests and confirm the new test fails**

Run: `& 'C:\Users\billlo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest middleware.tests.test_mcp_client -v`

Expected: existing tests pass, and the new factory/reader test fails because the factory and abstraction do not exist yet.

- [x] **Step 3: Implement the abstraction**

Add an abstract `McpStdoutReader` with `read_line`, a `SelectorStdoutReader` containing the current selector logic, and a `ThreadedStdoutReader` that owns a daemon thread and `queue.Queue`. The thread calls `stdout.readline()` and queues either the line or the exception. `read_line()` waits with the supplied timeout and raises `TimeoutError` on queue timeout. Add `create_stdout_reader()` using `os.name == "nt"`.

- [x] **Step 4: Make `McpStdioClient` consume the factory**

Create the reader after process creation, replace direct selector logic in `_read_response()` with `self._stdout_reader.read_line(self.timeout)`, map `TimeoutError` to `MCP_TIMEOUT`, and map reader `OSError`/`ValueError` to `MCP_UNAVAILABLE`. Clear the reader during `_stop_process()` after closing process streams. Keep protocol JSON parsing unchanged.

- [x] **Step 5: Run focused tests and confirm they pass**

Run: `& 'C:\Users\billlo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest middleware.tests.test_mcp_client -v`

Expected: all MCP client tests pass on Windows Python.

### Task 2: Update Windows-facing documentation

**Files:**
- Modify: `README.md`
- Modify: `middleware/README.md`
- Modify: `frontend/README.md`
- Modify: `mock_backends/README.md`
- Modify: `MCP/README.md`

- [x] **Step 1: Replace executable examples**

Change user-facing `python3` commands in README files to `python`, including environment-variable examples where the command is shown. Keep Linux-only shell path examples such as `/tmp` unchanged unless they are part of the executable name.

- [x] **Step 2: Add the Windows startup command**

Document `python scripts/run_stack.py` as the Windows/PowerShell startup command and retain the existing `py` launcher as an equivalent option where useful.

- [x] **Step 3: Run documentation contract tests**

Run: `& 'C:\Users\billlo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_run_stack -v`

Expected: all runner documentation and helper tests pass.

### Task 3: Verify the complete Windows stack

**Files:**
- Verify: `middleware/mcp_client.py`, `middleware/tests/test_mcp_client.py`, README files

- [x] **Step 1: Run all Python test suites**

Run:

```powershell
& 'C:\Users\billlo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -q
& 'C:\Users\billlo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s MCP/tests -q
& 'C:\Users\billlo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s middleware/tests -q
& 'C:\Users\billlo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m compileall -q MCP middleware mock_backends frontend scripts tests
```

Expected: every command exits 0 with no test failures or compile errors.

- [x] **Step 2: Run the real stack with Python 3.13**

Run `python scripts/run_stack.py` and confirm it prints `Ponte stack is ready.` with frontend, middleware, and backend URLs. Stop it with Ctrl-C and confirm child processes terminate.

- [x] **Step 3: Inspect the diff and report evidence**

Run `git diff --check`, inspect `git status --short`, and report the exact test counts and stack smoke result without claiming success unless all commands exit 0.
