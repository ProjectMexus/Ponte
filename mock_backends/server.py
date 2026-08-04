"""Single-process HTTP entrypoint for the three mock domains."""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Type
from urllib.parse import parse_qs, urlsplit

from mock_backends.core.clock import AsiaMacauClock
from mock_backends.core.contracts import Clock
from mock_backends.core.errors import DomainError, error_payload
from mock_backends.core.http import BackendRequest, BackendResponse
from mock_backends.core.idempotency import RepositoryIdempotencyStore
from mock_backends.core.ids import TextFileIdGenerator
from mock_backends.core.persistence import JsonLinesTextRepository
from mock_backends.medical.backend import MedicalBackend
from mock_backends.medical.service import MedicalService
from mock_backends.one_account.backend import OneAccountBackend
from mock_backends.one_account.service import OneAccountService
from mock_backends.router import MockRouter
from mock_backends.social_welfare.activity_backend import ElderlyActivitiesBackend
from mock_backends.social_welfare.activity_service import ElderlyActivitiesService
from mock_backends.social_welfare.backend import SocialWelfareBackend
from mock_backends.social_welfare.service import SocialWelfareService
from ponte_logging import log_event


_MIDDLEWARE_REQUEST_ID = re.compile(r"^REQ-MW-[0-9A-F]{12}$")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "database"


def create_application(data_dir: str | Path, clock: Clock | None = None) -> MockRouter:
    root = Path(data_dir)
    active_clock = clock or AsiaMacauClock()
    ids = TextFileIdGenerator(JsonLinesTextRepository(root / "id_sequences.txt"))

    one_root = root / "one_account"
    one_service = OneAccountService(
        clock=active_clock,
        ids=ids,
        application_repository=JsonLinesTextRepository(one_root / "applications.txt"),
        ticket_repository=JsonLinesTextRepository(one_root / "queue_tickets.txt"),
        idempotency=RepositoryIdempotencyStore(JsonLinesTextRepository(one_root / "idempotency.txt")),
    )

    medical_root = root / "medical"
    medical_service = MedicalService(
        clock=active_clock,
        ids=ids,
        appointment_repository=JsonLinesTextRepository(medical_root / "appointments.txt"),
        task_repository=JsonLinesTextRepository(medical_root / "tasks.txt"),
        idempotency=RepositoryIdempotencyStore(JsonLinesTextRepository(medical_root / "idempotency.txt")),
    )

    welfare_root = root / "social_welfare"
    welfare_service = SocialWelfareService(
        clock=active_clock,
        ids=ids,
        referral_repository=JsonLinesTextRepository(welfare_root / "referrals.txt"),
        idempotency=RepositoryIdempotencyStore(JsonLinesTextRepository(welfare_root / "idempotency.txt")),
    )
    activity_service = ElderlyActivitiesService(
        clock=active_clock,
        ids=ids,
        registration_repository=JsonLinesTextRepository(welfare_root / "activity_registrations.txt"),
        phone_assistance_repository=JsonLinesTextRepository(welfare_root / "phone_registration_assists.txt"),
        idempotency=RepositoryIdempotencyStore(JsonLinesTextRepository(welfare_root / "activity_idempotency.txt")),
    )

    router = MockRouter(active_clock)
    one_backend = OneAccountBackend(one_service, active_clock)
    router.mount("/mock/one-account", one_backend)
    router.mount("/mock/elderly-activities/v1", ElderlyActivitiesBackend(activity_service, active_clock))
    router.mount("/mock/medical/v1", MedicalBackend(medical_service, active_clock))
    router.mount("/mock/social-welfare", SocialWelfareBackend(welfare_service, active_clock))
    return router


def _header(headers: dict[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def make_request_handler(router: MockRouter) -> Type[BaseHTTPRequestHandler]:
    class MockRequestHandler(BaseHTTPRequestHandler):
        server_version = "PonteMock/1.0"

        def _request_id(self, headers: dict[str, str]) -> str:
            return _header(headers, "X-Request-Id") or f"REQ-{uuid.uuid4().hex[:12].upper()}"

        def _send(self, response: BackendResponse) -> None:
            self._response_status = response.status
            try:
                raw = json.dumps(response.body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            except Exception:
                self._response_status = 500
                raise
            self._response_bytes = len(raw)
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _error_response(self, request_id: str, error: DomainError) -> None:
            self._send(BackendResponse(error.status, error_payload(request_id, error, router.clock)))

        def _body(self, request_id: str) -> dict[str, Any] | None:
            length_value = self.headers.get("Content-Length")
            if not length_value:
                return None
            try:
                length = int(length_value)
            except ValueError as exc:
                raise DomainError(400, "INVALID_CONTENT_LENGTH", "Content-Length 不正確。") from exc
            if length < 0:
                raise DomainError(400, "INVALID_CONTENT_LENGTH", "Content-Length 不可以是負數。")
            raw = self.rfile.read(length)
            if not raw:
                return None
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DomainError(400, "INVALID_JSON", "request body 不是有效 JSON。") from exc
            if value is None:
                return None
            if not isinstance(value, dict):
                raise DomainError(400, "INVALID_REQUEST", "request body 必須是 JSON object。")
            return value

        def _handle(self) -> None:
            headers = {key: value for key, value in self.headers.items()}
            request_id = self._request_id(headers)
            log_request_id = (
                request_id
                if _MIDDLEWARE_REQUEST_ID.fullmatch(request_id)
                else f"HTTP-BE-{uuid.uuid4().hex[:12].upper()}"
            )
            parsed = urlsplit(self.path)
            path = parsed.path
            started_at = time.monotonic()
            self._response_status = 500
            self._response_bytes = 0
            log_event(
                "backend",
                "request_start",
                method=self.command,
                path=path,
                request_id=log_request_id,
            )
            try:
                body = self._body(request_id)
                request = BackendRequest(
                    method=self.command,
                    path=parsed.path,
                    query=parse_qs(parsed.query, keep_blank_values=True),
                    headers=headers,
                    body=body,
                    request_id=request_id,
                )
                self._send(router.dispatch(request))
            except DomainError as error:
                self._error_response(request_id, error)
            except Exception:
                self._error_response(request_id, DomainError(500, "MOCK_SERVICE_ERROR", "Mock service 暫時不可用。", retryable=True))
            finally:
                log_event(
                    "backend",
                    "request_end",
                    method=self.command,
                    path=path,
                    request_id=log_request_id,
                    status=self._response_status,
                    latency_ms=(time.monotonic() - started_at) * 1000,
                    bytes=self._response_bytes,
                )

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def do_PUT(self) -> None:
            self._handle()

        def do_DELETE(self) -> None:
            self._handle()

        def log_message(self, format: str, *args: Any) -> None:
            return

    return MockRequestHandler


def create_http_server(host: str, port: int, data_dir: str | Path, clock: Clock | None = None) -> ThreadingHTTPServer:
    router = create_application(data_dir, clock=clock)
    return ThreadingHTTPServer((host, port), make_request_handler(router))


def run_server(host: str, port: int, data_dir: str | Path) -> None:
    server = create_http_server(host, port, data_dir)
    print(f"Ponte mock backends listening on http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Ponte's One Account, Medical and Social Welfare mock backends.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    args = parser.parse_args()
    run_server(args.host, args.port, args.data_dir)


if __name__ == "__main__":
    main()
