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
        self.assertEqual(medical.source, "keyword")
        self.assertFalse(general.is_medical)

    def test_llm_recognizer_sends_json_and_parses_chat_response(self):
        captured = {}

        def transport(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return {
                "choices": [{
                    "message": {
                        "content": '```json\n{"intent":"medical_appointment","confidence":0.92}\n```',
                    },
                }],
            }

        recognizer = LlmIntentRecognizer(
            "https://llm.example.test/v1/chat/completions",
            api_key="test-key",
            model="test-model",
            transport=transport,
        )
        decision = recognizer.recognize("我想預約超聲波")
        self.assertTrue(decision.is_medical)
        self.assertEqual(decision.source, "llm")
        self.assertEqual(decision.confidence, 0.92)
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer test-key")
        self.assertEqual(captured["timeout"], 8.0)

    def test_hybrid_recognizer_falls_back_when_llm_fails(self):
        class FailingRecognizer(IntentRecognizer):
            def recognize(self, message):
                raise IntentRecognitionError("temporary failure")

        decision = HybridIntentRecognizer(llm=FailingRecognizer()).recognize("我想查醫療預約")
        self.assertTrue(decision.is_medical)
        self.assertEqual(decision.source, "keyword")

    def test_default_builder_uses_keywords_without_llm_url(self):
        with patch.dict("os.environ", {}, clear=True):
            recognizer = build_intent_recognizer()
        decision = recognizer.recognize("你好")
        self.assertEqual(decision.source, "keyword")
        self.assertFalse(decision.is_medical)


if __name__ == "__main__":
    unittest.main()
