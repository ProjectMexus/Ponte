import unittest

from middleware.task_manager.interpreter import DeterministicTaskRecoveryInterpreter
from middleware.task_manager.recovery import build_recovery_plan


class RecoveryPolicyTests(unittest.TestCase):
    def test_missing_required_field_returns_required_field_plan(self):
        plan = build_recovery_plan(
            error={"code": "MISSING_REQUIRED_FIELD", "details": {"field": "contact_phone"}},
            step_id="create_appointment",
            workflow="medical_booking",
            data={},
            result_data=None,
            retryable=False,
        )
        self.assertEqual(plan.reason_code, "MISSING_REQUIRED_FIELD")
        self.assertEqual(plan.required_fields[0].name, "contact_phone")
        self.assertEqual(plan.required_fields[0].label, "聯絡電話")

    def test_empty_search_result_returns_availability_plan(self):
        plan = build_recovery_plan(
            error=None,
            step_id="search_slots",
            workflow="medical_booking",
            data={"service_id": "SERVICE-US-001"},
            result_data=[],
            retryable=False,
        )
        self.assertEqual(plan.reason_code, "NO_AVAILABLE_SLOTS")
        self.assertEqual(plan.category, "availability")

    def test_retryable_backend_error_contains_recovery_actions(self):
        plan = build_recovery_plan(
            error={"code": "BACKEND_TIMEOUT", "message": "timeout"},
            step_id="search_slots",
            workflow="medical_booking",
            data={},
            result_data=None,
            retryable=True,
        )
        self.assertEqual(
            {option.action for option in plan.options},
            {"retry", "cancel", "human_help"},
        )

    def test_retryable_backend_error_preserves_reason_code(self):
        plan = build_recovery_plan(
            error={"code": "BACKEND_UNAVAILABLE"},
            step_id="load_services",
            workflow="medical_booking",
            data={},
            result_data=None,
            retryable=True,
        )
        self.assertEqual(plan.reason_code, "BACKEND_UNAVAILABLE")

    def test_invalid_response_is_hard_failure(self):
        plan = build_recovery_plan(
            error={"code": "BACKEND_INVALID_RESPONSE"},
            step_id="load_appointments",
            workflow="medical_query",
            data={},
            result_data=None,
            retryable=False,
        )
        self.assertIsNone(plan)

    def test_recovery_interpreter_is_separate_from_intent_recognizer(self):
        fallback = build_recovery_plan(
            error={"code": "BACKEND_TIMEOUT"},
            step_id="search_slots",
            workflow="medical_booking",
            data={},
            result_data=None,
            retryable=True,
        )
        interpreted = DeterministicTaskRecoveryInterpreter().interpret(
            error={"code": "BACKEND_TIMEOUT"},
            step_id="search_slots",
            workflow="medical_booking",
            data={},
            fallback=fallback,
        )
        self.assertIs(interpreted, fallback)
        self.assertNotIn("middleware.intent", DeterministicTaskRecoveryInterpreter.__module__)
        for option in interpreted.options:
            self.assertNotIn("REQ-", option.label)
            self.assertNotIn("tool_name", option.label)


if __name__ == "__main__":
    unittest.main()
