import unittest
from datetime import datetime, timezone, timedelta

from mock_backends.core.clock import FixedClock, MACAU_TZ
from mock_backends.core.errors import DomainError, error_payload


class CoreHelperTests(unittest.TestCase):
    def test_fixed_clock_requires_aware_datetime(self):
        now = datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ)
        self.assertEqual(FixedClock(now).now(), now)
        with self.assertRaises(ValueError):
            FixedClock(datetime(2026, 8, 3, 9, 0))

    def test_fixed_clock_accepts_utc_plus_eight(self):
        now = datetime(2026, 8, 3, 1, 0, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(FixedClock(now).now(), now)

    def test_domain_error_payload(self):
        now = datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ)
        error = DomainError(
            422,
            "VALIDATION_ERROR",
            "欄位無效。",
            details={"field": "name"},
            retryable=False,
        )
        payload = error_payload("REQ-1", error, FixedClock(now))
        self.assertEqual(payload["request_id"], "REQ-1")
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")
        self.assertFalse(payload["error"]["retryable"])
        self.assertEqual(payload["error"]["timestamp"], "2026-08-03T09:00:00+08:00")
