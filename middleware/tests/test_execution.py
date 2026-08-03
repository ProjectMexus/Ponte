import unittest

from middleware.contracts import ToolCall, ToolExecutionResult
from middleware.execution import DirectMcpExecutionStage, ExecutionPipeline
from MCP.registry import build_registry


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    def invoke(self, definition, arguments):
        self.calls.append((definition.name, arguments))
        return {"request_id": "REQ-1", "data": {"ok": True}}


class ExecutionTests(unittest.TestCase):
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
