import unittest

from middleware.contracts import ToolExecutionResult
from middleware.intent import IntentDecision
from middleware.interaction_contracts import EventEnvelope
from middleware.interaction_core import InteractionCore
from middleware.session import SessionStore


class FakeIntentRecognizer:
    def recognize(self, message):
        return IntentDecision("medical_booking", "keyword", 1.0, "medical")


class FakePipeline:
    def __init__(self, *, create_result=None):
        self.calls = []
        self.create_result = create_result

    def dispatch(self, call):
        self.calls.append(call)
        if call.name == "medical.list_appointment_services":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-SERVICES", {
                "data": [{"id": "SERVICE-US-001", "name": "腹部超聲波檢查", "active": True, "requires_referral": True}],
            })
        if call.name == "medical.search_appointment_slots":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-SLOTS", {
                "data": [{
                    "id": "SLOT-US-20260807-1500",
                    "service_id": "SERVICE-US-001",
                    "start": "2026-08-07T15:00:00+08:00",
                    "end": "2026-08-07T15:30:00+08:00",
                    "location_id": "LOC-IMAGING-CENTER",
                    "remaining": 1,
                }],
            })
        if call.name == "medical.create_appointment":
            if self.create_result is not None:
                return self.create_result
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-CREATE", {
                "data": {
                    "id": "APT-1",
                    "status": "confirmed",
                    "service": {"id": "SERVICE-US-001", "display": "腹部超聲波檢查"},
                    "start": "2026-08-07T15:00:00+08:00",
                    "location": {"display": "景湖醫療中心"},
                },
                "task": {"id": "TASK-BACKEND-1"},
                "receipt": {"reference": "MED-APT-1", "issued_at": "2026-08-06T15:01:00Z"},
            })
        raise AssertionError(f"unexpected tool: {call.name}")


class FlakyPipeline(FakePipeline):
    def __init__(self, failures):
        super().__init__()
        self.failures = dict(failures)

    def dispatch(self, call):
        remaining = self.failures.get(call.name, 0)
        if remaining:
            self.failures[call.name] = remaining - 1
            self.calls.append(call)
            return ToolExecutionResult(
                call.name,
                call.step_id,
                False,
                "REQ-FAIL",
                error={"code": "BACKEND_UNAVAILABLE", "message": "temporary"},
            )
        return super().dispatch(call)


def envelope(session_id, interaction_id, event):
    return EventEnvelope.from_json({
        "routing": {"session_id": session_id, "interaction_id": interaction_id},
        "event": event,
    })


class InteractionCoreTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = FakePipeline()
        self.core = InteractionCore(
            self.pipeline,
            SessionStore(),
            patient_id="PAT-DEMO-001",
            authorization="Bearer demo",
            mock_user_id="USR-DEMO-001",
            intent_recognizer=FakeIntentRecognizer(),
        )

    def test_first_medical_utterance_lists_services(self):
        result = self.core.handle(envelope("S-1", "INT-1", {
            "type": "user_utterance",
            "task_id": None,
            "content": "我想預約醫療服務",
        }))
        self.assertEqual(result.task["status"], "awaiting_input")
        self.assertEqual(result.task["current_step"], "select_service")
        self.assertEqual(result.response_intent, "select_service")
        self.assertEqual(result.facts["services"][0]["id"], "SERVICE-US-001")
        self.assertEqual(result.allowed_actions[0]["event"]["type"], "service_selected")
        self.assertIn("action_id", result.allowed_actions[0]["event"])

    def test_slot_selection_issues_server_targeted_confirmation(self):
        self.core.handle(envelope("S-1", "INT-1", {"type": "user_utterance", "content": "預約醫療"}))
        first = self.core.handle(envelope("S-1", "INT-1", {"type": "user_utterance", "content": "預約醫療"}))
        task_id = first.task["task_id"]
        service_action = self.core.handle(envelope("S-1", "INT-2", {
            "type": "service_selected",
            "action_id": "ACT-SERVICE-1",
            "task_id": task_id,
            "service_id": "SERVICE-US-001",
            "date_from": "2026-08-07",
            "date_to": "2026-08-14",
        }))
        self.assertEqual(service_action.task["task_id"], task_id)
        result = self.core.handle(envelope("S-1", "INT-3", {
            "type": "slot_selected",
            "action_id": "ACT-SLOT-1",
            "task_id": task_id,
            "slot_id": "SLOT-US-20260807-1500",
        }))
        self.assertEqual(result.task["status"], "awaiting_confirmation")
        self.assertEqual(result.confirmation["status"], "pending")
        action = next(item for item in result.allowed_actions if item["event"]["decision"] == "approve")
        self.assertEqual(action["event"]["task_id"], task_id)
        self.assertEqual(action["event"]["confirmation_id"], result.confirmation["confirmation_id"])
        self.assertIn("action_id", action["event"])

    def test_approval_builds_receipt_before_completed_result(self):
        first = self.core.handle(envelope("S-1", "INT-1", {"type": "user_utterance", "content": "預約醫療"}))
        task_id = first.task["task_id"]
        second = self.core.handle(envelope("S-1", "INT-2", {
            "type": "service_selected", "action_id": "ACT-SERVICE", "task_id": task_id,
            "service_id": "SERVICE-US-001", "date_from": "2026-08-07", "date_to": "2026-08-14",
        }))
        third = self.core.handle(envelope("S-1", "INT-3", {
            "type": "slot_selected", "action_id": "ACT-SLOT", "task_id": task_id,
            "slot_id": "SLOT-US-20260807-1500",
        }))
        approve = next(item["event"] for item in third.allowed_actions if item["event"]["decision"] == "approve")
        completed = self.core.handle(envelope("S-1", "INT-4", approve))
        self.assertEqual(completed.task["status"], "completed")
        self.assertEqual(completed.receipt["receipt_id"], "MED-APT-1")
        self.assertEqual(completed.receipt["task_id"], task_id)
        self.assertEqual(completed.task["receipt"]["receipt_id"], "MED-APT-1")

    def test_non_pending_confirmation_does_not_dispatch_again(self):
        first = self.core.handle(envelope("S-1", "INT-1", {"type": "user_utterance", "content": "預約醫療"}))
        task_id = first.task["task_id"]
        self.core.handle(envelope("S-1", "INT-2", {
            "type": "service_selected", "action_id": "ACT-SERVICE", "task_id": task_id,
            "service_id": "SERVICE-US-001", "date_from": "2026-08-07", "date_to": "2026-08-14",
        }))
        pending = self.core.handle(envelope("S-1", "INT-3", {
            "type": "slot_selected", "action_id": "ACT-SLOT", "task_id": task_id,
            "slot_id": "SLOT-US-20260807-1500",
        }))
        approve = next(item["event"] for item in pending.allowed_actions if item["event"]["decision"] == "approve")
        self.core.handle(envelope("S-1", "INT-4", approve))
        count = len(self.pipeline.calls)
        repeated = self.core.handle(envelope("S-1", "INT-5", approve))
        self.assertEqual(len(self.pipeline.calls), count)
        self.assertEqual(repeated.task["status"], "completed")

    def test_invalid_backend_response_recovers_without_receipt(self):
        self.pipeline.create_result = ToolExecutionResult(
            "medical.create_appointment", "create_appointment", True, "REQ-INVALID", {"data": {}}
        )
        first = self.core.handle(envelope("S-1", "INT-1", {"type": "user_utterance", "content": "預約醫療"}))
        task_id = first.task["task_id"]
        self.core.handle(envelope("S-1", "INT-2", {
            "type": "service_selected", "action_id": "ACT-SERVICE", "task_id": task_id,
            "service_id": "SERVICE-US-001", "date_from": "2026-08-07", "date_to": "2026-08-14",
        }))
        pending = self.core.handle(envelope("S-1", "INT-3", {
            "type": "slot_selected", "action_id": "ACT-SLOT", "task_id": task_id,
            "slot_id": "SLOT-US-20260807-1500",
        }))
        approve = next(item["event"] for item in pending.allowed_actions if item["event"]["decision"] == "approve")
        failed = self.core.handle(envelope("S-1", "INT-4", approve))
        self.assertEqual(failed.task["status"], "awaiting_input")
        self.assertEqual(failed.recovery["reason"], "invalid_backend_response")
        self.assertIsNone(failed.receipt)

    def test_action_target_requires_server_issued_identifiers(self):
        first = self.core.handle(envelope("S-1", "INT-1", {"type": "user_utterance", "content": "闋愮磩閱檪"}))
        with self.assertRaisesRegex(ValueError, "action_id"):
            self.core.handle(envelope("S-1", "INT-2", {
                "type": "service_selected",
                "task_id": first.task["task_id"],
                "service_id": "SERVICE-US-001",
                "date_from": "2026-08-07",
                "date_to": "2026-08-14",
            }))

    def test_retry_replays_failed_tool_without_recursive_recovery(self):
        pipeline = FlakyPipeline({"medical.list_appointment_services": 1})
        core = InteractionCore(
            pipeline,
            SessionStore(),
            patient_id="PAT-DEMO-001",
            authorization="Bearer demo",
            mock_user_id="USR-DEMO-001",
            intent_recognizer=FakeIntentRecognizer(),
        )
        failed = core.handle(envelope("S-1", "INT-1", {"type": "user_utterance", "content": "闋愮磩閱檪"}))
        retry = next(item["event"] for item in failed.allowed_actions if item["event"]["action"] == "retry")
        recovered = core.handle(envelope("S-1", "INT-2", retry))
        self.assertEqual(recovered.task["current_step"], "select_service")
        self.assertEqual(recovered.task["status"], "awaiting_input")
        self.assertEqual([call.name for call in pipeline.calls].count("medical.list_appointment_services"), 2)

    def test_confirmation_uses_server_task_referral_not_caller_value(self):
        first = self.core.handle(envelope("S-1", "INT-1", {"type": "user_utterance", "content": "闋愮磩閱檪"}))
        second = self.core.handle(envelope("S-1", "INT-2", {
            "type": "service_selected", "action_id": "ACT-SERVICE", "task_id": first.task["task_id"],
            "service_id": "SERVICE-US-001", "date_from": "2026-08-07", "date_to": "2026-08-14",
        }))
        third = self.core.handle(envelope("S-1", "INT-3", {
            "type": "slot_selected", "action_id": "ACT-SLOT", "task_id": second.task["task_id"],
            "slot_id": "SLOT-US-20260807-1500",
        }))
        approve = next(item["event"] for item in third.allowed_actions if item["event"]["decision"] == "approve")
        approve["referring_appointment_id"] = "CALLER-CONTROLLED"
        self.core.handle(envelope("S-1", "INT-4", approve))
        create_call = next(call for call in self.pipeline.calls if call.name == "medical.create_appointment")
        self.assertEqual(create_call.arguments["input"]["referring_appointment_id"], "APT-REF-DEMO-001")

    def test_cancelled_pending_confirmation_cannot_be_approved_later(self):
        first = self.core.handle(envelope("S-1", "INT-1", {"type": "user_utterance", "content": "闋愮磩閱檪"}))
        second = self.core.handle(envelope("S-1", "INT-2", {
            "type": "service_selected", "action_id": "ACT-SERVICE", "task_id": first.task["task_id"],
            "service_id": "SERVICE-US-001", "date_from": "2026-08-07", "date_to": "2026-08-14",
        }))
        pending = self.core.handle(envelope("S-1", "INT-3", {
            "type": "slot_selected", "action_id": "ACT-SLOT", "task_id": second.task["task_id"],
            "slot_id": "SLOT-US-20260807-1500",
        }))
        approve = next(item["event"] for item in pending.allowed_actions if item["event"]["decision"] == "approve")
        cancel = {
            "type": "cancel_task",
            "action_id": "ACT-CANCEL",
            "task_id": pending.task["task_id"],
        }
        cancelled = self.core.handle(envelope("S-1", "INT-4", cancel))
        self.assertEqual(cancelled.task["status"], "cancelled")
        repeated = self.core.handle(envelope("S-1", "INT-5", approve))
        self.assertEqual(repeated.task["status"], "cancelled")
        self.assertNotIn("medical.create_appointment", [call.name for call in self.pipeline.calls])


if __name__ == "__main__":
    unittest.main()
