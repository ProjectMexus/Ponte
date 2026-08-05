import unittest

from middleware.contracts import ToolExecutionResult
from middleware.interaction_contracts import (
    ActionReceiptBuilder,
    CanonicalInteractionResult,
    ConfirmationDecision,
    EventEnvelope,
    MedicalResultVerifier,
)


class InteractionContractTests(unittest.TestCase):
    def test_user_utterance_is_modality_neutral(self):
        envelope = EventEnvelope.from_json({
            "routing": {"interaction_id": "INT-1", "session_id": "S-1"},
            "event": {
                "type": "user_utterance",
                "task_id": None,
                "content": "我想預約腹部超聲波",
                "source": "voice",
                "language": "yue",
            },
            "audit": {"source": "voice", "language": "yue"},
        })
        self.assertEqual(envelope.event["content"], "我想預約腹部超聲波")
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

    def test_receipt_builder_uses_verified_backend_reference(self):
        result = ToolExecutionResult(
            "medical.create_appointment",
            "create_appointment",
            True,
            "REQ-1",
            {
                "data": {
                    "id": "APT-1",
                    "status": "confirmed",
                    "service": {"id": "SERVICE-US-001", "display": "腹部超聲波檢查"},
                    "start": "2026-08-07T15:00:00+08:00",
                    "location": {"display": "景湖醫療中心"},
                    "patient_id": "PAT-SECRET",
                },
                "task": {"id": "TASK-1"},
                "receipt": {"reference": "MED-APT-1", "issued_at": "2026-08-06T15:01:00Z"},
            },
        )
        verified = MedicalResultVerifier.verify(result)
        receipt = ActionReceiptBuilder.build("TASK-1", verified)
        self.assertEqual(receipt["receipt_id"], "MED-APT-1")
        self.assertEqual(receipt["issued_at"], "2026-08-06T15:01:00Z")
        self.assertNotIn("patient_id", receipt)
        self.assertNotIn("reference", receipt)

    def test_invalid_execution_result_is_rejected(self):
        result = ToolExecutionResult("medical.create_appointment", "create_appointment", True, "REQ-1", {"data": {}})
        with self.assertRaises(ValueError):
            MedicalResultVerifier.verify(result)

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
