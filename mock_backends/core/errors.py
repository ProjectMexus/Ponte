"""Domain errors and the shared error envelope."""

from __future__ import annotations

from typing import Any

from .contracts import Clock


class DomainError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Any = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details if details is not None else {}
        self.retryable = retryable

    def as_dict(self, timestamp: str) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
            "timestamp": timestamp,
        }


def error_payload(request_id: str, error: DomainError, clock: Clock) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "error": error.as_dict(clock.now().isoformat()),
    }
