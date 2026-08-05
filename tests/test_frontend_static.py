import threading
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from frontend.server import create_http_server


class FrontendStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_http_server("127.0.0.1", 0, Path("frontend"))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_client_asset_is_served(self):
        with self.opener.open(self.base_url + "/mcp-client.js") as response:
            self.assertIn("MiddlewareClient", response.read().decode("utf-8"))

    def test_static_assets_are_not_cached_during_local_development(self):
        with self.opener.open(self.base_url + "/app.js") as response:
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_path_traversal_is_not_served(self):
        with self.assertRaises(Exception):
            self.opener.open(self.base_url + "/../docs/PonteArch.md")

    def test_index_has_required_landmarks_and_controls(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        for token in (
            "<main",
            'aria-live="polite"',
            'id="message-input"',
            'id="mic-button"',
            'id="speak-stop-button"',
            'id="task-list"',
        ):
            self.assertIn(token, html)
        self.assertIn('lang="zh-Hant"', html)

    def test_index_exposes_task_workspace_root(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn('id="task-list"', html)
        self.assertIn('aria-label="服務任務"', html)
        self.assertNotIn('id="task-content"', html)

    def test_index_hides_developer_only_diagnostics(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="mode-badge"', html)
        self.assertNotIn("mcp medical.list_departments {}", html)
        self.assertIn('id="speech-status"', html)
        self.assertIn('id="task-list"', html)

    def test_frontend_supports_diagnostic_confirmation_action(self):
        self.assertIn(
            "confirm_tool",
            Path("frontend/README.md").read_text(encoding="utf-8"),
        )
        self.assertIn("sendAction", Path("frontend/app.js").read_text(encoding="utf-8"))
        self.assertIn(
            "action.kind || action.action || action.id",
            Path("frontend/interaction-view.js").read_text(encoding="utf-8"),
        )

    def test_frontend_submits_actions_returned_by_middleware(self):
        app = Path("frontend/app.js").read_text(encoding="utf-8")
        view = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        self.assertIn("action.kind || action.action || action.id", app)
        self.assertIn("action.kind || action.action || action.id", view)

    def test_styles_define_large_controls_and_focus(self):
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"font-size:\s*20px")
        self.assertRegex(css, r"min-height:\s*56px")
        self.assertIn(":focus-visible", css)

    def test_styles_keep_desktop_conversation_reachable(self):
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        self.assertRegex(
            css,
            r"\.conversation-panel\s*\{[^}]*position:\s*sticky;[^}]*height:\s*calc\(100dvh - 40px\);",
        )
        self.assertRegex(
            css,
            r"\.workspace-panel\s*\{[^}]*height:\s*calc\(100dvh - 40px\);[^}]*overflow-y:\s*auto;",
        )
        self.assertRegex(
            css,
            r"\.conversation-list\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;",
        )
        self.assertRegex(
            css,
            r"@media\s*\(max-width:\s*900px\)[\s\S]*?\.conversation-panel,\s*\.workspace-panel\s*\{[^}]*position:\s*static;[^}]*height:\s*auto;[^}]*overflow:\s*visible;",
        )

    def test_view_module_exports_renderer(self):
        js = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        self.assertIn("createInteractionView", js)
        self.assertIn("renderMedicalData", js)
        self.assertIn("actions", js)

    def test_view_supports_task_workspace_lifecycle(self):
        source = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        for marker in (
            "TaskRecord",
            "startTask",
            "updateTask",
            "continueTask",
            "toggleTask",
            "task-card",
            'createElement("details")',
            "medical_query",
            "appointments",
            "awaiting_user_input",
            "renderRecovery",
            "recovery.explanation",
            "onAction(action, task.localId)",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("taskRoot.replaceChildren()", source)

    def test_view_supports_collapsible_step_history(self):
        source = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        for marker in (
            "stepHistory",
            "updateStepHistory",
            "stepHistoryKey",
            "snapshotResponse",
            "stepDataForSnapshot",
            'createElement("details", "task-step-details")',
            "task-step-summary",
            "task-step-detail",
            "entry.expanded",
        ):
            self.assertIn(marker, source)
        self.assertIn("task.stepHistory = updateStepHistory", source)
        self.assertNotIn("renderSteps(steps, response.steps", source)
        for marker in (
            "selected_action",
            "renderActionHistory",
            "latestStepOwnsResponseContent",
            "重新選擇其他服務／科室",
            'step?.step_id === "get_task_status"',
        ):
            self.assertIn(marker, source)
        self.assertIn('actionKind(action) !== "search_slots"', source)

    def test_app_routes_message_and_action_to_task_ids(self):
        source = Path("frontend/app.js").read_text(encoding="utf-8")
        self.assertIn("startTask", source)
        self.assertIn("updateTask", source)
        self.assertIn("continueTask", source)
        self.assertIn("taskId", source)

    def test_view_uses_friendly_service_workspace_fields(self):
        source = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        for marker in (
            "LOCATION_LABELS",
            "LOC-REHAB-01",
            "復康治療室",
            "STEP_LABELS",
            "renderMedicalData",
            "所需時間",
            "服務地點",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("renderToolEvents", source)
        self.assertNotIn("tool-event-card", source)
        self.assertNotIn("request_id", source)

    def test_styles_prioritize_summary_cards(self):
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        self.assertIn(".summary-card", css)
        self.assertNotIn(".tool-event-card", css)

    def test_view_module_supports_medical_booking_action_contract(self):
        source = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        for marker in (
            "selecting_service",
            "date_from",
            "date_to",
            "service_id",
            "selecting_slot",
            "slot_id",
        ):
            self.assertIn(marker, source)
        self.assertIn('kind: "search_slots"', source)
        self.assertIn('kind: "select_slot"', source)

    def test_view_supports_mock_referral_confirmation(self):
        source = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        for marker in (
            "confirm_appointment",
            "referring_appointment_id",
            "APT-REF-1",
        ):
            self.assertIn(marker, source)

    def test_speech_module_has_fallback_and_cantonese_locale(self):
        js = Path("frontend/speech.js").read_text(encoding="utf-8")
        self.assertIn("SpeechRecognition", js)
        self.assertIn("webkitSpeechRecognition", js)
        self.assertIn("zh-HK", js)
        self.assertIn("speechSynthesis", js)
        self.assertIn("try", js)
        self.assertIn("catch", js)

    def test_frontend_supports_written_and_spoken_reply_toggle(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        app = Path("frontend/app.js").read_text(encoding="utf-8")

        self.assertIn('id="speak-stop-button"', html)
        self.assertIn('aria-pressed="true"', html)
        self.assertIn("自動朗讀：開", html)
        self.assertIn("assistant_speech_message", app)
        self.assertIn("autoSpeakEnabled", app)
        self.assertIn("speech.stopSpeaking()", app)
        self.assertIn(
            "response.assistant_speech_message || response.assistant_message",
            app,
        )

    def test_app_wires_client_view_and_speech(self):
        js = Path("frontend/app.js").read_text(encoding="utf-8")
        for token in (
            "MiddlewareClient",
            "createInteractionView",
            "createSpeechController",
            "sendMessage",
            "sendAction",
        ):
            self.assertIn(token, js)


if __name__ == "__main__":
    unittest.main()
