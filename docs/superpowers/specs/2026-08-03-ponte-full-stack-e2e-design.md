# Ponte Full-Stack MCP E2E Design

## Goal

建立一條可重複執行的完整 demo 測試鏈，驗證瀏覽器前端的一次簡單文字輸入能依序通過 Frontend、Middleware、真正的 MCP stdio server，最後到達 Mock Backend 並把結果返回畫面：

```text
Frontend :5173
    -> Middleware HTTP bridge :8090
    -> MCPServer JSON-RPC over stdio
    -> MCP RestAdapter HTTP
    -> Mock Backend :8080
```

瀏覽器 smoke scenario 使用「我想查詢醫療預約」作為輸入，驗證第一個 workflow checkpoint；它不宣稱已完成預約，也不把後續選服務、日期、時段及確認步驟塞進這個單一輸入測試。

## Existing Context

- `mock_backends.server` 已提供四個 domain mount 的 HTTP server，使用 `--data-dir` 保存 mock state。
- `MCP` 已提供固定 21-tool registry、受控 `RestAdapter` 及 newline-delimited JSON-RPC `MCPServer`，入口是 `python -m MCP`。
- `middleware` 已提供 frontend-facing HTTP bridge、session/controller、tool execution pipeline 及直接使用 registry/adapter 的 `DirectMcpExecutionStage`。
- `frontend` 是零 build dependency 的 static app，`MiddlewareClient` 只呼叫 middleware `/api/*` endpoints。
- 現有 integration tests 可驗證 Middleware -> RestAdapter -> Mock Backend，但不會經過獨立 MCP process；現有 MCP smoke tests 則驗證 MCP stdio -> adapter -> backend。

## Design

### 1. Middleware owns the MCP client process

Middleware application startup creates a long-lived `McpStdioClient` with the configured backend URL. The client launches the current Python interpreter with `python -m MCP`, sets `PONTE_BACKEND_URL` in the child environment, and uses the repository root as the child working directory.

The client performs this handshake once:

1. Send JSON-RPC `initialize` with protocol version `2025-03-26`.
2. Send `notifications/initialized` without waiting for a response.
3. For each tool call, send `tools/call` with the fixed tool name and `{context, input}` arguments.

The stdio stream is serialized with a lock because one MCP process has one request stream. Each request receives a monotonically increasing JSON-RPC id. The client validates the response id, JSON-RPC shape, and MCP tool result. `structuredContent` is returned to middleware as the existing backend-shaped payload. `isError: true` becomes the existing `AdapterError`/`ToolExecutionResult` error boundary without exposing tracebacks to the browser.

The child process is closed when the middleware application/server is closed. Startup failure, unexpected EOF, malformed JSON-RPC, id mismatch, and timeout have stable error codes (`MCP_UNAVAILABLE`, `MCP_PROTOCOL_ERROR`, or `MCP_TIMEOUT`) and remain safe to serialize.

### 2. Replace only the runtime terminal stage

Add a middleware execution stage that resolves the fixed registry definition and invokes `McpStdioClient.call_tool`. The controller and interaction contracts remain unchanged. The middleware HTTP bridge therefore continues to expose:

- `GET /api/health`
- `GET /api/mcp/tools`
- `POST /api/mcp/tools/call`
- `POST /api/interactions/message`
- `POST /api/interactions/action`

`DirectMcpExecutionStage` remains available for fast unit tests of controller and adapter behavior. Production/application wiring uses the stdio MCP stage so all interaction and direct-tool requests traverse the real MCP server. The registry is still checked before dispatch; the client cannot send arbitrary method, URL, headers, or tool names.

### 3. Make startup and teardown deterministic

The middleware application owns the client and exposes a close operation. `create_http_server` attaches a shutdown-safe cleanup hook for the application, and the command-line entrypoint calls cleanup in its `finally` block. Tests explicitly close servers and applications in teardown so no child MCP process survives a test.

The stack runner starts:

1. Mock backend on an ephemeral or configured localhost port with a temporary data directory.
2. Middleware on an ephemeral or configured localhost port, pointed at the backend URL; middleware starts MCP.
3. Frontend static server on an ephemeral or configured localhost port, pointed at middleware through `PONTE_MIDDLEWARE_URL`.

The runner forwards SIGINT/SIGTERM and terminates children in reverse order. A documented three-command fallback remains available for environments where the runner is not used.

### 4. Test layers and acceptance criteria

Keep the existing focused tests and add the missing process-boundary coverage:

- MCP client unit tests use a fake line-oriented child or transport to cover handshake, tool success, MCP tool error, malformed response, id mismatch, EOF, and timeout.
- Middleware process integration starts the real mock backend and real `python -m MCP`; a middleware interaction request must return the same medical data while the MCP process is the only execution stage.
- Full stack HTTP smoke starts backend, middleware, and frontend static servers and checks `/`, `/mcp-client.js`, `/api/health`, and `/api/interactions/message`.
- Browser acceptance opens the frontend URL, verifies the health indicator is connected, enters `我想查詢醫療預約`, submits it, and verifies the assistant response, task state `selecting_service`, visible tool events for `medical.get_my_appointments` and `medical.list_appointment_services`, and no connection error.

The browser smoke may use the in-app browser during verification. The repository-level automated test remains deterministic and does not depend on microphone, speech recognition, external authentication, or a browser profile.

### 5. Error and observability boundaries

- Child stderr is kept separate from stdout so MCP protocol output cannot be corrupted.
- Middleware maps MCP process/transport failures to `ToolExecutionResult(ok=False)` and the existing controller response path.
- The frontend continues to show a user-readable middleware error and retains text input.
- Request ids from backend envelopes remain visible in `tool_events` when available; generated middleware ids are used only when a lower layer cannot provide one.
- No credentials, patient identifiers, or raw tracebacks are added to logs or browser error payloads beyond the existing mock/demo context.

## Non-Goals

- Replacing newline-delimited JSON-RPC with a network MCP transport.
- Adding Workflow persistence, external authentication, real government/medical systems, or a general-purpose agent.
- Making the browser smoke complete the full medical booking workflow.
- Reworking the frontend into a build-based application.

## Files Expected to Change During Implementation

- `middleware/mcp_client.py`: long-lived stdio MCP client and protocol/error boundary.
- `middleware/execution.py`: MCP stdio execution stage and safe error mapping.
- `middleware/server.py`: application wiring, lifecycle and configuration.
- `tests/` and/or `middleware/tests/`: process-boundary and stack integration coverage.
- `scripts/` or an equivalent root runner module: deterministic local stack startup and teardown.
- `README.md`, `middleware/README.md`, and `frontend/README.md`: startup and browser acceptance instructions.

The exact test file split may follow the existing unittest layout, but no domain backend or MCP tool contract changes are required.

