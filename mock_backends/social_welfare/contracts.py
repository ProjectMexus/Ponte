"""Validation helpers for the Arch-derived welfare contract."""

from __future__ import annotations

from typing import Any

from mock_backends.core.errors import DomainError


def body_or_empty(body: dict[str, Any] | None) -> dict[str, Any]:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise DomainError(400, "INVALID_REQUEST", "request body 必須是 JSON object。")
    return body


def required_body(body: dict[str, Any] | None) -> dict[str, Any]:
    result = body_or_empty(body)
    if not result:
        raise DomainError(400, "INVALID_REQUEST", "request body 不可以為空。")
    return result


def required_user(headers: dict[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "x-mock-user-id" and value:
            return value
    raise DomainError(401, "AUTH_REQUIRED", "缺少 X-Mock-User-Id。")


def required_idempotency_key(headers: dict[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "idempotency-key" and value:
            return value
    raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "建立或 assign 操作必須提供 Idempotency-Key。")
