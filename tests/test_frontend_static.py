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

    def test_index_is_avatar_first_and_removes_text_workspace(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        for marker in ("ponte-button", "ponte-avatar", "voice-status-panel", "voice-exceptions", "artifact-drawer"):
            self.assertIn(marker, html)
        for removed in ("message-input", "task-list", "conversation-panel", "workspace-panel"):
            self.assertNotIn(removed, html)
        self.assertIn('id="conversation-caption"', html)
        self.assertIn('id="caption-line"', html)
        self.assertNotIn("sound-check-button", html)

    def test_required_voice_assets_are_served_without_a_cache(self):
        for path in ("app.js", "voice-capture.js", "voice-exceptions.js", "mcp-client.js", "ponte2.jpg"):
            with self.opener.open(self.base_url + "/" + path) as response:
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_path_traversal_is_not_served(self):
        with self.assertRaises(Exception):
            self.opener.open(self.base_url + "/../docs/PonteArch.md")

    def test_voice_capture_uses_supported_recording_and_vad_contract(self):
        source = Path("frontend/voice-capture.js").read_text(encoding="utf-8")
        for marker in ("MediaRecorder", "audio/webm", "audio/ogg", "silenceMs: 1350", "minDurationMs: 400", "maxDurationMs: 20_000", "vadThreshold"):
            self.assertIn(marker, source)

    def test_app_protects_the_latest_voice_turn_and_interrupts_audio(self):
        source = Path("frontend/app.js").read_text(encoding="utf-8")
        for marker in ("AbortController", "latestTurn", "AbortError", "stopPlayback", "sendVoiceTurn"):
            self.assertIn(marker, source)
        self.assertIn("showUserSpeech", source)
        self.assertIn("showPonteReply", source)
        self.assertNotIn("sound-check-button", source)

    def test_voice_transport_is_multipart_and_preserves_json_actions(self):
        source = Path("frontend/mcp-client.js").read_text(encoding="utf-8")
        for marker in ('new FormData()', 'form.append("session_id"', 'form.append("turn_id"', 'form.append("audio"', '"/api/voice/turn"'):
            self.assertIn(marker, source)

    def test_exceptions_keep_structured_approval_and_receipt_hooks(self):
        source = Path("frontend/voice-exceptions.js").read_text(encoding="utf-8")
        for marker in ("renderApproval", "renderReceipt", "openArtifact", "response?.approval", "response?.artifact"):
            self.assertIn(marker, source)

    def test_avatar_exceptions_render_appointment_and_recovery_actions(self):
        source = Path("frontend/voice-exceptions.js").read_text(encoding="utf-8")
        for marker in (
            "renderTaskInteraction",
            'task_state === "selecting_service"',
            'task_state === "selecting_slot"',
            'kind: "search_slots"',
            'kind: "select_slot"',
            "recovery?.explanation",
            "recovery?.required_fields",
            "onAction?.(action)",
            "referring_appointment_id",
        ):
            self.assertIn(marker, source)

    def test_speech_fallback_remains_cantonese_capable(self):
        source = Path("frontend/speech.js").read_text(encoding="utf-8")
        for marker in ("SpeechRecognition", "webkitSpeechRecognition", "zh-HK", "speechSynthesis"):
            self.assertIn(marker, source)
        self.assertIn("speechSynthesis.resume", source)
        self.assertIn("speechSynthesis.speak(utterance)", source)

    def test_styles_keep_large_avatar_control_and_visible_focus(self):
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        self.assertIn(".ponte-button", css)
        self.assertIn(".voice-status-panel", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("conversation-caption", css)
        self.assertIn("caption-line", css)


if __name__ == "__main__":
    unittest.main()
