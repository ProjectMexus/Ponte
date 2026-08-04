"""Readable, process-local mock ID generation."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

from .contracts import RecordRepository


class SequentialIdGenerator:
    def __init__(self) -> None:
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._lock = Lock()

    def next(self, prefix: str) -> str:
        with self._lock:
            self._counters[prefix] += 1
            return f"{prefix}-{self._counters[prefix]:04d}"


class TextFileIdGenerator:
    """Readable mock IDs whose counters survive application restarts."""

    def __init__(self, repository: RecordRepository) -> None:
        self.repository = repository
        self._lock = Lock()

    def next(self, prefix: str) -> str:
        with self._lock:
            record_id = f"SEQ-{prefix}"
            record = self.repository.get(record_id)
            value = 0 if record is None else int(record["value"])
            value += 1
            updated = {"id": record_id, "prefix": prefix, "value": value}
            if record is None:
                self.repository.insert(updated)
            else:
                self.repository.replace(record_id, updated)
            return f"{prefix}-{value:04d}"
