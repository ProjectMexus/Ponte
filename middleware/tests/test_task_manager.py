import unittest

from middleware.session import SessionState, build_response
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


if __name__ == "__main__":
    unittest.main()
