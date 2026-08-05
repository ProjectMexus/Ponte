import json
import unittest

from middleware.approval import ApprovalClassifier, ApprovalGate
from middleware.contracts import PendingToolProposal, ToolExecutionResult


class ScriptedChatClient:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.requests = []

    def complete(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        if self.error:
            raise self.error
        return self.responses.pop(0)


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    def dispatch(self, call, context):
        self.calls.append((call, dict(context)))
        return ToolExecutionResult(call.name, call.step_id, True, "REQ-APPROVED", {"ok": True})


def response(decision, confidence):
    return {
        "choices": [{"message": {"content": json.dumps({
            "decision": decision,
            "confidence": confidence,
        })}}],
    }


class ApprovalClassifierTests(unittest.TestCase):
    def test_uses_only_isolated_system_and_current_user_messages(self):
        client = ScriptedChatClient([response("APPROVE", 0.95)])
        classifier = ApprovalClassifier(client)

        result = classifier.classify("Yes, proceed")

        self.assertEqual(result.decision, "APPROVE")
        messages, _ = client.requests[0]
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertEqual(messages[1]["content"], "Yes, proceed")

    def test_low_confidence_and_invalid_json_fail_closed(self):
        low = ApprovalClassifier(ScriptedChatClient([response("APPROVE", 0.79)]))
        invalid = ApprovalClassifier(ScriptedChatClient([{
            "choices": [{"message": {"content": '{"decision":"APPROVE","confidence":1,"extra":true}'}}],
        }]))
        failed = ApprovalClassifier(ScriptedChatClient(error=RuntimeError("provider down")))

        self.assertEqual(low.classify("yes").decision, "UNCERTAIN")
        self.assertEqual(invalid.classify("yes").decision, "UNCERTAIN")
        self.assertEqual(failed.classify("yes").decision, "UNCERTAIN")


class ApprovalGateTests(unittest.TestCase):
    def proposal(self):
        return PendingToolProposal.create(
            "medical.create_appointment",
            {"patient_id": "P-1", "slot_id": "SL-1"},
            "R2",
            now=1000.0,
        )

    def test_approve_executes_exact_stored_proposal_and_clears_it(self):
        executor = RecordingExecutor()
        gate = ApprovalGate(
            ApprovalClassifier(ScriptedChatClient([response("APPROVE", 0.99)])),
            executor,
            clock=lambda: 1001.0,
        )
        proposal = self.proposal()

        resolution = gate.resolve("yes", proposal, context={"authorization": "server-only"})

        self.assertEqual(resolution.status, "executed")
        self.assertIsNone(resolution.pending_proposal)
        call, context = executor.calls[0]
        self.assertEqual(call.name, proposal.tool_name)
        self.assertEqual(call.arguments, dict(proposal.arguments))
        self.assertEqual(context, {"authorization": "server-only"})

    def test_cancel_clears_and_uncertain_retains_without_execution(self):
        executor = RecordingExecutor()
        cancel = ApprovalGate(
            ApprovalClassifier(ScriptedChatClient([response("CANCEL", 0.99)])),
            executor,
            clock=lambda: 1001.0,
        ).resolve("no", self.proposal())
        uncertain = ApprovalGate(
            ApprovalClassifier(ScriptedChatClient([response("UNCERTAIN", 0.99)])),
            executor,
            clock=lambda: 1001.0,
        ).resolve("maybe", self.proposal())

        self.assertEqual(cancel.status, "cancelled")
        self.assertIsNone(cancel.pending_proposal)
        self.assertEqual(uncertain.status, "uncertain")
        self.assertIsNotNone(uncertain.pending_proposal)
        self.assertEqual(executor.calls, [])

    def test_expired_or_tampered_proposal_never_executes(self):
        executor = RecordingExecutor()
        gate = ApprovalGate(
            ApprovalClassifier(ScriptedChatClient([response("APPROVE", 1.0)])),
            executor,
            clock=lambda: 1300.0,
        )

        resolution = gate.resolve("yes", self.proposal())

        self.assertEqual(resolution.status, "expired")
        self.assertIsNone(resolution.pending_proposal)
        self.assertEqual(executor.calls, [])

        original = self.proposal()
        tampered = PendingToolProposal(
            original.proposal_id,
            original.tool_name,
            original.arguments,
            original.risk_level,
            original.created_at,
            original.expires_at,
            "0" * 64,
        )
        invalid = ApprovalGate(
            ApprovalClassifier(ScriptedChatClient([response("APPROVE", 1.0)])),
            executor,
            clock=lambda: 1001.0,
        ).resolve("yes", tampered)
        self.assertEqual(invalid.status, "invalid")
        self.assertEqual(executor.calls, [])


if __name__ == "__main__":
    unittest.main()
