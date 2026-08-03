import unittest

from middleware.contracts import InteractionActionRequest, InteractionRequest, ToolExecutionResult
from middleware.controller import InteractionController
from middleware.session import SessionStore


class RecordingPipeline:
    def __init__(self):
        self.calls = []

    def dispatch(self, call):
        self.calls.append(call)
        if call.name == "medical.get_my_appointments":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-1", {"data": []}, None)
        if call.name == "medical.list_appointment_services":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-2", {"data": [{"id": "SERVICE-US-001", "name": "超聲波檢查"}]}, None)
        if call.name == "medical.search_appointment_slots":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-3", {"data": [{"id": "SLOT-US-20260812-1400", "start": "2026-08-12T14:00:00+08:00"}]}, None)
        if call.name == "medical.create_appointment":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-4", {"data": {"task_id": "TASK-1"}, "task": {"id": "TASK-1"}}, None)
        if call.name == "medical.get_task_status":
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-5", {"data": {"status": "SUBMITTED"}}, None)
        raise AssertionError(call.name)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = RecordingPipeline()
        self.controller = InteractionController(self.pipeline, SessionStore(), "PAT-DEMO-001", "Bearer mock-user-token")

    def test_medical_message_loads_appointments_and_services(self):
        response = self.controller.handle_message(InteractionRequest("S-1", "我想查詢醫療預約"))
        self.assertEqual(response["task_state"], "selecting_service")
        self.assertEqual([call.name for call in self.pipeline.calls], [
            "medical.get_my_appointments",
            "medical.list_appointment_services",
        ])

    def test_create_appointment_is_blocked_until_confirmation(self):
        self.controller.handle_message(InteractionRequest("S-1", "我想預約醫療服務"))
        self.controller.handle_action(InteractionActionRequest("S-1", "search_slots", {
            "service_id": "SERVICE-US-001", "date_from": "2026-08-10", "date_to": "2026-08-14",
        }))
        self.controller.handle_action(InteractionActionRequest("S-1", "select_slot", {
            "slot_id": "SLOT-US-20260812-1400",
        }))
        pending = self.controller.handle_action(InteractionActionRequest("S-1", "cancel", {}))
        self.assertEqual(pending["task_state"], "cancelled")
        self.assertNotIn("medical.create_appointment", [call.name for call in self.pipeline.calls])

    def test_confirmation_submits_documented_body_and_reads_task_status(self):
        self.controller.handle_message(InteractionRequest("S-1", "我想預約醫療服務"))
        self.controller.handle_action(InteractionActionRequest("S-1", "search_slots", {
            "service_id": "SERVICE-US-001", "date_from": "2026-08-10", "date_to": "2026-08-14",
        }))
        self.controller.handle_action(InteractionActionRequest("S-1", "select_slot", {
            "slot_id": "SLOT-US-20260812-1400",
        }))
        response = self.controller.handle_action(InteractionActionRequest("S-1", "confirm", {}))
        self.assertEqual(response["task_state"], "submitted")
        create_call = next(call for call in self.pipeline.calls if call.name == "medical.create_appointment")
        self.assertTrue(create_call.arguments["input"]["consent"])
        self.assertNotIn("confirmation", create_call.arguments["input"])
        self.assertEqual(self.pipeline.calls[-1].name, "medical.get_task_status")


if __name__ == "__main__":
    unittest.main()
