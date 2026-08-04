# Windows Stack Runner Compatibility Design

## Goal

讓 Ponte 在 Windows/PowerShell 使用已安裝的 Python 3.13 啟動完整 stack，並修復 middleware 與 MCP stdio child process 通訊時 Windows pipe 被當作 socket 使用的錯誤。

## Scope

- 將 repository README 的執行範例由 `python3` 改為跨平台可用的 `python`。
- 在 `middleware/mcp_client.py` 抽象 MCP stdout line reader：Unix 使用 `selectors` 的可超時讀取；Windows 使用 background thread 將 blocking pipe 讀取結果送入 queue，再由主執行緒以 timeout 等待。
- 保留既有 MCP JSON-RPC、錯誤碼、timeout 行為及 process lifecycle。
- 加入 Windows-specific regression coverage，並以完整 stack smoke 驗證。

## Architecture

`McpStdioClient._read_response()` 不直接依賴 platform-specific pipe semantics，而是呼叫一個內部 line-reader abstraction。Unix reader 以 `selectors.DefaultSelector` 等待 stdout 可讀；Windows reader 啟動 daemon reader thread，thread 執行 `readline()` 並把 `(raw line, exception)` 放入 queue，呼叫端用 `queue.get(timeout=...)` 實現相同 timeout contract。reader 的生命週期綁定單一 MCP process，process stop 時不再等待 reader thread。

所有 reader failure 仍轉換為既有 `MCP_TIMEOUT`、`MCP_UNAVAILABLE` 或 `MCP_PROTOCOL_ERROR`，不把 platform exception 暴露給 HTTP client。

## Testing

- Extend `middleware/tests/test_mcp_client.py` with a reader abstraction test that simulates a Windows pipe and confirms a response is read without calling `selectors.select`.
- Run the focused MCP client tests on Windows Python.
- Run repository, MCP, and middleware unittest suites plus compileall.
- Start `scripts/run_stack.py` with Python 3.13 and confirm backend, middleware, and frontend become ready.

## Documentation

Root `README.md` and service README command examples use `python`. Linux users may still use `python3` explicitly if that is their local interpreter name; the code itself always passes `sys.executable` to child processes.
