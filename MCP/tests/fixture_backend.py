"""Small local HTTP fixture used by MCP connectivity tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from typing import Any


class _FixtureHandler(BaseHTTPRequestHandler):
    server: "_FixtureHTTPServer"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._handle()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self._handle()

    def _handle(self) -> None:
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b""
        try:
            body: Any = json.loads(raw_body.decode("utf-8")) if raw_body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {"_invalid_json": True}
        request = {
            "method": self.command,
            "path": parsed.path,
            "query": {key: values[-1] for key, values in parse_qs(parsed.query).items()},
            "headers": dict(self.headers.items()),
            "body": body,
        }
        self.server.requests.append(request)

        if self.server.malformed_once:
            self.server.malformed_once = False
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"not-json")
            return

        if (
            parsed.path == "/mock/medical/v1/registrations"
            and isinstance(body, dict)
            and body.get("slot_id") == "SLOT-CONFLICT"
        ):
            self._json_response(
                409,
                {
                    "error": {
                        "code": "SLOT_NOT_AVAILABLE",
                        "message": "所選時段已滿",
                        "retryable": False,
                    }
                },
            )
            return

        status = 201 if self.command == "POST" else 200
        payload = {"request_id": "REQ-FIXTURE-1", "data": {"ok": True, "path": parsed.path}}
        if parsed.path.endswith("/registrations"):
            payload["data"] = {"registration": {"registration_id": "REG-FIXTURE-1"}}
        self._json_response(status, payload)

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


class _FixtureHTTPServer(ThreadingHTTPServer):
    requests: list[dict[str, Any]]
    malformed_once: bool


class FixtureBackend:
    """Context manager for a local, request-recording HTTP backend."""

    def __init__(self) -> None:
        self.server = _FixtureHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        self.server.requests = []
        self.server.malformed_once = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FixtureBackend":
        self.thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self.server.requests

    def return_malformed_once(self) -> None:
        self.server.malformed_once = True
