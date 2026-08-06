"""Architecture-boundary guards for the two-workflow interaction core.

Behavioral ownership is the primary guard: Core routes and persists without
executing tools, concrete workflows own dispatch, and legacy routes reject
medical/cash requests before any tool call. Source inspection stays narrow
and secondary so comments or log strings cannot cause false failures.
"""

import inspect
import unittest
from pathlib import Path

from middleware.cash_sharing_workflow import CashSharingWorkflow
from middleware.contracts import InteractionActionRequest, InteractionRequest, ToolExecutionResult
from middleware.controller import InteractionController, LegacyInteractionContractError
from middleware.intent import IntentDecision, KeywordIntentRecognizer
from middleware.interaction_contracts import (
    CanonicalInteractionResult,
    EventEnvelope,
    InteractionTask,
)
from middleware.interaction_core import InteractionCore
from middleware.interaction_delivery import DeliveryOrchestrator
from middleware.medical_workflow import MedicalWorkflow
from middleware.session import SessionStore


MIDDLEWARE_DIR = Path(__file__).resolve().parents[1]


class FakeWorkflow:
    """Minimal workflow double proving Core needs no execution dependency."""

    def __init__(self, task_type, response_intent):
        self.task_type = task_type
        self.response_intent = response_intent
        self.started = []
        self.handled = []

    def start(self, envelope, intent):
        self.started.append(envelope)
        task = InteractionTask(
            task_id=f"TASK-{self.task_type.upper()}",
            type=self.task_type,
            status="completed",
            current_step="complete",
        ).to_dict()
        result = CanonicalInteractionResult(
            interaction_id=envelope.interaction_id,
            task=task,
            response_intent=self.response_intent,
        )
        return task, result, []

    def handle(self, task, envelope):
        self.handled.append(envelope)
        result = CanonicalInteractionResult(
            interaction_id=envelope.interaction_id,
            task=task,
            response_intent=self.response_intent,
        )
        return task, result, []


class RecordingPipeline:
    def __init__(self):
        self.calls = []

    def dispatch(self, call):
        self.calls.append(call)
        raise AssertionError(f"legacy route dispatched a tool call: {call.name}")


class DualFixturePipeline:
    """Serves both workflows' read-side fixtures in one shared Core process."""

    def __init__(self):
        self.calls = []

    def dispatch(self, call):
        self.calls.append(call)
        if call.name == "medical.list_appointment_services":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-SERVICES", {
                "data": [{
                    "id": "SERVICE-US-001",
                    "name": "腹部超聲波檢查",
                    "active": True,
                }],
            })
        if call.name == "medical.search_appointment_slots":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-SLOTS", {
                "data": [{
                    "id": "SLOT-US-20260812-1400",
                    "service_id": "SERVICE-US-001",
                    "start": "2026-08-12T14:00:00+08:00",
                }],
            })
        if call.name == "one_account.get_cash_sharing_plan":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-PLAN", {
                "data": {
                    "plan": {
                        "plan_id": "CSP-2026",
                        "plan_name": "現金分享計劃",
                        "year": 2026,
                        "status": "OPEN",
                        "eligibility": {"eligible": True, "status": "ELIGIBLE"},
                        "payout": {"amount": 10000, "currency": "MOP"},
                    },
                    "history": [],
                },
            })
        raise AssertionError(f"unexpected tool: {call.name}")


