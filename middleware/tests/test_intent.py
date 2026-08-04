import contextlib
import io
import json
import os
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

    def test_llm_recognizer_logs_safe_send_and_receive_summaries(self):
        secret_message = "PATIENT_SECRET_MESSAGE"

        def transport(request, timeout):
            return {
                "choices": [{
                    "message": {
                        "content": (
                            '{"intent":"medical_query","confidence":0.9,'
                            '"note":"response_secret"}'
                        ),
                    },
                }],
            }

        recognizer = LlmIntentRecognizer(
            "https://llm.example.test/v1/chat/completions",
            api_key="API_KEY_SECRET",
            model="test-model",
            transport=transport,
        )
        with self.assertLogs("ponte", level="INFO") as captured:
            decision = recognizer.recognize(secret_message)

        output = "\n".join(captured.output)
        self.assertEqual(decision.intent, "medical_query")
        self.assertIn("[llm]", output)
        self.assertIn("send", output)
        self.assertIn("receive", output)
        self.assertIn("request_id=LLM-", output)
        self.assertIn("model=test-model", output)
        self.assertIn("endpoint=llm.example.test/v1/chat/completions", output)
        self.assertIn("message_count=2", output)
        self.assertIn(f"message_chars={len(secret_message)}", output)
        self.assertIn("intent=medical_query", output)
        self.assertIn("confidence=0.9", output)
        self.assertRegex(output, r"latency_ms=\d+")
        self.assertNotIn(secret_message, output)
        self.assertNotIn("response_secret", output)
        self.assertNotIn("API_KEY_SECRET", output)
        self.assertNotIn("Authorization", output)
        self.assertNotIn("test-key", output)

    def test_llm_debug_logs_prompt_and_provider_response(self):
        recognizer = LlmIntentRecognizer(
            "https://llm.example.test/v1/chat/completions",
            api_key="CONFIGURED_API_KEY",
            model="test-model",
            transport=lambda request, timeout: {
                "choices": [{
                    "message": {
                        "content": (
                            '{"intent":"medical_query","confidence":0.91,'
                            '"appointment_id":"APT-DEBUG-001"}'
                        ),
                    },
                }],
            },
        )
        with patch.dict(
            os.environ,
            {"PONTE_LOG_LEVEL": "DEBUG", "PONTE_LLM_API_KEY": "CONFIGURED_API_KEY"},
        ):
            with self.assertLogs("ponte", level="DEBUG") as captured:
                recognizer.recognize("查詢我的醫療預約 PATIENT-DEBUG-001")

        output = "\n".join(captured.output)
        self.assertIn("prompt=", output)
        self.assertIn("查詢我的醫療預約 PATIENT-DEBUG-001", output)
        self.assertIn("response=", output)
        self.assertIn("APT-DEBUG-001", output)
        self.assertIn("intent=medical_query", output)
        self.assertIn("confidence=0.91", output)
        self.assertRegex(output, r"latency_ms=\d+")
        self.assertNotIn("CONFIGURED_API_KEY", output)

    def test_llm_debug_content_is_hidden_at_info(self):
        prompt_marker = "查詢我的醫療預約 PATIENT-INFO-ONLY-001"
        response_marker = "APT-INFO-ONLY-001"
        recognizer = LlmIntentRecognizer(
            "https://llm.example.test/v1/chat/completions",
            api_key="CONFIGURED_API_KEY",
            model="test-model",
            transport=lambda request, timeout: {
                "choices": [{
                    "message": {
                        "content": (
                            '{"intent":"medical_query","confidence":0.83,'
                            f'"appointment_id":"{response_marker}"}}'
                        ),
                    },
                }],
            },
        )
        with patch.dict(
            os.environ,
            {"PONTE_LOG_LEVEL": "INFO", "PONTE_LLM_API_KEY": "CONFIGURED_API_KEY"},
        ):
            with self.assertLogs("ponte", level="INFO") as captured:
                recognizer.recognize(prompt_marker)

        output = "\n".join(captured.output)
        self.assertIn("[llm] send", output)
        self.assertIn("[llm] receive", output)
        self.assertNotIn(prompt_marker, output)
        self.assertNotIn(response_marker, output)
        self.assertNotIn("CONFIGURED_API_KEY", output)

    def test_llm_terminal_stderr_contains_only_safe_summary(self):
        recognizer = LlmIntentRecognizer(
            "https://llm.example.test/v1/chat/completions?secret=URL_SECRET",
            api_key="API_KEY_SECRET",
            model="test-model",
            transport=lambda request, timeout: {
                "choices": [{
                    "message": {
                        "content": (
                            '{"intent":"medical_query","confidence":0.9,'
                            '"response":"MEDICAL_RESPONSE_SECRET"}'
                        ),
                    },
                }],
            },
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            recognizer.recognize("PATIENT_PROMPT_SECRET")

        output = stderr.getvalue()
        self.assertIn("[llm] send", output)
        self.assertIn("[llm] receive", output)
        self.assertIn("model=test-model", output)
        self.assertIn("intent=medical_query", output)
        self.assertIn("confidence=0.9", output)
        self.assertIn("latency_ms=", output)
        self.assertNotIn("PATIENT_PROMPT_SECRET", output)
        self.assertNotIn("MEDICAL_RESPONSE_SECRET", output)
        self.assertNotIn("API_KEY_SECRET", output)
        self.assertNotIn("URL_SECRET", output)

    def test_llm_recognizer_logs_safe_error_without_exception_message(self):
        def transport(request, timeout):
            raise RuntimeError("EXCEPTION_SECRET_MESSAGE")

        recognizer = LlmIntentRecognizer(
            "https://llm.example.test/v1/chat/completions?api_key=SECRET",
            api_key="test-key",
            model="test-model",
            transport=transport,
        )
        with self.assertLogs("ponte", level="INFO") as captured:
            with self.assertRaises(IntentRecognitionError):
                recognizer.recognize("PATIENT_SECRET_MESSAGE")

        output = "\n".join(captured.output)
        self.assertIn("[llm] error", output)
        self.assertIn("request_id=LLM-", output)
        self.assertIn("outcome=error", output)
        self.assertIn("error_code=llm_intent_error", output)
        self.assertIn("error_type=RuntimeError", output)
        self.assertRegex(output, r"latency_ms=\d+")
        self.assertNotIn("EXCEPTION_SECRET_MESSAGE", output)
        self.assertNotIn("PATIENT_SECRET_MESSAGE", output)
        self.assertNotIn("SECRET", output)

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
                raise IntentRecognitionError("ORIGINAL_FAILURE_SECRET")

        with self.assertLogs("ponte", level="INFO") as captured:
            decision = HybridIntentRecognizer(llm=FailingRecognizer()).recognize(
                "我想查詢自己的醫療預約"
            )

        output = "\n".join(captured.output)
        self.assertTrue(decision.is_medical_query)
        self.assertEqual(decision.source, "keyword")
        self.assertIn("[middleware] intent_decision", output)
        self.assertIn("intent=medical_query", output)
        self.assertIn("confidence=1", output)
        self.assertIn("source=keyword", output)
        self.assertIn("fallback_reason=llm_error", output)
        self.assertNotIn("ORIGINAL_FAILURE_SECRET", output)

    def test_hybrid_recognizer_logs_unconfigured_fallback(self):
        with self.assertLogs("ponte", level="INFO") as captured:
            decision = HybridIntentRecognizer().recognize("你好")

        output = "\n".join(captured.output)
        self.assertEqual(decision.intent, "general")
        self.assertIn("[middleware] intent_decision", output)
        self.assertIn("intent=general", output)
        self.assertIn("confidence=1", output)
        self.assertIn("source=keyword", output)
        self.assertIn("fallback_reason=llm_not_configured", output)

    def test_hybrid_recognizer_logs_llm_source(self):
        class SuccessfulRecognizer(IntentRecognizer):
            def recognize(self, message):
                return LlmIntentRecognizer._parse_response(
                    {"intent": "cash_sharing", "confidence": 0.75}
                )

        with self.assertLogs("ponte", level="INFO") as captured:
            decision = HybridIntentRecognizer(llm=SuccessfulRecognizer()).recognize("SECRET_MESSAGE")

        output = "\n".join(captured.output)
        self.assertEqual(decision.source, "llm")
        self.assertIn("[middleware] intent_decision", output)
        self.assertIn("intent=cash_sharing", output)
        self.assertIn("confidence=0.75", output)
        self.assertIn("source=llm", output)
        self.assertNotIn("SECRET_MESSAGE", output)
        self.assertNotIn("fallback_reason=", output)

    def test_default_builder_uses_keywords_without_llm_url(self):
        with patch.dict("os.environ", {}, clear=True):
            recognizer = build_intent_recognizer()
        decision = recognizer.recognize("你好")
        self.assertEqual(decision.source, "keyword")
        self.assertFalse(decision.is_medical)


if __name__ == "__main__":
    unittest.main()
