"""HTTP-shaped adapter for the social welfare domain service."""

from __future__ import annotations

from mock_backends.core.contracts import Clock
from mock_backends.core.errors import DomainError, error_payload
from mock_backends.core.http import BackendRequest, BackendResponse

from .contracts import required_user
from .service import SocialWelfareService


class SocialWelfareBackend:
    prefix = "/mock/social-welfare"

    def __init__(self, service: SocialWelfareService, clock: Clock | None = None) -> None:
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
            if request.method == "GET" and path == "/services":
                return self.service.search_services(request.query, request.request_id)
            if request.method == "POST" and path == "/referrals":
                return self.service.create_referral(required_user(request.headers), request.body, request.headers, request.request_id, path)
            if request.method == "GET" and path.startswith("/referrals/") and not path.endswith("/assign"):
                return self.service.get_referral(required_user(request.headers), path[len("/referrals/"):], request.request_id)
            if request.method == "POST" and path.startswith("/referrals/") and path.endswith("/assign"):
                referral_id = path[len("/referrals/"):-len("/assign")].rstrip("/")
                return self.service.assign_referral(required_user(request.headers), referral_id, request.body, request.headers, request.request_id, path)
            raise DomainError(404, "NOT_FOUND", "找不到指定的 social welfare mock endpoint。")
        except DomainError as error:
            return self._error(request, error)
        except Exception:
            return self._error(request, DomainError(500, "MOCK_SERVICE_ERROR", "Mock 社福服務暫時不可用。", retryable=True))
