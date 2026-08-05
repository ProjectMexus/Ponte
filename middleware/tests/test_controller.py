import json
import unittest

from middleware.contracts import InteractionActionRequest, InteractionRequest, ToolExecutionResult
from middleware.controller import InteractionController
from middleware.intent import IntentDecision, IntentRecognizer, KeywordIntentRecognizer
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
        if call.name == "one_account.get_cash_sharing_plan":
            return ToolExecutionResult(
                call.name,
                call.step_id,
                True,
                "REQ-6",
                {"data": {"plan_name": "現金分享計劃", "status": "ELIGIBLE"}},
                None,
            )
        if call.name == "one_account.search_elderly_activities":
            return ToolExecutionResult(
                call.name,
                call.step_id,
                True,
                "REQ-7",
                {"data": [{"activity_id": "ACT-001", "title": "長者閱讀班"}]},
                None,
            )
        if call.name == "medical.list_departments":
            return ToolExecutionResult(
                call.name,
                call.step_id,
                True,
                "REQ-8",
                {"data": {"departments": [{"id": "DEP-CARD", "name": "心臟科"}]}},
                None,
            )
        if call.name == "one_account.book_government_service_center_queue":
            return ToolExecutionResult(
                call.name,
                call.step_id,
                True,
                "REQ-9",
                {"data": {"ticket": {"ticket_id": "Q-GSC-001"}}},
                None,
            )
        raise AssertionError(call.name)


class TimeoutThenSuccessPipeline(RecordingPipeline):
    def __init__(self):
        super().__init__()
        self.slot_attempts = 0

    def dispatch(self, call):
        if call.name == "medical.search_appointment_slots" and self.slot_attempts == 0:
            self.calls.append(call)
            self.slot_attempts += 1
            return ToolExecutionResult(
                call.name,
                call.step_id,
                False,
                "REQ-TIMEOUT",
                None,
                {"code": "BACKEND_TIMEOUT", "message": "backend timeout", "retryable": True},
            )
        return super().dispatch(call)


class EmptySlotsPipeline(RecordingPipeline):
    def dispatch(self, call):
        if call.name == "medical.search_appointment_slots":
            self.calls.append(call)
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-EMPTY", {"data": []}, None)
        return super().dispatch(call)


class DuplicateBookingOnConfirmPipeline(RecordingPipeline):
    def dispatch(self, call):
        if call.name == "medical.create_appointment":
            self.calls.append(call)
            return ToolExecutionResult(
                call.name,
                call.step_id,
                False,
                "REQ-DUPLICATE-BOOKING",
                None,
                {
                    "code": "DUPLICATE_BOOKING",
                    "message": "同一病人已有衝突的有效預約。",
                    "status": 409,
                    "details": {"message": "同一病人已有衝突的有效預約。"},
                    "retryable": False,
                },
            )
        return super().dispatch(call)


class AlternativeServiceDuplicateBookingPipeline(RecordingPipeline):
    def dispatch(self, call):
        if call.name == "medical.list_appointment_services":
            self.calls.append(call)
            return ToolExecutionResult(
                call.name,
                call.step_id,
                True,
                "REQ-SERVICES-ALTERNATIVE",
                {
                    "data": [
                        {"id": "SERVICE-PT-001", "name": "物理治療"},
                        {"id": "SERVICE-US-001", "name": "腹部超聲波檢查"},
                    ],
                },
                None,
            )
        if call.name == "medical.search_appointment_slots":
            self.calls.append(call)
            service_id = call.arguments["input"]["service_id"]
            if service_id == "SERVICE-PT-001":
                return ToolExecutionResult(
                    call.name,
                    call.step_id,
                    True,
                    "REQ-SLOT-PT",
                    {"data": [{"id": "SLOT-PT-20260813-1000", "start": "2026-08-13T10:00:00+08:00"}]},
                    None,
                )
        if call.name == "medical.create_appointment":
            self.calls.append(call)
            return ToolExecutionResult(
                call.name,
                call.step_id,
                False,
                "REQ-DUPLICATE-ALTERNATIVE",
                None,
                {"code": "DUPLICATE_BOOKING", "status": 409, "retryable": False},
            )
        return super().dispatch(call)


