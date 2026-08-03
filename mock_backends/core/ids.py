"""Readable, process-local mock ID generation."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


class SequentialIdGenerator:
    def __init__(self) -> None:
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._lock = Lock()

    def next(self, prefix: str) -> str:
        with self._lock:
            self._counters[prefix] += 1
            return f"{prefix}-{self._counters[prefix]:04d}"
