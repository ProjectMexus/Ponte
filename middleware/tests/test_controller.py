import unittest

from middleware.contracts import InteractionActionRequest, InteractionRequest, ToolExecutionResult
from middleware.controller import InteractionController, LegacyInteractionContractError
from middleware.intent import IntentDecision, IntentRecognizer, KeywordIntentRecognizer
from middleware.session import SessionStore


class RecordingPipeline:
    def __init__(self):
        self.calls = []

    def dispatch(self, call):
        self.calls.append(call)
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

    def test_legacy_message_route_rejects_cash_intents_before_tool_calls(self):
        with self.assertRaises(LegacyInteractionContractError) as raised:
            self.controller.handle_message(InteractionRequest("S-LEGACY-CASH", "我想查現金分享計劃"))
        self.assertEqual(raised.exception.code, "INTERACTION_EVENT_REQUIRED")
        self.assertEqual(self.pipeline.calls, [])

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

    def test_legacy_message_route_rejects_medical_intents_before_tool_calls(self):
        for message in ("我想預約醫療服務", "我想查詢自己的醫療預約"):
            with self.assertRaises(LegacyInteractionContractError) as raised:
                self.controller.handle_message(InteractionRequest("S-LEGACY-MED", message))
            self.assertEqual(raised.exception.code, "INTERACTION_EVENT_REQUIRED")
        self.assertEqual(self.pipeline.calls, [])

    def test_legacy_action_route_rejects_medical_actions_before_tool_calls(self):
        retired_actions = (
            ("select_service", {}),
            ("search_slots", {"service_id": "SERVICE-US-001", "date_from": "2026-08-10", "date_to": "2026-08-14"}),
            ("select_slot", {"slot_id": "SLOT-US-20260812-1400"}),
            ("confirm", {}),
            ("retry", {}),
            ("human_help", {}),
        )
        for action, payload in retired_actions:
            with self.assertRaises(LegacyInteractionContractError) as raised:
                self.controller.handle_action(InteractionActionRequest("S-LEGACY-ACT", action, payload))
            self.assertEqual(raised.exception.code, "INTERACTION_EVENT_REQUIRED")
        self.assertEqual(self.pipeline.calls, [])

    def test_legacy_cancel_without_pending_diagnostic_is_rejected(self):
        with self.assertRaises(LegacyInteractionContractError) as raised:
            self.controller.handle_action(InteractionActionRequest("S-LEGACY-ACT", "cancel", {}))
        self.assertEqual(raised.exception.code, "INTERACTION_EVENT_REQUIRED")
        self.assertEqual(self.pipeline.calls, [])


if __name__ == "__main__":
    unittest.main()
