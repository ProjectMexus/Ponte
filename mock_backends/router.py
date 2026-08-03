"""Prefix router that keeps domain adapters independent."""

from __future__ import annotations

from dataclasses import replace

from mock_backends.core.clock import AsiaMacauClock
from mock_backends.core.contracts import Clock
from mock_backends.core.errors import DomainError, error_payload
from mock_backends.core.http import BackendRequest, BackendResponse


class MockRouter:
    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or AsiaMacauClock()
        self._mounts: dict[str, object] = {}

    def mount(self, prefix: str, backend: object) -> None:
        normalized = "/" + prefix.strip("/")
        self._mounts[normalized] = backend

    def dispatch(self, request: BackendRequest) -> BackendResponse:
        for prefix in sorted(self._mounts, key=len, reverse=True):
            if request.path == prefix or request.path.startswith(prefix + "/"):
                backend = self._mounts[prefix]
                relative_path = request.path[len(prefix):] or "/"
                forwarded = replace(request, path=relative_path)
                try:
                    return backend.handle(forwarded)
                except DomainError as error:
                    return BackendResponse(error.status, error_payload(request.request_id, error, self.clock))
                except Exception:
                    error = DomainError(500, "MOCK_SERVICE_ERROR", "Mock service 暫時不可用。", retryable=True)
                    return BackendResponse(error.status, error_payload(request.request_id, error, self.clock))
        error = DomainError(404, "NOT_FOUND", "找不到指定的 mock endpoint。")
        return BackendResponse(error.status, error_payload(request.request_id, error, self.clock))
