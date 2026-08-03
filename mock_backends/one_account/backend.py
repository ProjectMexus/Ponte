"""HTTP-shaped adapter for the One Account domain service."""

from __future__ import annotations

from typing import Any

from mock_backends.core.contracts import Clock
from mock_backends.core.errors import DomainError, error_payload
from mock_backends.core.http import BackendRequest, BackendResponse

from .contracts import required_user_id
from .service import OneAccountService


class OneAccountBackend:
    prefix = "/mock/one-account"

    def __init__(self, service: OneAccountService, clock: Clock | None = None) -> None:
        self.service = service
        self.clock = clock or service.clock

    def _relative_path(self, path: str) -> str:
        if path.startswith(self.prefix):
            path = path[len(self.prefix):]
        return path or "/"

    def _error(self, request: BackendRequest, error: DomainError) -> BackendResponse:
        return BackendResponse(error.status, error_payload(request.request_id, error, self.clock))

    def handle(self, request: BackendRequest) -> BackendResponse:
        path = self._relative_path(request.path)
        try:
            if request.method == "POST" and path == "/pension/applications":
                return self.service.submit_pension_application(
                    required_user_id(request.headers),
                    request.headers,
                    request.body,
                    request.request_id,
                    path,
                )
            if request.method == "GET" and path == "/cash-sharing-plan":
                return self.service.get_cash_sharing_plan(
                    required_user_id(request.headers), request.query, request.request_id
                )
            if request.method == "POST" and path == "/queue-tickets/government-service-center":
                return self.service.create_queue_ticket(
                    required_user_id(request.headers),
                    "government_service_center",
                    request.body,
                    request.headers,
                    request.request_id,
                    path,
                )
            if request.method == "POST" and path == "/queue-tickets/identification-services-bureau":
                return self.service.create_queue_ticket(
                    required_user_id(request.headers),
                    "identification_services_bureau",
                    request.body,
                    request.headers,
                    request.request_id,
                    path,
                )
            if request.method == "GET" and path == "/my/queue-tickets":
                return self.service.list_queue_tickets(
                    required_user_id(request.headers), request.query, request.request_id
                )
            raise DomainError(404, "NOT_FOUND", "找不到指定的 One Account mock endpoint。")
        except DomainError as error:
            return self._error(request, error)
        except Exception:
            return self._error(
                request,
                DomainError(500, "MOCK_SERVICE_ERROR", "Mock 一戶通服務暫時不可用。", retryable=True),
            )
