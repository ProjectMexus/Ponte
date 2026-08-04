import unittest
from unittest.mock import patch

from middleware.session import SessionState, build_response
from middleware.contracts import ToolCall, ToolExecutionResult
from middleware.task_manager.contracts import RecoveryOption, RecoveryPlan
from middleware.task_manager.transitions import InvalidTaskTransition, ensure_transition


class TaskManagerContractTests(unittest.TestCase):
    def test_awaiting_user_input_is_not_terminal_and_can_resume(self):
        ensure_transition("querying", "awaiting_user_input")
        ensure_transition("awaiting_user_input", "selecting_slot")

    def test_terminal_task_cannot_resume(self):
        with self.assertRaises(InvalidTaskTransition):
            ensure_transition("completed", "querying")

    def test_recovery_plan_serializes_safe_options(self):
        plan = RecoveryPlan(
            category="availability",
            reason_code="NO_AVAILABLE_SLOTS",
            explanation="目前沒有可預約名額。",
            options=(RecoveryOption("retry", "重新搜尋", {}),),
        )
        self.assertEqual(plan.to_dict()["options"][0]["action"], "retry")

    def test_task_manager_response_contains_recovery_and_actions(self):
        from middleware.task_manager.manager import TaskManager

        state = SessionState("S-TASK-MANAGER")
        manager = TaskManager(state)
        plan = RecoveryPlan(
            category="missing_information",
            reason_code="MISSING_REQUIRED_FIELD",
            explanation="服務中心需要補充資料才能繼續。",
            options=(RecoveryOption("cancel", "取消", {}),),
        )

        manager.transition("querying", "load_appointments")
        manager.request_user_input(plan)
        response = build_response(state, "請補充資料。", [])

        self.assertEqual(response["task_state"], "awaiting_user_input")
        self.assertEqual(response["recovery"]["reason_code"], "MISSING_REQUIRED_FIELD")
        self.assertEqual(response["actions"][0]["kind"], "cancel")

    def test_tool_failure_keeps_workflow_data_and_records_retry_call(self):
        from middleware.task_manager.manager import TaskManager

        state = SessionState("S-RECOVER-MANAGER")
        state.data.update({
            "intent": "medical_booking",
            "service_id": "SERVICE-US-001",
            "date_from": "2026-08-10",
            "date_to": "2026-08-14",
        })
        manager = TaskManager(state)
        manager.transition("querying", "search_slots")
        call = ToolCall(
            "medical.search_appointment_slots",
            {"context": {}, "input": {"service_id": "SERVICE-US-001"}},
            "search_slots",
        )
        result = ToolExecutionResult(
            call.name,
            call.step_id,
            False,
            "REQ-TIMEOUT",
            None,
            {"code": "BACKEND_TIMEOUT", "message": "timeout", "retryable": True},
        )

        manager.record_tool_result(
            result,
            "search_slots",
            {"service_id": "SERVICE-US-001"},
            safe_for_retry=True,
            workflow="medical_booking",
            call=call,
        )

        self.assertEqual(state.task_state, "awaiting_user_input")
        self.assertIsNotNone(state.recovery)
        self.assertIs(state.last_tool_call, call)
        self.assertEqual(state.data["service_id"], "SERVICE-US-001")
        self.assertEqual(state.data["date_from"], "2026-08-10")
        self.assertEqual(state.tool_events[0]["error"]["code"], "BACKEND_TIMEOUT")

        manager.start_action()
        self.assertIsNone(state.recovery)
        self.assertIsNone(state.last_error)
        self.assertEqual(state.data["service_id"], "SERVICE-US-001")

    def test_configured_recovery_interpreter_receives_sanitized_submit_error(self):
        from middleware.task_manager.manager import TaskManager

        class RecordingInterpreter:
            def __init__(self):
                self.calls = []

            def interpret(self, **kwargs):
                self.calls.append(kwargs)
                return kwargs["fallback"]

        state = SessionState("S-DUPLICATE-MANAGER")
        state.data.update({
            "intent": "medical_booking",
            "service_id": "SERVICE-US-001",
            "date_from": "2026-08-10",
            "date_to": "2026-08-14",
        })
        interpreter = RecordingInterpreter()
        manager = TaskManager(state, interpreter)
        manager.transition("awaiting_confirmation", "confirm_appointment")
        manager.transition("submitting", "create_appointment")
        result = ToolExecutionResult(
            "medical.create_appointment",
            "create_appointment",
            False,
            "REQ-DUPLICATE-MANAGER",
            None,
            {
                "code": "DUPLICATE_BOOKING",
                "message": "RAW BACKEND CONFLICT MESSAGE",
                "status": 409,
                "details": {"message": "RAW BACKEND CONFLICT MESSAGE"},
                "retryable": False,
            },
        )

        manager.record_tool_result(
            result,
            "create_appointment",
            {"service_id": "SERVICE-US-001", "slot_id": "SLOT-US-20260812-1400"},
            safe_for_retry=False,
            workflow="medical_booking",
        )

        self.assertEqual(state.task_state, "awaiting_user_input")
        self.assertEqual(len(interpreter.calls), 1)
        self.assertEqual(interpreter.calls[0]["error"]["code"], "DUPLICATE_BOOKING")
        self.assertNotIn("message", interpreter.calls[0]["error"])
        self.assertNotIn("RAW BACKEND CONFLICT MESSAGE", str(build_response(state, "請選擇下一步。", [])))

    def test_recovery_interpreter_call_logs_safe_summary(self):
        from middleware.task_manager.manager import TaskManager

        state = SessionState("S-RECOVERY-LOG")
        state.data.update({"intent": "medical_booking", "service_id": "SERVICE-US-001"})
        manager = TaskManager(state)
        manager.transition("querying", "search_slots")
        result = ToolExecutionResult(
            "medical.search_appointment_slots",
            "search_slots",
            False,
            "REQ-TIMEOUT-LOG",
            None,
            {"code": "BACKEND_TIMEOUT", "message": "RAW TIMEOUT MESSAGE", "retryable": True},
        )

        with patch("middleware.task_manager.manager.log_event") as log_event:
            manager.record_tool_result(
                result,
                "search_slots",
                {"service_id": "SERVICE-US-001"},
                safe_for_retry=True,
                workflow="medical_booking",
            )

        calls = [call for call in log_event.call_args_list if call.args[1] == "recovery_interpreter_call"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs["error_code"], "BACKEND_TIMEOUT")
        self.assertEqual(calls[0].kwargs["source"], "deterministic_fallback")
        self.assertEqual(calls[0].kwargs["operation"], "task_recovery")


if __name__ == "__main__":
    unittest.main()
