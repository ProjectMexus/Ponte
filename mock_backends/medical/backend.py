"""HTTP-shaped adapter for the medical domain service."""

from __future__ import annotations

from mock_backends.core.contracts import Clock
from mock_backends.core.errors import DomainError, error_payload
from mock_backends.core.http import BackendRequest, BackendResponse

from .contracts import required_patient
from .service import MedicalService


class MedicalBackend:
    prefix = "/mock/medical/v1"

    def __init__(self, service: MedicalService, clock: Clock | None = None) -> None:
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
            if request.method == "GET" and path == "/departments":
                return self.service.list_departments(request.query, request.request_id)
            if request.method == "GET" and path.startswith("/departments/") and path.endswith("/doctors"):
                department_id = path[len("/departments/"):-len("/doctors")].rstrip("/")
                return self.service.list_department_doctors(department_id, request.request_id)
            if request.method == "GET" and path == "/registration-slots":
                required_patient(request.headers)
                return self.service.search_registration_slots(request.query, request.request_id)
            if request.method == "POST" and path == "/registrations":
                patient_id = required_patient(request.headers)
                return self.service.create_registration(patient_id, request.body, request.headers, request.request_id, path)
            if request.method == "GET" and path == "/appointment-services":
                return self.service.list_appointment_services(request.query, request.request_id)
            if request.method == "GET" and path == "/appointment-slots":
                required_patient(request.headers)
                return self.service.search_appointment_slots(request.query, request.request_id)
            if request.method == "POST" and path == "/appointments":
                patient_id = required_patient(request.headers)
                return self.service.create_appointment(patient_id, request.body, request.headers, request.request_id, path)
            if request.method == "GET" and path == "/appointments":
                return self.service.list_appointments(required_patient(request.headers), request.query, request.request_id)
            if request.method == "GET" and path.startswith("/appointments/"):
                return self.service.get_appointment(required_patient(request.headers), path[len("/appointments/"):], request.request_id)
            if request.method == "GET" and path.startswith("/tasks/"):
                return self.service.get_task(required_patient(request.headers), path[len("/tasks/"):], request.request_id)
            raise DomainError(404, "NOT_FOUND", "找不到指定的 medical mock endpoint。")
        except DomainError as error:
            return self._error(request, error)
        except Exception:
            return self._error(request, DomainError(500, "MOCK_SERVICE_ERROR", "Mock 醫療服務暫時不可用。", retryable=True))