def envelope(session_id, interaction_id, content):
    return EventEnvelope.from_json({
        "routing": {"session_id": session_id, "interaction_id": interaction_id},
        "event": {"type": "user_utterance", "task_id": None, "content": content},
    })


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_core_has_no_execution_dependency(self):
        parameters = inspect.signature(InteractionCore.__init__).parameters
        self.assertNotIn("pipeline", parameters)
        self.assertNotIn("executor", parameters)

    def test_core_routes_both_intents_with_fake_workflows_only(self):
        medical = FakeWorkflow("medical_appointment", "select_service")
        cash = FakeWorkflow("cash_sharing_query", "cash_sharing_summary")
        core = InteractionCore(
            SessionStore(),
            medical,
            intent_recognizer=KeywordIntentRecognizer(),
            cash_workflow=cash,
        )

        medical_result = core.handle(envelope("S-FAKE-MED", "INT-F-1", "我想預約醫療服務"))
        cash_result = core.handle(envelope("S-FAKE-CASH", "INT-F-2", "我想查現金分享計劃"))

        self.assertEqual(len(medical.started), 1)
        self.assertEqual(len(cash.started), 1)
        self.assertEqual(medical_result.task["type"], "medical_appointment")
        self.assertEqual(cash_result.task["type"], "cash_sharing_query")

    def test_core_rejects_unsupported_intents_without_a_workflow_call(self):
        medical = FakeWorkflow("medical_appointment", "select_service")
        core = InteractionCore(SessionStore(), medical, intent_recognizer=KeywordIntentRecognizer())
        with self.assertRaises(ValueError):
            core.handle(envelope("S-FAKE-OTHER", "INT-F-3", "我想找長者文娛活動"))
        self.assertEqual(medical.started, [])

    def test_legacy_medical_route_cannot_dispatch_a_medical_tool(self):
        pipeline = RecordingPipeline()
        controller = InteractionController(
            pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        for message in ("我想預約醫療服務", "我想查詢自己的醫療預約"):
            with self.assertRaises(LegacyInteractionContractError) as raised:
                controller.handle_message(InteractionRequest("S-LEGACY-MED", message))
            self.assertEqual(raised.exception.code, "INTERACTION_EVENT_REQUIRED")
        with self.assertRaises(LegacyInteractionContractError):
            controller.handle_action(InteractionActionRequest("S-LEGACY-MED", "search_slots", {}))
        self.assertEqual(pipeline.calls, [])

    def test_legacy_cash_route_cannot_dispatch_a_cash_tool(self):
        pipeline = RecordingPipeline()
        controller = InteractionController(
            pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        with self.assertRaises(LegacyInteractionContractError) as raised:
            controller.handle_message(InteractionRequest("S-LEGACY-CASH", "我想查現金分享計劃"))
        self.assertEqual(raised.exception.code, "INTERACTION_EVENT_REQUIRED")
        self.assertEqual(pipeline.calls, [])


class SharedCoreBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = DualFixturePipeline()
        self.core = InteractionCore(
            SessionStore(),
            MedicalWorkflow(self.pipeline, "PAT-DEMO-001", "Bearer demo"),
            intent_recognizer=KeywordIntentRecognizer(),
            cash_workflow=CashSharingWorkflow(self.pipeline, "PAT-DEMO-001", "Bearer demo"),
        )
        self.delivery = DeliveryOrchestrator()

    def test_medical_and_cash_sessions_do_not_leak_state(self):
        medical_result = self.core.handle(envelope("S-ARCH-MED", "INT-ARCH-1", "我想預約醫療服務"))
        cash_result = self.core.handle(envelope("S-ARCH-CASH", "INT-ARCH-2", "我想查現金分享計劃"))

        self.assertEqual(medical_result.task["type"], "medical_appointment")
        self.assertEqual(cash_result.task["type"], "cash_sharing_query")

        medical_workspace = self.delivery.deliver(medical_result)["workspace"]
        cash_workspace = self.delivery.deliver(cash_result)["workspace"]
        self.assertEqual(medical_workspace["view"], "service_selection")
        self.assertEqual(cash_workspace["view"], "cash_sharing_summary")

        self.assertIn("services", medical_result.facts)
        self.assertNotIn("plan", medical_result.facts)
        self.assertIn("plan", cash_result.facts)
        self.assertNotIn("services", cash_result.facts)

        self.assertTrue(medical_workspace["actions"])
        self.assertEqual(cash_workspace["actions"], [])
        self.assertIsNone(cash_workspace["artifact"])
        self.assertIsNone(cash_result.receipt)
        self.assertIsNone(cash_result.confirmation)

    def test_follow_up_events_route_to_the_owning_workflow_per_session(self):
        medical_first = self.core.handle(envelope("S-ARCH-MED", "INT-ARCH-3", "我想預約醫療服務"))
        self.core.handle(envelope("S-ARCH-CASH", "INT-ARCH-4", "我想查現金分享計劃"))

        service_event = medical_first.allowed_actions[0]["event"]
        medical_second = self.core.handle(EventEnvelope.from_json({
            "routing": {"session_id": "S-ARCH-MED", "interaction_id": "INT-ARCH-5"},
            "event": service_event,
        }))

        self.assertEqual(medical_second.task["type"], "medical_appointment")
        self.assertIn("slots", medical_second.facts)


class OwnershipSourceTests(unittest.TestCase):
    """Narrow secondary guards; behavior tests above are authoritative."""

    @staticmethod
    def read(name):
        return (MIDDLEWARE_DIR / name).read_text(encoding="utf-8")

    def test_confirmation_execution_and_receipt_logic_is_not_duplicated(self):
        core = self.read("interaction_core.py")
        controller = self.read("controller.py")
        cash = self.read("cash_sharing_workflow.py")
        for source in (core, controller, cash):
            self.assertNotIn("confirmation_decision", source)
            self.assertNotIn("create_appointment", source)
            self.assertNotIn("ActionReceiptBuilder", source)
        for source in (core, controller, cash):
            self.assertNotIn("receipt_id", source)

    def test_controller_retains_only_diagnostic_confirmation(self):
        controller = self.read("controller.py")
        self.assertIn("pending_diagnostic", controller)
        self.assertIn("_confirm_diagnostic", controller)
        self.assertIn("confirm_tool", controller)
        self.assertNotIn("_handle_medical", controller)
        self.assertNotIn("_handle_cash_sharing", controller)


if __name__ == "__main__":
    unittest.main()
