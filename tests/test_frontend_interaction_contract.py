import unittest
from pathlib import Path


class FrontendInteractionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Path("frontend/app.js").read_text(encoding="utf-8")
        cls.client = Path("frontend/mcp-client.js").read_text(encoding="utf-8")
        cls.view = Path("frontend/interaction-view.js").read_text(encoding="utf-8")
        cls.exceptions = Path("frontend/voice-exceptions.js").read_text(encoding="utf-8")

    def test_client_posts_normalized_interactions(self):
        self.assertIn("sendInteraction(envelope", self.client)
        self.assertIn('this.request("/api/interactions"', self.client)
        self.assertIn('method: "POST"', self.client)
        self.assertIn("JSON.stringify(envelope)", self.client)

    def test_workspace_view_fields_and_actions_are_server_projected(self):
        for marker in ("workspace.view", "workspace.fields", "workspace.actions", "workspace.artifact", "action.event"):
            self.assertIn(marker, self.view)
        self.assertIn("renderCanonicalWorkspace", self.exceptions)

    def test_response_display_and_speech_fields_drive_delivery(self):
        self.assertIn("response.display_text", self.app)
        self.assertIn("response.speech_text", self.app)
        self.assertIn("showPonteReply(displayText)", self.app)
        self.assertIn("speech.speak(speechText", self.app)

    def test_server_audio_requires_ready_status(self):
        self.assertIn("speech_audio", self.app)
        self.assertIn('speechAudio?.status !== "ready"', self.app)
        self.assertIn("speechAudio.url", self.app)
        self.assertIn('audio.addEventListener("error"', self.app)

    def test_browser_stt_uses_normalized_event_envelope(self):
        self.assertIn("client.sendInteraction({", self.app)
        self.assertIn("routing: { interaction_id: makeInteractionId(), session_id: sessionId }", self.app)
        self.assertIn('event: { type: "user_utterance", task_id: null, content: transcript }', self.app)
        self.assertNotIn("client.sendMessage(", self.app)
        self.assertNotIn('source: "voice"', self.app)

    def test_workspace_action_event_is_forwarded_without_frontend_construction(self):
        self.assertIn("onAction?.(action.event)", self.view)
        self.assertIn("renderCanonicalWorkspace", self.exceptions)
        self.assertIn("event,", self.app)
        self.assertNotIn("client.sendAction(", self.app)
        self.assertNotIn("action.payload", self.app)
        self.assertNotIn("sendMessage(body", self.client)
        self.assertNotIn("sendAction(body", self.client)

    def test_frontend_has_no_text_workflow_parsing_or_event_inference(self):
        for source in (self.app, self.view, self.exceptions):
            for removed in (
                "task_state",
                "current_step",
                "search_slots",
                "select_slot",
                "confirm_appointment",
                "assistant_message",
                "receipt.html",
            ):
                self.assertNotIn(removed, source)
        self.assertNotIn("innerHTML", self.view)
        self.assertNotIn("innerHTML", self.exceptions)

    def test_medical_interactions_use_only_the_canonical_endpoint(self):
        for source in (self.app, self.client, self.view, self.exceptions):
            self.assertNotIn("/api/interactions/message", source)
            self.assertNotIn("/api/interactions/action", source)


if __name__ == "__main__":
    unittest.main()
