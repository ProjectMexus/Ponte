"""HTTP adapter for the elderly cultural activities API."""

from __future__ import annotations

from mock_backends.core.contracts import Clock
from mock_backends.core.errors import DomainError, error_payload
from mock_backends.core.http import BackendRequest, BackendResponse

from .activity_service import ElderlyActivitiesService
from .contracts import required_user


class ElderlyActivitiesBackend:
    prefix = "/mock/elderly-activities/v1"

    def __init__(self, service: ElderlyActivitiesService, clock: Clock | None = None) -> None:
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
            if request.method == "GET" and path == "/activities":
                return self.service.search(request.query, request.request_id)
            if request.method == "GET" and path.startswith("/activities/") and path.endswith("/registration-form"):
                required_user(request.headers)
                return self.service.get_registration_form(path[len("/activities/"):-len("/registration-form")].rstrip("/"), request.request_id)
            if request.method == "GET" and path.startswith("/activities/"):
                return self.service.get_activity(path[len("/activities/"):], request.request_id)
            if request.method == "POST" and path == "/registrations":
                return self.service.create_registration(required_user(request.headers), request.body, request.headers, request.request_id, path)
            if request.method == "GET" and path.startswith("/registrations/"):
                return self.service.get_registration(required_user(request.headers), path[len("/registrations/"):], request.request_id)
            if request.method == "POST" and path == "/phone-registration-assists":
                return self.service.create_phone_assistance(required_user(request.headers), request.body, request.headers, request.request_id, path)
            if request.method == "GET" and path.startswith("/phone-registration-assists/"):
                return self.service.get_phone_assistance(required_user(request.headers), path[len("/phone-registration-assists/"):], request.request_id)
            raise DomainError(404, "NOT_FOUND", "找不到指定的 elderly activities mock endpoint。")
        except DomainError as error:
            return self._error(request, error)
        except Exception:
            return self._error(request, DomainError(500, "MOCK_SERVICE_ERROR", "Mock 長者活動服務暫時不可用。", retryable=True))
