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
        for marker in (
            "ponte-button",
            "ponte-avatar",
            "voice-status-panel",
            "operational-status",
            "language-toggle",
            "voice-exceptions",
            "artifact-drawer",
        ):
            self.assertIn(marker, html)
        for removed in ("message-input", "task-list", "conversation-panel", "workspace-panel"):
            self.assertNotIn(removed, html)
        self.assertIn('id="conversation-caption"', html)
        self.assertIn('id="caption-line"', html)
        self.assertNotIn("sound-check-button", html)
        self.assertNotIn("stop-audio-button", html)
        self.assertNotIn("Stop reply", html)

    def test_display_language_is_traditional_chinese_first_and_state_only(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        source = Path("frontend/app.js").read_text(encoding="utf-8")
        self.assertIn('data-locale="zh-Hant"', html)
        self.assertIn('data-locale="en"', html)
        self.assertIn('let displayLocale = "zh-Hant"', source)
        for marker in (
            "DISPLAY_COPY",
            'processing: ["小澳在思考中。"',
            '"speaking-response": ["小澳正在回應。"',
            'processing: ["Ponte is thinking."',
            '"speaking-response": ["Ponte is replying."',
            'user: "你"',
            'assistant: "小澳"',
            'user: "You"',
            'assistant: "Ponte"',
            "document.documentElement.lang = locale",
        ):
            self.assertIn(marker, source)
        self.assertIn('recognition.lang = "zh-HK"', Path("frontend/speech.js").read_text(encoding="utf-8"))

    def test_operational_panel_uses_existing_health_and_voice_signals(self):
        source = Path("frontend/app.js").read_text(encoding="utf-8")
        for marker in (
            "service-status-value",
            "voice-path-value",
            "microphone-status-value",
            "backend_reachable",
            "voice_ready",
            "backendVoiceReady",
            "speech.supported",
        ):
            self.assertIn(marker, source)

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
        self.assertNotIn("stopAudioButton", source)
        self.assertIn('state === "speaking-response"', source)
        self.assertIn("latestTurn += 1", source)
        self.assertIn('setState("ready")', source)

    def test_action_click_cancels_previous_audio_before_clearing_error(self):
        source = Path("frontend/app.js").read_text(encoding="utf-8")
        action_block = source.split("async function handleAction", 1)[1].split("const exceptions", 1)[0]
        self.assertIn("interruptCurrentTurn();", action_block)
        self.assertLess(action_block.index("interruptCurrentTurn();"), action_block.index("exceptions.clearError();"))
        for marker in (
            "activeSpeechTurn",
            "activeSpeechTurn === latestTurn",
            'state === "audio-error" && activeSpeechTurn === latestTurn',
        ):
            self.assertIn(marker, source)

    def test_voice_transport_is_multipart_and_preserves_json_actions(self):
        source = Path("frontend/mcp-client.js").read_text(encoding="utf-8")
        for marker in ('new FormData()', 'form.append("session_id"', 'form.append("turn_id"', 'form.append("audio"', '"/api/voice/turn"'):
            self.assertIn(marker, source)

    def test_exceptions_keep_structured_approval_and_receipt_hooks(self):
        source = Path("frontend/voice-exceptions.js").read_text(encoding="utf-8")
        for marker in ("renderApproval", "renderReceipt", "openArtifact", "response?.approval", "response?.artifact"):
            self.assertIn(marker, source)
        self.assertIn("syncExceptionSurface", source)

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
        self.assertIn("clamp(500px", css)
        self.assertIn(".language-option", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn(".operational-status", css)
        self.assertNotIn(".stop-audio", css)

    def test_demo_popups_are_centered_translucent_and_theme_consistent(self):
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        for marker in (
            ".voice-exceptions.has-modal",
            "place-items: center",
            "backdrop-filter: blur(12px)",
            "rgba(250, 250, 252, .82)",
            ".artifact-drawer",
            ".artifact-sheet",
            "animation: modal-in",
        ):
            self.assertIn(marker, css)

    def test_apple_material_tokens_keep_system_type_and_quiet_surface(self):
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        for marker in (
            '"SF Pro Display"',
            "-webkit-font-smoothing: antialiased",
            "--canvas: #f5f5f7",
            "--accent: #0a84ff",
            "rgba(255, 255, 255, .68)",
        ):
            self.assertIn(marker, css)

    def test_transient_captions_and_errors_auto_dismiss(self):
        app = Path("frontend/app.js").read_text(encoding="utf-8")
        exceptions = Path("frontend/voice-exceptions.js").read_text(encoding="utf-8")
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        for marker in ("captionTimer", "clearTimeout(captionTimer)", "setTimeout", "currentCaption = null"):
            self.assertIn(marker, app)
        for marker in ("errorTimer", "clearTimeout(errorTimer)", "setTimeout", "clearError()", "8000"):
            self.assertIn(marker, exceptions)
        self.assertIn("color: #667085", css)
        self.assertIn("font-size: clamp(.86rem", css)
        self.assertIn("font-size: .74rem", css)


if __name__ == "__main__":
    unittest.main()
