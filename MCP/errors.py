"""Errors exposed by the Ponte MCP adapter layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdapterError(Exception):
    """A structured error that can be returned from an MCP tool call."""

    code: str
    message: str
    status: int | None = None
    details: Any = None
    retryable: bool = False

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def to_dict(self) -> dict[str, Any]:
        """Return the stable error payload used by the MCP layer."""

        return {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "details": self.details,
            "retryable": self.retryable,
        }


class InvalidToolArguments(AdapterError):
    """The client supplied an invalid MCP tool envelope or context."""

    def __init__(
        self,
        message: str = "Invalid tool arguments",
        *,
        details: Any = None,
    ) -> None:
        super().__init__(
            code="INVALID_TOOL_ARGUMENTS",
            message=message,
            status=400,
            details=details,
            retryable=False,
        )


class BackendUnavailable(AdapterError):
    """The configured backend could not be reached."""

    def __init__(
        self,
        message: str = "Backend unavailable",
        *,
        details: Any = None,
    ) -> None:
        super().__init__(
            code="BACKEND_UNAVAILABLE",
            message=message,
            status=503,
            details=details,
            retryable=True,
        )


class BackendTimeout(AdapterError):
    """The configured backend did not respond before the timeout."""

    def __init__(
        self,
        message: str = "Backend request timed out",
        *,
        details: Any = None,
    ) -> None:
        super().__init__(
            code="BACKEND_TIMEOUT",
            message=message,
            status=504,
            details=details,
            retryable=True,
        )


class BackendInvalidResponse(AdapterError):
    """The backend returned a response outside the documented contract."""

    def __init__(
        self,
        message: str = "Backend returned an invalid response",
        *,
        status: int | None = 502,
        details: Any = None,
    ) -> None:
        super().__init__(
            code="BACKEND_INVALID_RESPONSE",
            message=message,
            status=status,
            details=details,
            retryable=False,
        )
