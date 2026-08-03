from datetime import datetime, timezone
import unittest

from middleware.contracts import InteractionActionRequest, InteractionRequest
from middleware.session import SessionStore


class ContractTests(unittest.TestCase):
    def test_message_request_accepts_text_and_voice(self):
        text = InteractionRequest.from_json({
            "session_id": "S-1",
            "message": "我想查醫療預約",
            "source": "text",
        })
        voice = InteractionRequest.from_json({
            "session_id": "S-1",
            "message": "我想改期",
            "source": "voice",
        })
        self.assertEqual(text.source, "text")
        self.assertEqual(voice.source, "voice")

    def test_invalid_message_request_is_rejected(self):
        with self.assertRaises(ValueError):
            InteractionRequest.from_json({"message": "沒有 session"})

    def test_action_request_defaults_payload_to_empty_object(self):
        request = InteractionActionRequest.from_json({
            "session_id": "S-1",
            "action": "cancel",
        })
        self.assertEqual(request.payload, {})

    def test_session_store_preserves_confirmation_record(self):
        store = SessionStore()
        state = store.get_or_create("S-1")
        state.confirmation_record = {
            "decision": "confirmed",
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "step_id": "confirm_appointment",
        }
        store.save(state)
        self.assertEqual(store.get_or_create("S-1").confirmation_record["decision"], "confirmed")


if __name__ == "__main__":
    unittest.main()
