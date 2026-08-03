"""Transport-neutral request and response values used by domain adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BackendRequest:
    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, list[str]] = field(default_factory=dict)
    body: dict[str, Any] | None = None
    request_id: str = "REQ-LOCAL"

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None


@dataclass
class BackendResponse:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=lambda: {"Content-Type": "application/json"})


def success_body(request_id: str, data: Any) -> dict[str, Any]:
    return {"request_id": request_id, "data": data}
