"""Small protocols used to keep domain services storage-agnostic."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current timezone-aware time."""


class RecordRepository(Protocol):
    def list(self) -> list[dict[str, Any]]:
        """Return copies of all records."""

    def get(self, record_id: str) -> dict[str, Any] | None:
        """Return a record copy or None."""

    def insert(self, record: dict[str, Any]) -> None:
        """Insert a new record."""

    def replace(self, record_id: str, record: dict[str, Any]) -> None:
        """Replace an existing record."""

    def find(self, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        """Return records matching predicate."""


class IdempotencyStore(Protocol):
    def lookup(self, scope: str, key: str) -> dict[str, Any] | None:
        """Return the saved request hash and response, if any."""

    def remember(
        self,
        scope: str,
        key: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> None:
        """Save a response or reject a conflicting request hash."""


class IdGenerator(Protocol):
    def next(self, prefix: str) -> str:
        """Return a readable unique mock identifier."""
