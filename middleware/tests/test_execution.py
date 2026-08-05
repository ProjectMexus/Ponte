import unittest

from MCP.errors import AdapterError
from middleware.contracts import ToolCall, ToolExecutionResult
from middleware.execution import (
    ContextualExecutionPipeline,
    DirectMcpExecutionStage,
    ExecutionPipeline,
    McpExecutionStage,
)
from MCP.registry import build_registry


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    def invoke(self, definition, arguments):
        self.calls.append((definition.name, arguments))
        return {"request_id": "REQ-1", "data": {"ok": True}}


class RecordingMcpClient:
    def __init__(self, payload=None, error=None):
        self.calls = []
        self.payload = payload or {"request_id": "REQ-MCP-1", "data": {"ok": True}}
        self.error = error
        self.closed = False

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.error:
            raise self.error
        return self.payload

    def close(self):
        self.closed = True


class ExecutionTests(unittest.TestCase):
    def test_contextual_pipeline_injects_server_context_around_bare_input(self):
        captured = []

        class TerminalStage:
            def handle(self, call, next_stage):
                captured.append(call)
                return ToolExecutionResult(call.name, call.step_id, True, "REQ-CONTEXT", {})

        executor = ContextualExecutionPipeline(ExecutionPipeline([TerminalStage()]))

        executor.dispatch(
            ToolCall("medical.list_departments", {"active_only": True}, "departments"),
            {"authorization": "Bearer trusted"},
        )

        self.assertEqual(captured[0].arguments, {
            "context": {"authorization": "Bearer trusted"},
            "input": {"active_only": True},
        })

    def test_direct_stage_calls_registry_definition_and_adapter(self):
        adapter = RecordingAdapter()
        stage = DirectMcpExecutionStage(build_registry(), adapter)
        result = ExecutionPipeline([stage]).dispatch(ToolCall(
            "medical.list_departments",
            {"context": {"authorization": "Bearer mock-user-token"}, "input": {}},
            "load_departments",
        ))
        self.assertTrue(result.ok)
        self.assertEqual(adapter.calls[0][0], "medical.list_departments")

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

    def test_pipeline_preserves_stage_order_for_future_workflow_stage(self):
        events = []

        class GateStage:
            def handle(self, call, next_stage):
                events.append("workflow")
                return next_stage(call)

        class TerminalStage:
            def handle(self, call, next_stage):
                events.append("mcp")
                return ToolExecutionResult("fake.tool", call.step_id, True, "REQ-2", {"data": {}}, None)

        ExecutionPipeline([GateStage(), TerminalStage()]).dispatch(ToolCall("fake.tool", {}, "step"))
        self.assertEqual(events, ["workflow", "mcp"])


if __name__ == "__main__":
    unittest.main()
