import inspect
import unittest

from middleware.contracts import ToolExecutionResult
from middleware.intent import IntentDecision
from middleware.interaction_contracts import CanonicalInteractionResult, EventEnvelope
from middleware.interaction_core import InteractionCore
from middleware.medical_workflow import MedicalWorkflow
from middleware.session import SessionStore


class FakeIntentRecognizer:
    def __init__(self, intent="medical_booking"):
        self.intent = intent

    def recognize(self, message):
        return IntentDecision(self.intent, "keyword", 1.0, "medical")


class FakePipeline:
    def __init__(self):
        self.calls = []

    def dispatch(self, call):
        self.calls.append(call)
        if call.name == "medical.list_appointment_services":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-SERVICES", {
                "data": [{"id": "SERVICE-US-001", "name": "腹部超聲波檢查", "active": True}],
            })
        raise AssertionError(f"unexpected tool: {call.name}")


class FakeWorkflow:
    def __init__(self):
        self.started = []
        self.handled = []

    def start(self, envelope, intent):
        self.started.append((envelope, intent))
        return self._outcome(envelope, "select_service")

    def handle(self, task, envelope):
        self.handled.append((task, envelope))
        updated = dict(task)
        updated["current_step"] = "select_slot"
        return self._outcome(envelope, "select_slot", updated)

    @staticmethod
    def _outcome(envelope, response_intent, task=None):
        task = task or {
            "task_id": "TASK-1",
            "type": "medical_appointment",
            "status": "awaiting_input",
            "current_step": "select_service",
            "facts": {},
        }
        result = CanonicalInteractionResult(
            interaction_id=envelope.interaction_id,
            task=task,
            response_intent=response_intent,
        )
        return task, result, [{"type": "workflow_called"}]


def envelope(session_id, interaction_id, event):
    return EventEnvelope.from_json({
        "routing": {"session_id": session_id, "interaction_id": interaction_id},
        "event": event,
    })


def build_real_core(pipeline=None):
    workflow = MedicalWorkflow(
        pipeline or FakePipeline(),
        "PAT-DEMO-001",
        "Bearer demo",
        mock_user_id="USR-DEMO-001",
    )
    return InteractionCore(
        SessionStore(),
        workflow,
        intent_recognizer=FakeIntentRecognizer(),
    )


class InteractionCoreTests(unittest.TestCase):
    def test_core_starts_selected_workflow_and_saves_returned_task(self):
        sessions = SessionStore()
        workflow = FakeWorkflow()
        core = InteractionCore(sessions, workflow, intent_recognizer=FakeIntentRecognizer())

        result = core.handle(envelope("S-1", "INT-1", {
            "type": "user_utterance", "content": "我想預約醫療服務",
        }))

        state = sessions.get_or_create("S-1")
        self.assertEqual(len(workflow.started), 1)
        self.assertEqual(state.active_task_id, "TASK-1")
        self.assertEqual(state.task, result.task)
        self.assertEqual(state.interaction_log, [{"type": "workflow_called"}])

    def test_core_routes_existing_task_and_saves_workflow_transition(self):
        sessions = SessionStore()
        workflow = FakeWorkflow()
        core = InteractionCore(sessions, workflow, intent_recognizer=FakeIntentRecognizer())
        core.handle(envelope("S-1", "INT-1", {
            "type": "user_utterance", "content": "我想預約醫療服務",
        }))

        result = core.handle(envelope("S-1", "INT-2", {
            "type": "service_selected", "action_id": "ACT-1", "task_id": "TASK-1",
            "service_id": "SERVICE-US-001", "date_from": "2026-08-07", "date_to": "2026-08-14",
        }))

        self.assertEqual(len(workflow.handled), 1)
        self.assertEqual(result.task["current_step"], "select_slot")
        self.assertEqual(sessions.get_or_create("S-1").task["current_step"], "select_slot")

    def test_core_rejects_unsupported_intent_without_creating_task(self):
        sessions = SessionStore()
        core = InteractionCore(sessions, FakeWorkflow(), intent_recognizer=FakeIntentRecognizer("cash_sharing"))

        with self.assertRaisesRegex(ValueError, "unsupported interaction intent"):
            core.handle(envelope("S-1", "INT-1", {
                "type": "user_utterance", "content": "現金分享",
            }))

        self.assertIsNone(sessions.get_or_create("S-1").task)

    def test_core_has_no_execution_dependency(self):
        parameters = inspect.signature(InteractionCore.__init__).parameters
        self.assertNotIn("pipeline", parameters)
        self.assertNotIn("executor", parameters)


if __name__ == "__main__":
    unittest.main()
