"""Idempotency storage implemented on top of the repository interface."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import RecordRepository
from .errors import DomainError


def canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RepositoryIdempotencyStore:
    def __init__(self, repository: RecordRepository) -> None:
        self.repository = repository

    @staticmethod
    def _record_id(scope: str, key: str) -> str:
        digest = hashlib.sha256(f"{scope}\n{key}".encode("utf-8")).hexdigest()[:24]
        return f"IDEM-{digest}"

    def lookup(self, scope: str, key: str) -> dict[str, Any] | None:
        record = self.repository.get(self._record_id(scope, key))
        if record is None:
            return None
        return {
            "request_hash": record["request_hash"],
            "response": record["response"],
        }

    def remember(
        self,
        scope: str,
        key: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> None:
        record_id = self._record_id(scope, key)
        existing = self.repository.get(record_id)
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise DomainError(
                    409,
                    "IDEMPOTENCY_KEY_REUSED",
                    "Idempotency-Key 已用於不同的 request body。",
                    details={"scope": scope, "key": key},
                    retryable=False,
                )
            return
        self.repository.insert(
            {
                "id": record_id,
                "scope": scope,
                "key": key,
                "request_hash": request_hash,
                "response": response,
            }
        )
