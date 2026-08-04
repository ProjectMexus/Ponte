import contextlib
import io
import logging
import os
import unittest
from unittest.mock import patch

from ponte_logging import endpoint_label, log_debug_event, log_event


class PonteLoggingTests(unittest.TestCase):
    def test_debug_event_is_hidden_at_info(self):
        with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "INFO"}):
            with self.assertLogs("ponte", level="INFO") as captured:
                log_event("llm", "send", model="test-model")
                log_debug_event("llm", "send", prompt="PATIENT_PROMPT")

        self.assertNotIn("PATIENT_PROMPT", "\n".join(captured.output))

    def test_debug_event_shows_content_and_masks_nested_credentials(self):
        with patch.dict(
            os.environ,
            {
                "PONTE_LOG_LEVEL": "DEBUG",
                "PONTE_LLM_API_KEY": "CONFIGURED_API_KEY",
            },
        ):
            with self.assertLogs("ponte", level="DEBUG") as captured:
                log_debug_event(
                    "mcp",
                    "receive",
                    result={
                        "patient_id": "PAT-001",
                        "authorization": "Bearer NESTED_TOKEN",
                        "nested": {
                            "api_key": "INLINE_KEY",
                            "records": [{"secret": "INLINE_SECRET"}],
                        },
                    },
                    prompt=(
                        "medical data CONFIGURED_API_KEY; "
                        "Authorization: Bearer INLINE_BEARER; token=INLINE_TOKEN"
                    ),
                )

        output = "\n".join(captured.output)
        self.assertIn("PAT-001", output)
        self.assertIn("<redacted>", output)
        for secret in (
            "CONFIGURED_API_KEY",
            "NESTED_TOKEN",
            "INLINE_KEY",
            "INLINE_SECRET",
            "INLINE_BEARER",
            "INLINE_TOKEN",
        ):
            self.assertNotIn(secret, output)

    def test_debug_event_drops_unknown_fields_and_logging_failures(self):
        with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "DEBUG"}):
            with self.assertLogs("ponte", level="DEBUG") as captured:
                log_debug_event(
                    "mcp",
                    "send_debug",
                    request={"patient_id": "PATIENT_REQUEST"},
                    unknown="PATIENT_UNKNOWN_FIELD",
                )

        output = "\n".join(captured.output)
        self.assertIn("PATIENT_REQUEST", output)
        self.assertNotIn("PATIENT_UNKNOWN_FIELD", output)
        self.assertNotIn("unknown", output)

        with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "DEBUG"}):
            with patch(
                "ponte_logging._LOGGER.debug",
                side_effect=RuntimeError("SECRET_LOG_FAILURE"),
            ):
                log_debug_event("llm", "send_debug", prompt="PATIENT_PROMPT")

    def test_event_has_component_and_only_safe_fields(self):
        with self.assertLogs("ponte", level="INFO") as captured:
            log_event(
                "llm",
                "send",
                request_id="LLM-ABC",
                model="gemini-2.5-flash-lite",
                message_chars=12,
                prompt="PATIENT_SECRET_PROMPT",
                api_key="SECRET_KEY",
                authorization="Bearer SECRET_AUTHORIZATION",
                cookie="SECRET_COOKIE",
                patient_name="PATIENT_NAME",
                input_keys=["PATIENT_SECRET_VALUE"],
            )

        output = "\n".join(captured.output)
        self.assertIn("[llm]", output)
        self.assertIn("model=gemini-2.5-flash-lite", output)
        self.assertIn("message_chars=12", output)
        self.assertNotIn("PATIENT_SECRET_PROMPT", output)
        self.assertNotIn("SECRET_KEY", output)
        self.assertNotIn("SECRET_AUTHORIZATION", output)
        self.assertNotIn("SECRET_COOKIE", output)
        self.assertNotIn("PATIENT_NAME", output)
        self.assertNotIn("PATIENT_SECRET_VALUE", output)
        self.assertNotIn("prompt=", output)
        self.assertNotIn("api_key=", output)
        self.assertNotIn("authorization=", output)
        self.assertNotIn("cookie=", output)
        self.assertNotIn("patient_name=", output)

    def test_endpoint_label_removes_query_and_fragment(self):
        self.assertEqual(
            endpoint_label("https://llm.example/v1/chat?api_key=SECRET#x"),
            "llm.example/v1/chat",
        )
        self.assertEqual(endpoint_label("/api/intent?patient_id=SECRET#fragment"), "/api/intent")

    def test_path_redacts_medical_identifier_segments(self):
        with self.assertLogs("ponte", level="INFO") as captured:
            log_event(
                "backend",
                "request_end",
                method="GET",
                path="/mock/medical/v1/appointments/APT-0001",
                status=200,
            )

        output = "\n".join(captured.output)
        self.assertIn("path=/mock/medical/v1/appointments/:id", output)
        self.assertNotIn("APT-0001", output)

    def test_unknown_level_falls_back_to_info(self):
        with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "NOT_A_LEVEL"}):
            with self.assertLogs("ponte", level="INFO") as captured:
                log_event("backend", "request_end", status=200)
        self.assertTrue(captured.output)

    def test_log_level_is_read_on_each_event(self):
        logger = logging.getLogger("ponte")
        with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "WARNING"}):
            log_event("backend", "request_end", status=200)
            self.assertEqual(logger.level, logging.WARNING)

        with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "DEBUG"}):
            log_event("backend", "request_end", status=200)
            self.assertEqual(logger.level, logging.DEBUG)

    def test_scalar_formatting_is_safe_and_bounded(self):
        long_value = "x" * 200
        with self.assertLogs("ponte", level="INFO") as captured:
            log_event(
                "middleware",
                "request_end",
                request_id="REQ-1\nSECOND-LINE",
                confidence=0.123456789,
                latency_ms=None,
                outcome=True,
                error_type=long_value,
                input_keys={"secret": "value"},
            )

        output = "\n".join(captured.output)
        self.assertIn("request_id=REQ-1 SECOND-LINE", output)
        self.assertIn("confidence=0.123457", output)
        self.assertIn("latency_ms=none", output)
        self.assertIn("outcome=true", output)
        self.assertIn("error_type=" + "x" * 120, output)
        self.assertNotIn("secret", output)
        self.assertNotIn("value", output)
        self.assertLessEqual(output.count("x"), 120)

    def test_invalid_component_and_unknown_fields_are_dropped(self):
        with patch("ponte_logging._LOGGER.info") as logger_info:
            log_event(
                "not-a-component",
                "request_end",
                status=200,
                unknown="UNKNOWN_MARKER",
            )
        logger_info.assert_not_called()

        with self.assertLogs("ponte", level="INFO") as captured:
            log_event(
                "backend",
                "request_end",
                status=200,
                unknown="UNKNOWN_MARKER",
            )
        output = "\n".join(captured.output)
        self.assertIn("status=200", output)
        self.assertNotIn("UNKNOWN_MARKER", output)
        self.assertNotIn("unknown=", output)

    def test_logger_failure_does_not_escape(self):
        with patch("ponte_logging._LOGGER.info", side_effect=RuntimeError("SECRET_LOG_FAILURE")):
            log_event("backend", "request_end", status=200)

    def test_default_output_uses_stderr(self):
        stderr = io.StringIO()
        with patch.dict(os.environ, {"PONTE_LOG_LEVEL": "INFO"}):
            with contextlib.redirect_stderr(stderr):
                log_event("frontend", "request_end", method="GET", path="/", status=200)
        self.assertIn("INFO [frontend] request_end", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
