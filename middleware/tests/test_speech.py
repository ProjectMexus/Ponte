import unittest

from middleware.session import SessionState, build_response
from middleware.speech import to_cantonese_spoken


class CantoneseSpeechTests(unittest.TestCase):
    def test_converts_common_written_phrases_to_spoken_cantonese(self):
        text = "我已查到你目前的醫療預約，請選擇一個時段。"

        self.assertEqual(
            to_cantonese_spoken(text),
            "我幫你查到你而家嘅醫療預約，麻煩你揀一個時間。",
        )

    def test_preserves_unknown_service_names_and_identifiers(self):
        text = "服務 ABC-123 目前沒有資料。"

        spoken = to_cantonese_spoken(text)

        self.assertIn("ABC-123", spoken)
        self.assertIn("服務", spoken)
        self.assertIn("而家冇資料", spoken)

    def test_build_response_includes_written_and_spoken_messages(self):
        state = SessionState("S-SPEECH")

        response = build_response(state, "請選擇一個時段。", [])

        self.assertEqual(response["assistant_message"], "請選擇一個時段。")
        self.assertEqual(
            response["assistant_speech_message"],
            "麻煩你揀一個時間。",
        )


if __name__ == "__main__":
    unittest.main()