class InvalidAppointmentsPipeline(RecordingPipeline):
    def dispatch(self, call):
        if call.name == "medical.get_my_appointments":
            self.calls.append(call)
            return ToolExecutionResult(call.name, call.step_id, True, "REQ-INVALID", {"unexpected": []}, None)
        return super().dispatch(call)


class AlwaysGeneralRecognizer(IntentRecognizer):
    def recognize(self, message):
        return IntentDecision("general", "llm", 0.99)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = RecordingPipeline()
        self.controller = InteractionController(
            self.pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )

    def test_medical_query_loads_only_my_appointments(self):
        response = self.controller.handle_message(
            InteractionRequest("S-QUERY", "我想查詢自己的醫療預約")
        )
        self.assertEqual(response["task_state"], "completed")
        self.assertEqual(response["current_step"], "load_appointments")
        self.assertEqual(response["data"]["appointments"], [])
        self.assertEqual(
            [call.name for call in self.pipeline.calls],
            ["medical.get_my_appointments"],
        )

    def test_medical_booking_loads_appointments_and_services(self):
        response = self.controller.handle_message(
            InteractionRequest("S-BOOKING", "我想預約醫療服務")
        )
        self.assertEqual(response["task_state"], "selecting_service")
        self.assertEqual(response["actions"][0]["kind"], "search_slots")
        self.assertEqual([call.name for call in self.pipeline.calls], [
            "medical.get_my_appointments",
            "medical.list_appointment_services",
        ])

    def test_new_message_resets_previous_workflow_data(self):
        self.controller.handle_message(InteractionRequest("S-REUSE", "我想預約醫療服務"))
        self.controller.handle_action(InteractionActionRequest("S-REUSE", "search_slots", {
            "service_id": "SERVICE-US-001",
            "date_from": "2026-08-10",
            "date_to": "2026-08-14",
        }))
        self.controller.handle_action(InteractionActionRequest("S-REUSE", "select_slot", {
            "slot_id": "SLOT-US-20260812-1400",
        }))

        query = self.controller.handle_message(
            InteractionRequest("S-REUSE", "我想查詢自己的醫療預約")
        )

        self.assertEqual(query["data"]["appointments"], [])
        for stale_key in ("services", "slots", "selected_slot", "service_id", "slot_id"):
            self.assertNotIn(stale_key, query["data"])
        self.assertEqual([step["step_id"] for step in query["steps"]], ["load_appointments"])
        self.assertEqual(
            [event["tool_name"] for event in query["tool_events"]],
            ["medical.get_my_appointments"],
        )

    def test_cash_sharing_message_calls_one_account_tool(self):
        response = self.controller.handle_message(
            InteractionRequest("S-CASH", "我想查現金分享計劃")
        )
        self.assertEqual(response["task_state"], "completed")
        self.assertEqual(
            [call.name for call in self.pipeline.calls],
            ["one_account.get_cash_sharing_plan"],
        )
        self.assertEqual(
            self.pipeline.calls[0].arguments["context"]["mock_user_id"],
            "USR-DEMO-001",
        )

    def test_activity_message_calls_activity_search_tool(self):
        response = self.controller.handle_message(
            InteractionRequest("S-ACTIVITY", "我想找長者文娛活動")
        )
        self.assertEqual(response["task_state"], "completed")
        self.assertEqual(
            [event["tool_name"] for event in response["tool_events"]],
            ["one_account.search_elderly_activities"],
        )
        self.assertEqual(
            self.pipeline.calls[0].arguments["input"],
            {"available_only": True},
        )

    def test_diagnostic_get_returns_contract_and_backend_data(self):
        response = self.controller.handle_message(
            InteractionRequest(
                "S-DIAG-1",
                'mcp medical.list_departments {"keyword":"心臟"}',
            )
        )
        self.assertEqual(response["mode"], "mcp_diagnostic")
        self.assertEqual(response["task_state"], "completed")
        self.assertEqual(response["data"]["diagnostic"]["http_method"], "GET")
        self.assertEqual(
            response["data"]["diagnostic"]["path"],
            "/mock/medical/v1/departments",
        )
        self.assertEqual(response["tool_events"][0]["tool_name"], "medical.list_departments")
        self.assertEqual(
            response["data"]["backend_response"]["data"]["departments"][0]["id"],
            "DEP-CARD",
        )

    def test_diagnostic_post_requires_confirmation_and_confirm_dispatches(self):
        pending = self.controller.handle_message(
            InteractionRequest(
                "S-DIAG-2",
                'mcp one_account.book_government_service_center_queue '
                '{"service_center_id":"GSC-MAIN",'
                '"service_type":"general_counter","requested_date":"2026-08-20",'
                '"confirmation":{"confirmation_id":"DEMO-CONF"}}',
            )
        )
        self.assertEqual(pending["task_state"], "awaiting_confirmation")
        self.assertEqual(pending["tool_events"], [])
        self.assertEqual(pending["actions"][0]["kind"], "confirm_tool")
        self.assertFalse(any(call.name.startswith("one_account.book_") for call in self.pipeline.calls))

        confirmed = self.controller.handle_action(
            InteractionActionRequest("S-DIAG-2", "confirm_tool", {"ignored": "value"})
        )
        self.assertEqual(confirmed["task_state"], "completed")
        self.assertEqual(
            [call.name for call in self.pipeline.calls],
            ["one_account.book_government_service_center_queue"],
        )
        self.assertEqual(
            confirmed["data"]["backend_response"]["data"]["ticket"]["ticket_id"],
            "Q-GSC-001",
        )
        call_context = self.pipeline.calls[0].arguments["context"]
        self.assertEqual(call_context["mock_user_id"], "USR-DEMO-001")
        self.assertTrue(call_context["idempotency_key"].startswith("IDEMP-MW-"))

    def test_controller_uses_injected_intent_recognizer(self):
        controller = InteractionController(
            self.pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=AlwaysGeneralRecognizer(),
        )
        response = controller.handle_message(InteractionRequest("S-2", "我想預約醫療服務"))
        self.assertEqual(response["task_state"], "idle")
        self.assertEqual(response["data"]["intent_source"], "llm")
        self.assertEqual(self.pipeline.calls, [])

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

    def test_backend_timeout_keeps_booking_task_open_for_retry(self):
        pipeline = TimeoutThenSuccessPipeline()
        controller = InteractionController(
            pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        controller.handle_message(InteractionRequest("S-RECOVER", "我想預約醫療服務"))
        first = controller.handle_action(InteractionActionRequest("S-RECOVER", "search_slots", {
            "service_id": "SERVICE-US-001",
            "date_from": "2026-08-10",
            "date_to": "2026-08-14",
        }))
        self.assertEqual(first["task_state"], "awaiting_user_input")
        self.assertEqual(first["recovery"]["reason_code"], "BACKEND_TIMEOUT")
        self.assertIn("retry", [action["kind"] for action in first["actions"]])

        second = controller.handle_action(InteractionActionRequest("S-RECOVER", "retry", {}))
        self.assertEqual(second["task_state"], "selecting_slot")
        self.assertEqual(second["data"]["service_id"], "SERVICE-US-001")

    def test_empty_slots_explain_availability_and_keep_task_open(self):
        pipeline = EmptySlotsPipeline()
        controller = InteractionController(
            pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        controller.handle_message(InteractionRequest("S-EMPTY", "我想預約醫療服務"))
        response = controller.handle_action(InteractionActionRequest("S-EMPTY", "search_slots", {
            "service_id": "SERVICE-US-001",
            "date_from": "2026-08-10",
            "date_to": "2026-08-14",
        }))
        self.assertEqual(response["task_state"], "awaiting_user_input")
        self.assertEqual(response["recovery"]["reason_code"], "NO_AVAILABLE_SLOTS")
        self.assertIn("沒有可預約名額", response["assistant_message"])

    def test_duplicate_booking_submit_returns_safe_recovery_actions(self):
        pipeline = DuplicateBookingOnConfirmPipeline()
        controller = InteractionController(
            pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        controller.handle_message(InteractionRequest("S-DUPLICATE", "我想預約醫療服務"))
        controller.handle_action(InteractionActionRequest("S-DUPLICATE", "search_slots", {
            "service_id": "SERVICE-US-001",
            "date_from": "2026-08-10",
            "date_to": "2026-08-14",
        }))
        controller.handle_action(InteractionActionRequest("S-DUPLICATE", "select_slot", {
            "slot_id": "SLOT-US-20260812-1400",
        }))

        response = controller.handle_action(InteractionActionRequest("S-DUPLICATE", "confirm", {}))

        self.assertEqual(response["task_state"], "awaiting_user_input")
        self.assertEqual(response["recovery"]["reason_code"], "DUPLICATE_BOOKING")
        self.assertIn("不能再預約", response["assistant_message"])
        self.assertEqual(
            {action["kind"] for action in response["actions"]},
            {"search_slots", "cancel", "human_help"},
        )
        self.assertNotIn("同一病人已有衝突的有效預約。", json.dumps(response, ensure_ascii=False))

        search_option = next(
            action for action in response["actions"] if action["kind"] == "search_slots"
        )
        continued = controller.handle_action(
            InteractionActionRequest("S-SLOT-RACE", "search_slots", search_option["payload"])
        )
        self.assertEqual(continued["task_state"], "selecting_slot")
        self.assertEqual(continued["data"]["service_id"], "SERVICE-US-001")

    def test_duplicate_booking_offers_loaded_alternative_service(self):
        pipeline = AlternativeServiceDuplicateBookingPipeline()
        controller = InteractionController(
            pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        controller.handle_message(InteractionRequest("S-ALTERNATIVE", "我想預約醫療服務"))
        controller.handle_action(InteractionActionRequest("S-ALTERNATIVE", "search_slots", {
            "service_id": "SERVICE-PT-001",
            "date_from": "2026-08-05",
            "date_to": "2026-08-19",
        }))
        controller.handle_action(InteractionActionRequest("S-ALTERNATIVE", "select_slot", {
            "slot_id": "SLOT-PT-20260813-1000",
        }))

        failed = controller.handle_action(InteractionActionRequest("S-ALTERNATIVE", "confirm", {}))

        self.assertEqual(failed["recovery"]["reason_code"], "DUPLICATE_BOOKING")
        search_options = [action for action in failed["actions"] if action["kind"] == "search_slots"]
        self.assertEqual(search_options[0]["payload"]["service_id"], "SERVICE-US-001")
        self.assertIn("超聲波", search_options[0]["label"])

        continued = controller.handle_action(
            InteractionActionRequest("S-ALTERNATIVE", "search_slots", search_options[0]["payload"])
        )
        self.assertEqual(continued["task_state"], "selecting_slot")
        self.assertEqual(continued["data"]["service_id"], "SERVICE-US-001")

    def test_invalid_backend_response_remains_hard_failed(self):
        pipeline = InvalidAppointmentsPipeline()
        controller = InteractionController(
            pipeline,
            SessionStore(),
            "PAT-DEMO-001",
            "Bearer mock-user-token",
            intent_recognizer=KeywordIntentRecognizer(),
        )
        response = controller.handle_message(InteractionRequest("S-INVALID", "我想查詢自己的醫療預約"))
        self.assertEqual(response["task_state"], "failed")
        self.assertNotIn("recovery", response)
        self.assertEqual(response["error"]["code"], "BACKEND_INVALID_RESPONSE")


if __name__ == "__main__":
    unittest.main()
