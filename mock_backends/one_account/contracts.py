"""One Account domain constants and small validation helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

from mock_backends.core.errors import DomainError


def required_body(body: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise DomainError(400, "INVALID_REQUEST", "request body 必須是 JSON object。")
    return body


def required_idempotency_key(headers: dict[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "idempotency-key" and value:
            return value
    raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "POST 操作必須提供 Idempotency-Key。")


def required_user_id(headers: dict[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "x-mock-user-id" and value:
            return value
    raise DomainError(401, "AUTH_REQUIRED", "缺少 X-Mock-User-Id。")


def parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise DomainError(400, "INVALID_REQUEST", f"{field} 必須是 YYYY-MM-DD。", {"field": field})
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DomainError(400, "INVALID_REQUEST", f"{field} 必須是有效日期。", {"field": field}) from exc
