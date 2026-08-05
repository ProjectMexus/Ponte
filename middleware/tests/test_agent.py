import json
import unittest

from MCP.registry import build_registry
from middleware.agent import RegistryDrivenAgent, project_registry_tools
from middleware.contracts import ToolExecutionResult


class ScriptedChatClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        return self.responses.pop(0)


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    def dispatch(self, call, context):
        self.calls.append((call, dict(context)))
        return ToolExecutionResult(
            call.name,
            call.step_id,
            True,
            "REQ-AGENT-1",
            {"departments": []},
        )


class RegistryDrivenAgentTests(unittest.TestCase):
    def test_projects_all_registry_tools_with_input_schema_only(self):
        registry = build_registry()

        tools = project_registry_tools(registry)

        self.assertEqual(len(tools), 21)
        self.assertEqual(
            {tool["function"]["name"] for tool in tools},
            set(registry.names()),
        )
        for tool in tools:
            parameters = tool["function"]["parameters"]
            self.assertNotIn("context", parameters.get("properties", {}))
            self.assertNotIn("input", parameters.get("properties", {}))

    def test_r0_executes_with_server_context_then_returns_response(self):
        client = ScriptedChatClient([
            {
                "choices": [{"message": {"content": json.dumps({
                    "action": "tool_call",
                    "tool_name": "medical.list_departments",
                    "arguments": {"active_only": True},
                })}}],
            },
            {
                "choices": [{"message": {"content": json.dumps({
                    "action": "respond",
                    "message": "No departments matched.",
                })}}],
            },
        ])
        executor = RecordingExecutor()
        agent = RegistryDrivenAgent(build_registry(), client, executor)

        outcome = agent.run(
            "Show departments",
            context={"authorization": "Bearer server-secret", "accept_language": "en-US"},
        )

        self.assertEqual(outcome.kind, "respond")
        self.assertEqual(outcome.message, "No departments matched.")
        self.assertEqual(outcome.decision_count, 2)
        self.assertEqual(len(outcome.tool_results), 1)
        call, context = executor.calls[0]
        self.assertEqual(call.arguments, {"active_only": True})
        self.assertEqual(context["authorization"], "Bearer server-secret")

    def test_risk_tool_returns_immutable_pending_proposal_without_execution(self):
        client = ScriptedChatClient([{
            "choices": [{"message": {"content": json.dumps({
                "action": "tool_call",
                "tool_name": "medical.create_appointment",
                "arguments": {
                    "patient_id": "P-1",
                    "service_id": "S-1",
                    "slot_id": "SL-1",
                    "consent": True,
                },
            })}}],
        }])
        executor = RecordingExecutor()
        agent = RegistryDrivenAgent(build_registry(), client, executor, clock=lambda: 1000.0)

        outcome = agent.run("Book it", context={"authorization": "secret"})

        self.assertEqual(outcome.kind, "pending_approval")
        self.assertEqual(outcome.proposal.risk_level, "R2")
        self.assertEqual(outcome.proposal.expires_at, 1300.0)
        self.assertTrue(outcome.proposal.verify_integrity())
        with self.assertRaises(TypeError):
            outcome.proposal.arguments["slot_id"] = "CHANGED"
        self.assertEqual(executor.calls, [])

    def test_r1_tool_also_requires_approval(self):
        client = ScriptedChatClient([{
            "choices": [{"message": {"content": json.dumps({
                "action": "tool_call",
                "tool_name": "one_account.book_government_service_center_queue",
                "arguments": {
                    "service_type": "identity",
                    "requested_date": "2026-08-10",
                    "confirmation": {"confirmed": True},
                },
            })}}],
        }])
        executor = RecordingExecutor()

        outcome = RegistryDrivenAgent(build_registry(), client, executor).run("Reserve a queue")

        self.assertEqual(outcome.kind, "pending_approval")
        self.assertEqual(outcome.proposal.risk_level, "R1")
        with self.assertRaises(TypeError):
            outcome.proposal.arguments["confirmation"]["confirmed"] = False
        self.assertEqual(executor.calls, [])

    def test_stops_after_four_r0_tool_decisions(self):
        response = {
            "choices": [{"message": {"content": json.dumps({
                "action": "tool_call",
                "tool_name": "medical.list_departments",
                "arguments": {},
            })}}],
        }
        client = ScriptedChatClient([response, response, response, response, response])
        executor = RecordingExecutor()
        agent = RegistryDrivenAgent(build_registry(), client, executor)

        outcome = agent.run("Keep looking")

        self.assertEqual(outcome.kind, "limit_reached")
        self.assertEqual(outcome.decision_count, 4)
        self.assertEqual(len(executor.calls), 4)
        self.assertEqual(len(client.requests), 4)

    def test_malformed_model_json_fails_without_tool_execution(self):
        client = ScriptedChatClient([{
            "choices": [{"message": {"content": "```json\n{}\n```"}}],
        }])
        executor = RecordingExecutor()

        outcome = RegistryDrivenAgent(build_registry(), client, executor).run("Do something")

        self.assertEqual(outcome.kind, "clarify")
        self.assertEqual(executor.calls, [])


if __name__ == "__main__":
    unittest.main()
