"""Tiny JSON Lines repositories backed by files ending in .txt."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any, Callable


class _PathLocks:
    _locks: dict[str, RLock] = {}
    _guard = RLock()

    @classmethod
    def for_path(cls, path: Path) -> RLock:
        key = str(path.resolve())
        with cls._guard:
            return cls._locks.setdefault(key, RLock())


class MemoryRepository:
    def __init__(self, id_field: str = "id") -> None:
        self.id_field = id_field
        self._records: dict[str, dict[str, Any]] = {}

    def list(self) -> list[dict[str, Any]]:
        return copy.deepcopy(list(self._records.values()))

    def get(self, record_id: str) -> dict[str, Any] | None:
        record = self._records.get(record_id)
        return copy.deepcopy(record) if record is not None else None

    def insert(self, record: dict[str, Any]) -> None:
        record_id = record.get(self.id_field)
        if not record_id:
            raise ValueError(f"record must contain {self.id_field}")
        if record_id in self._records:
            raise ValueError(f"duplicate record ID: {record_id}")
        self._records[record_id] = copy.deepcopy(record)

    def replace(self, record_id: str, record: dict[str, Any]) -> None:
        if record_id not in self._records:
            raise KeyError(record_id)
        if record.get(self.id_field) != record_id:
            raise ValueError(f"replacement ID must be {record_id}")
        self._records[record_id] = copy.deepcopy(record)

    def find(self, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        return [record for record in self.list() if predicate(record)]


class JsonLinesTextRepository:
    def __init__(self, path: str | Path, id_field: str = "id") -> None:
        self.path = Path(path)
        self.id_field = id_field
        self._lock = _PathLocks.for_path(self.path)

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    raise ValueError(f"invalid blank line {line_number} in {self.path}")
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON at line {line_number} in {self.path}") from exc
                if not isinstance(record, dict):
                    raise ValueError(f"line {line_number} in {self.path} is not a JSON object")
                if not record.get(self.id_field):
                    raise ValueError(f"line {line_number} in {self.path} has no {self.id_field}")
                records.append(record)
        return records

    def _write_unlocked(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, self.path)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._read_unlocked())

    def get(self, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            for record in self._read_unlocked():
                if record.get(self.id_field) == record_id:
                    return copy.deepcopy(record)
        return None

    def insert(self, record: dict[str, Any]) -> None:
        record_id = record.get(self.id_field)
        if not record_id:
            raise ValueError(f"record must contain {self.id_field}")
        with self._lock:
            records = self._read_unlocked()
            if any(item.get(self.id_field) == record_id for item in records):
                raise ValueError(f"duplicate record ID: {record_id}")
            records.append(copy.deepcopy(record))
            self._write_unlocked(records)

    def replace(self, record_id: str, record: dict[str, Any]) -> None:
        if record.get(self.id_field) != record_id:
            raise ValueError(f"replacement ID must be {record_id}")
        with self._lock:
            records = self._read_unlocked()
            for index, existing in enumerate(records):
                if existing.get(self.id_field) == record_id:
                    records[index] = copy.deepcopy(record)
                    self._write_unlocked(records)
                    return
        raise KeyError(record_id)

    def find(self, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        return [record for record in self.list() if predicate(record)]
