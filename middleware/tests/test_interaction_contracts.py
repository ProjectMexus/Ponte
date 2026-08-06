import unittest

from middleware.interaction_contracts import (
    CanonicalInteractionResult,
    ConfirmationDecision,
    EventEnvelope,
    InteractionTask,
)


class InteractionContractTests(unittest.TestCase):
    def test_user_utterance_is_modality_neutral(self):
        envelope = EventEnvelope.from_json({
            "routing": {"interaction_id": "INT-1", "session_id": "S-1"},
            "event": {
                "type": "user_utterance",
                "task_id": None,
                "content": "I want to book an ultrasound",
                "source": "voice",
                "language": "yue",
            },
            "audit": {"source": "voice", "language": "yue"},
        })
        self.assertEqual(envelope.event["content"], "I want to book an ultrasound")
        self.assertNotIn("source", envelope.event)
        self.assertNotIn("language", envelope.event)

    def test_confirmation_event_keeps_complete_server_target(self):
        envelope = EventEnvelope.from_json({
            "routing": {"interaction_id": "INT-1", "session_id": "S-1"},
            "event": {
                "type": "confirmation_decision",
                "action_id": "ACT-1",
                "task_id": "TASK-1",
                "confirmation_id": "CONF-1",
                "decision": "approve",
            },
        })
        decision = ConfirmationDecision.from_event(envelope.event)
        self.assertEqual(decision.action_id, "ACT-1")
        self.assertEqual(decision.decision, "approve")

    def test_interaction_task_requires_explicit_workflow_state(self):
        task = InteractionTask(
            task_id="TASK-1",
            type="medical_appointment",
            status="awaiting_input",
            current_step="select_service",
        ).to_dict()
        self.assertEqual(task["type"], "medical_appointment")
        self.assertEqual(task["status"], "awaiting_input")
        self.assertEqual(task["current_step"], "select_service")

    def test_canonical_result_serializes_only_structured_fields(self):
        result = CanonicalInteractionResult(
            interaction_id="INT-1",
            task={"task_id": "TASK-1", "status": "awaiting_input", "current_step": "select_service"},
            response_intent="select_service",
            facts={"services": []},
            allowed_actions=[],
        )
        payload = result.to_dict()
        self.assertEqual(payload["response_intent"], "select_service")
        self.assertNotIn("assistant_message", payload)
        self.assertNotIn("raw", payload)


if __name__ == "__main__":
    unittest.main()
