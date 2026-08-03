"""Timezone-aware clocks for production-like and deterministic runs."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo

    MACAU_TZ: tzinfo = ZoneInfo("Asia/Macau")
except Exception:  # pragma: no cover - only used on minimal Python images
    MACAU_TZ = timezone.utc


class AsiaMacauClock:
    def now(self) -> datetime:
        return datetime.now(MACAU_TZ)


class FixedClock:
    def __init__(self, value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._value = value

    def now(self) -> datetime:
        return self._value
