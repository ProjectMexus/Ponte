"""Medical backend validation helpers."""

from __future__ import annotations

from typing import Any

from mock_backends.core.errors import DomainError


def required_body(body: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise DomainError(400, "INVALID_REQUEST", "request body 必須是 JSON object。")
    return body


def required_patient(headers: dict[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "x-patient-id" and value:
            return value
    raise DomainError(401, "AUTH_REQUIRED", "缺少 X-Patient-Id。")


def required_idempotency_key(headers: dict[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "idempotency-key" and value:
            return value
    raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "建立操作必須提供 Idempotency-Key。")
