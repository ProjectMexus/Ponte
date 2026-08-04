import json
import unittest
from unittest.mock import patch

from middleware.intent import (
    HybridIntentRecognizer,
    IntentRecognizer,
    IntentRecognitionError,
    KeywordIntentRecognizer,
    LlmIntentRecognizer,
    build_intent_recognizer,
)


class IntentTests(unittest.TestCase):
    def test_intent_recognizer_is_abstract(self):
        with self.assertRaises(TypeError):
            IntentRecognizer()

    def test_keyword_recognizer_matches_medical_terms(self):
        recognizer = KeywordIntentRecognizer()
        medical = recognizer.recognize("我想改期睇醫生")
        general = recognizer.recognize("你好")
        self.assertTrue(medical.is_medical)
        self.assertTrue(medical.is_medical_booking)
        self.assertEqual(medical.source, "keyword")
        self.assertFalse(general.is_medical)

    def test_keyword_recognizer_separates_my_appointments_from_booking(self):
        recognizer = KeywordIntentRecognizer()
        query = recognizer.recognize("我想查詢自己的醫療預約")
        booking = recognizer.recognize("我想預約醫療服務")
        slots = recognizer.recognize("我想查詢可預約時段")
        self.assertTrue(query.is_medical_query)
        self.assertFalse(query.is_medical_booking)
        self.assertTrue(booking.is_medical_booking)
        self.assertTrue(slots.is_medical_booking)

    def test_keyword_recognizer_matches_cash_sharing_and_activity_terms(self):
        recognizer = KeywordIntentRecognizer()
        self.assertTrue(recognizer.recognize("我想查現金分享計劃").is_cash_sharing)
        self.assertTrue(recognizer.recognize("我想找長者文娛活動").is_elderly_activity)
        self.assertFalse(recognizer.recognize("你好").is_cash_sharing)

    def test_llm_recognizer_sends_json_and_parses_chat_response(self):
        captured = {}

        def transport(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return {
                "choices": [{
                    "message": {
                        "content": '```json\n{"intent":"cash_sharing","confidence":0.8}\n```',
                    },
                }],
            }

        recognizer = LlmIntentRecognizer(
            "https://llm.example.test/v1/chat/completions",
            api_key="test-key",
            model="test-model",
            transport=transport,
        )
        decision = recognizer.recognize("我想查現金分享")
        self.assertTrue(decision.is_cash_sharing)
        self.assertEqual(decision.source, "llm")
        self.assertEqual(decision.confidence, 0.8)
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer test-key")
        self.assertEqual(captured["timeout"], 8.0)

    def test_llm_recognizer_rejects_unsupported_intent(self):
        with self.assertRaises(IntentRecognitionError):
            LlmIntentRecognizer._parse_response({"intent": "passport_renewal"})

    def test_llm_recognizer_parses_both_medical_intents(self):
        for expected, message in (
            ("medical_query", "查詢自己的預約"),
            ("medical_booking", "預約檢查服務"),
        ):
            recognizer = LlmIntentRecognizer(
                "https://llm.example.test/v1/chat/completions",
                transport=lambda request, timeout, value=expected: {
                    "choices": [{"message": {"content": json.dumps({"intent": value})}}]
                },
            )
            self.assertEqual(recognizer.recognize(message).intent, expected)

    def test_hybrid_recognizer_falls_back_when_llm_fails(self):
        class FailingRecognizer(IntentRecognizer):
            def recognize(self, message):
                raise IntentRecognitionError("temporary failure")

        decision = HybridIntentRecognizer(llm=FailingRecognizer()).recognize("我想查詢自己的醫療預約")
        self.assertTrue(decision.is_medical_query)
        self.assertEqual(decision.source, "keyword")

    def test_default_builder_uses_keywords_without_llm_url(self):
        with patch.dict("os.environ", {}, clear=True):
            recognizer = build_intent_recognizer()
        decision = recognizer.recognize("你好")
        self.assertEqual(decision.source, "keyword")
        self.assertFalse(decision.is_medical)


if __name__ == "__main__":
    unittest.main()
