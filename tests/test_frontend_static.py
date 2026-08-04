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
            'id="task-steps"',
            'id="action-list"',
        ):
            self.assertIn(token, html)
        self.assertIn('lang="zh-Hant"', html)

    def test_index_advertises_mcp_diagnostic_command(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn("mcp medical.list_departments {}", html)

    def test_frontend_supports_diagnostic_confirmation_action(self):
        self.assertIn(
            "confirm_tool",
            Path("frontend/README.md").read_text(encoding="utf-8"),
        )
        self.assertIn("sendAction", Path("frontend/app.js").read_text(encoding="utf-8"))
        self.assertIn(
            "action.kind || action.id",
            Path("frontend/interaction-view.js").read_text(encoding="utf-8"),
        )

    def test_styles_define_large_controls_and_focus(self):
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"font-size:\s*20px")
        self.assertRegex(css, r"min-height:\s*56px")
        self.assertIn(":focus-visible", css)

    def test_view_module_exports_renderer(self):
        js = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        self.assertIn("createInteractionView", js)
        self.assertIn("tool_events", js)
        self.assertIn("actions", js)

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

    def test_speech_module_has_fallback_and_cantonese_locale(self):
        js = Path("frontend/speech.js").read_text(encoding="utf-8")
        self.assertIn("SpeechRecognition", js)
        self.assertIn("webkitSpeechRecognition", js)
        self.assertIn("zh-HK", js)
        self.assertIn("speechSynthesis", js)

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
