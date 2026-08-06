import copy
import unittest

from middleware.interaction_contracts import CanonicalInteractionResult
from middleware.interaction_delivery import (
    DeliveryOrchestrator,
    ResponseComposer,
    WorkspaceProjector,
)
from middleware.voice import SpeechPayload


def result_for(
    response_intent,
    *,
    status="awaiting_input",
    current_step="select_service",
    facts=None,
    allowed_actions=None,
    confirmation=None,
    recovery=None,
    receipt=None,
):
    return CanonicalInteractionResult(
        interaction_id="INT-1",
        task={
            "task_id": "TASK-1",
            "status": status,
            "current_step": current_step,
        },
        response_intent=response_intent,
        facts={} if facts is None else facts,
        allowed_actions=[] if allowed_actions is None else allowed_actions,
        confirmation=confirmation,
        recovery=recovery,
        receipt=receipt,
    )


class BrokenSpeechAdapter:
    def synthesize(self, text, settings):
        raise RuntimeError("tts is down")


class WorkingSpeechAdapter:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, settings):
        self.calls.append((text, settings))
        return SpeechPayload(b"audio", "audio/mpeg")


class InteractionDeliveryTests(unittest.TestCase):
    def test_workspace_preserves_complete_server_action_event(self):
        event = {
            "type": "confirmation_decision",
            "action_id": "ACT-APPROVE",
            "task_id": "TASK-1",
            "confirmation_id": "CONF-1",
            "decision": "approve",
            "server_nonce": "opaque-value",
        }
        result = result_for(
            "confirm_appointment",
            status="awaiting_confirmation",
            current_step="confirm",
            confirmation={"confirmation_id": "CONF-1", "status": "pending"},
            allowed_actions=[{"label": "確認預約", "event": event}],
        )

        workspace = WorkspaceProjector.project(result)

        self.assertEqual(workspace["actions"][0]["event"], event)
        self.assertIsNot(workspace["actions"][0]["event"], event)
        self.assertEqual(workspace["actions"][0]["event"]["action_id"], "ACT-APPROVE")
        self.assertEqual(workspace["actions"][0]["event"]["task_id"], "TASK-1")
        self.assertEqual(workspace["actions"][0]["event"]["confirmation_id"], "CONF-1")
        self.assertEqual(workspace["actions"][0]["event"]["decision"], "approve")

    def test_workspace_selects_each_deterministic_appointment_view(self):
        cases = (
            (
                "appointment_list",
                result_for("appointment_list", facts={"appointments": []}),
            ),
            (
                "service_selection",
                result_for(
                    "select_service",
                    facts={"services": [{"id": "SVC-1", "name": "檢查"}]},
                ),
            ),
            (
                "slot_selection",
                result_for(
                    "select_slot",
                    current_step="select_slot",
                    facts={"slots": [{"id": "SLOT-1", "start": "2026-08-07T15:00:00+08:00"}]},
                ),
            ),
            (
                "appointment_confirmation",
                result_for(
                    "confirm_appointment",
                    status="awaiting_confirmation",
                    current_step="confirm",
                    confirmation={"confirmation_id": "CONF-1", "status": "pending"},
                ),
            ),
            (
                "appointment_recovery",
                result_for(
                    "recovery",
                    recovery={"reason": "invalid_backend_response", "message": "請重試"},
                ),
            ),
            (
                "appointment_completed",
                result_for(
                    "completed",
                    status="completed",
                    receipt={"receipt_id": "MED-1", "status": "completed"},
                ),
            ),
        )

        for expected_view, result in cases:
            with self.subTest(expected_view=expected_view):
                workspace = WorkspaceProjector.project(result)
                self.assertEqual(workspace["view"], expected_view)

    def test_response_and_receipt_projection_are_deterministic_and_structured(self):
        receipt = {
            "receipt_id": "MED-1",
            "kind": "medical_appointment",
            "status": "completed",
            "issued_at": "2026-08-06T15:01:00Z",
            "task_id": "TASK-1",
            "appointment": {
                "service": "腹部超聲波檢查",
                "date": "2026-08-07",
                "time": "15:00",
                "location": "景湖醫療中心",
                "status": "confirmed",
            },
        }
        result = result_for(
            "completed",
            status="completed",
            facts={"appointment": receipt["appointment"]},
            receipt=receipt,
        )
        before = copy.deepcopy(result.to_dict())

        first_response = ResponseComposer.compose(result)
        second_response = ResponseComposer.compose(result)
        workspace = WorkspaceProjector.project(result)

        self.assertEqual(first_response, second_response)
        self.assertEqual(set(first_response), {"display_text", "speech_text"})
        self.assertTrue(first_response["display_text"])
        self.assertTrue(first_response["speech_text"])
        self.assertEqual(workspace["artifact"], receipt)
        self.assertEqual(result.to_dict(), before)

    def test_cash_summary_projects_read_only_workspace_without_receipt(self):
        facts = {
            "plan": {
                "plan_id": "CSP-2026",
                "plan_name": "現金分享計劃",
                "year": 2026,
                "status": "OPEN",
                "eligibility": {"eligible": True, "status": "ELIGIBLE"},
                "payout": {
                    "amount": 10000,
                    "currency": "MOP",
                    "payment_status": "SCHEDULED",
                    "scheduled_date": "2026-09-30",
                },
                "last_updated_at": "2026-08-06T00:00:00+08:00",
            },
            "history": [],
        }
        result = result_for(
            "cash_sharing_summary",
            status="completed",
            current_step="complete",
            facts=facts,
        )

        workspace = WorkspaceProjector.project(result)
        response = ResponseComposer.compose(result)

        self.assertEqual(workspace["view"], "cash_sharing_summary")
        self.assertEqual(workspace["actions"], [])
        self.assertIsNone(workspace["artifact"])
        self.assertEqual(
            {field["key"] for field in workspace["fields"]},
            {
                "plan_name", "year", "plan_status", "eligibility",
                "amount", "currency", "payment_status", "scheduled_date",
                "last_updated_at",
            },
        )
        self.assertIn("OPEN", response["display_text"])
        self.assertIn("ELIGIBLE", response["display_text"])
        self.assertIn("SCHEDULED", response["display_text"])
        self.assertNotIn("預約已完成", response["display_text"])

    def test_cash_recovery_projects_reason_and_server_actions(self):
        event = {
            "type": "recovery_action",
            "action_id": "ACT-RETRY",
            "task_id": "TASK-1",
            "action": "retry",
        }
        result = result_for(
            "cash_sharing_recovery",
            current_step="load_cash_sharing_plan",
            recovery={
                "reason": "backend_unavailable",
                "allowed_actions": ["retry", "human_help", "cancel"],
            },
            allowed_actions=[{"label": "再試一次", "event": event}],
        )

        workspace = WorkspaceProjector.project(result)
        response = ResponseComposer.compose(result)

        self.assertEqual(workspace["view"], "cash_sharing_recovery")
        self.assertEqual(workspace["fields"][0]["key"], "reason")
        self.assertEqual(workspace["actions"][0]["event"], event)
        self.assertIn("重試", response["display_text"])

    def test_cash_cancelled_task_is_not_projected_as_appointment(self):
        result = CanonicalInteractionResult(
            interaction_id="INT-1",
            task={
                "task_id": "TASK-1",
                "type": "cash_sharing_query",
                "status": "cancelled",
                "current_step": "cancelled",
            },
            response_intent="cancelled",
        )

        workspace = WorkspaceProjector.project(result)
        response = ResponseComposer.compose(result)

        self.assertEqual(workspace["view"], "cash_sharing_summary")
        self.assertNotIn("預約", response["display_text"])

    def test_tts_failure_isolated_from_canonical_result(self):
        result = result_for(
            "select_service",
            facts={"services": [{"id": "SVC-1", "name": "檢查"}]},
        )
        before = copy.deepcopy(result.to_dict())

        delivered = DeliveryOrchestrator.deliver(
            result,
            speech_adapter=BrokenSpeechAdapter(),
            speech_settings={"voice": "test"},
        )

        self.assertEqual(delivered["interaction_id"], "INT-1")
        self.assertEqual(delivered["task"], before["task"])
        self.assertEqual(delivered["speech_audio"]["status"], "unavailable")
        self.assertEqual(result.to_dict(), before)

    def test_tts_success_returns_metadata_without_audio_bytes(self):
        adapter = WorkingSpeechAdapter()
        result = result_for("select_service")

        delivered = DeliveryOrchestrator.deliver(
            result,
            speech_adapter=adapter,
            speech_settings={"voice": "test"},
        )

        self.assertEqual(delivered["speech_audio"]["status"], "ready")
        self.assertEqual(delivered["speech_audio"]["content_type"], "audio/mpeg")
        self.assertEqual(delivered["speech_audio"]["byte_length"], 5)
        self.assertNotIn("content", delivered["speech_audio"])
        self.assertEqual(adapter.calls[0][1], {"voice": "test"})


if __name__ == "__main__":
    unittest.main()
