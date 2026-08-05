import json
import os
import unittest
from unittest.mock import patch

from middleware.task_manager.interpreter import (
    DeterministicTaskRecoveryInterpreter,
    LlmTaskRecoveryInterpreter,
    build_task_recovery_interpreter,
)
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

    def test_duplicate_booking_returns_generic_service_picker(self):
        plan = build_recovery_plan(
            error={
                "code": "DUPLICATE_BOOKING",
                "message": "同一病人已有衝突的有效預約。",
            },
            step_id="create_appointment",
            workflow="medical_booking",
            data={
                "service_id": "SERVICE-US-001",
                "date_from": "2026-08-10",
                "date_to": "2026-08-14",
            },
            result_data=None,
            retryable=False,
        )
        self.assertEqual(plan.category, "booking_conflict")
        self.assertEqual(plan.reason_code, "DUPLICATE_BOOKING")
        self.assertIn("不能再預約", plan.explanation)
        self.assertEqual(
            {option.action for option in plan.options},
            {"select_service", "cancel", "human_help"},
        )
        picker = next(option for option in plan.options if option.action == "select_service")
        self.assertEqual(picker.label, "重新選擇其他服務／科室")
        self.assertEqual(dict(picker.payload), {})
        self.assertNotIn("同一病人已有衝突的有效預約。", plan.explanation)

    def test_duplicate_booking_does_not_choose_a_fixed_alternative_service(self):
        plan = build_recovery_plan(
            error={"code": "DUPLICATE_BOOKING"},
            step_id="create_appointment",
            workflow="medical_booking",
            data={
                "service_id": "SERVICE-PT-001",
                "date_from": "2026-08-05",
                "date_to": "2026-08-19",
                "services": [
                    {"id": "SERVICE-US-001", "name": "腹部超聲波檢查"},
                    {"id": "SERVICE-PT-001", "name": "物理治療"},
                    {"id": "SERVICE-CARDIO-001", "name": "心臟科門診"},
                ],
            },
            result_data=None,
            retryable=False,
        )

        self.assertEqual(
            [option.action for option in plan.options],
            ["select_service", "cancel", "human_help"],
        )
        self.assertNotIn("service_id", plan.options[0].payload)

    def test_slot_taken_during_confirmation_returns_same_service_search_option(self):
        plan = build_recovery_plan(
            error={"code": "SLOT_NOT_AVAILABLE"},
            step_id="create_appointment",
            workflow="medical_booking",
            data={
                "service_id": "SERVICE-US-001",
                "date_from": "2026-08-10",
                "date_to": "2026-08-14",
            },
            result_data=None,
            retryable=False,
        )

        self.assertEqual(plan.reason_code, "SLOT_NOT_AVAILABLE")
        search = next(option for option in plan.options if option.action == "search_slots")
        self.assertEqual(search.payload["service_id"], "SERVICE-US-001")
        self.assertEqual(search.payload["date_from"], "2026-08-10")
        self.assertIn("其他可預約時段", plan.explanation)

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

    def test_configured_task_recovery_llm_uses_separate_safe_context(self):
        captured = {}

        def transport(request, timeout):
            del timeout
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "category": "booking_conflict",
                            "reason_code": "DUPLICATE_BOOKING",
                            "explanation": "這個時段已有衝突預約，請重新搜尋其他時段。",
                            "required_fields": [],
                            "options": [
                                {
                                    "action": "search_slots",
                                    "label": "重新搜尋其他時段",
                                    "payload": {
                                        "service_id": "SERVICE-US-001",
                                        "date_from": "2026-08-10",
                                        "date_to": "2026-08-14",
                                    },
                                },
                                {"action": "cancel", "label": "取消預約", "payload": {}},
                            ],
                        }, ensure_ascii=False),
                    },
                }],
            }

        interpreter = LlmTaskRecoveryInterpreter(
            "https://recovery.example.test/v1/chat/completions",
            api_key="RECOVERY_KEY",
            model="recovery-model",
            transport=transport,
        )
        with patch("middleware.task_manager.interpreter.log_event") as log_event:
            plan = interpreter.interpret(
                error={
                    "code": "DUPLICATE_BOOKING",
                    "status": 409,
                    "message": "RAW BACKEND MESSAGE",
                    "details": {"message": "RAW BACKEND MESSAGE"},
                    "retryable": False,
                },
                step_id="create_appointment",
                workflow="medical_booking",
                data={
                    "service_id": "SERVICE-US-001",
                    "date_from": "2026-08-10",
                    "date_to": "2026-08-14",
                    "slot_id": "SLOT-INTERNAL-001",
                    "patient_id": "PATIENT-INTERNAL-001",
                    "services": [
                        {"id": "SERVICE-US-001", "name": "腹部超聲波檢查", "patient_id": "PATIENT-INTERNAL-001"},
                        {"id": "SERVICE-PT-001", "name": "物理治療"},
                    ],
                },
                fallback=None,
            )

        self.assertIsNotNone(plan)
        self.assertEqual(plan.reason_code, "DUPLICATE_BOOKING")
        self.assertEqual(plan.options[0].action, "search_slots")
        user_context = captured["body"]["messages"][1]["content"]
        self.assertNotIn("RAW BACKEND MESSAGE", user_context)
        self.assertNotIn("PATIENT-INTERNAL-001", user_context)
        self.assertNotIn("SLOT-INTERNAL-001", user_context)
        self.assertIn("SERVICE-PT-001", user_context)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer RECOVERY_KEY")
        self.assertTrue(any(call.args[1] == "send" and call.kwargs["operation"] == "task_recovery" for call in log_event.call_args_list))

    def test_task_recovery_configuration_does_not_reuse_intent_settings(self):
        with patch.dict(
            os.environ,
            {
                "PONTE_LLM_API_URL": "https://intent.example.test/v1/chat/completions",
                "PONTE_TASK_RECOVERY_LLM_API_URL": "https://recovery.example.test/v1/chat/completions",
            },
            clear=False,
        ):
            interpreter = build_task_recovery_interpreter()
        self.assertIsInstance(interpreter, LlmTaskRecoveryInterpreter)
        self.assertEqual(interpreter.api_url, "https://recovery.example.test/v1/chat/completions")

        with patch.dict(
            os.environ,
            {
                "PONTE_LLM_API_URL": "https://intent.example.test/v1/chat/completions",
                "PONTE_TASK_RECOVERY_LLM_API_URL": "",
            },
            clear=False,
        ):
            fallback = build_task_recovery_interpreter()
        self.assertIsInstance(fallback, DeterministicTaskRecoveryInterpreter)


if __name__ == "__main__":
    unittest.main()
