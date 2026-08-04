"""Small dependency-free static server for Ponte's frontend assets."""

from __future__ import annotations

import argparse
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from typing import Any

from ponte_logging import log_event


class _StaticRequestHandler(SimpleHTTPRequestHandler):
    server_version = "PonteFrontend/1.0"

    def __init__(self, *args: Any, root: Path, **kwargs: Any) -> None:
        self.root = root
        super().__init__(*args, directory=str(root), **kwargs)

    def translate_path(self, path: str) -> str:
        relative = Path(unquote(urlsplit(path).path).lstrip("/"))
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            return str(self.root / "__ponte_missing_file__")
        return str(candidate)

    def handle_one_request(self) -> None:
        self._request_started_at = time.monotonic()
        self._request_log_code = None
        self._request_log_size = "-"
        self._response_bytes = None
        try:
            super().handle_one_request()
        finally:
            if self._request_log_code is not None:
                log_event(
                    "frontend",
                    "request_end",
                    method=getattr(self, "command", ""),
                    path=urlsplit(getattr(self, "path", "")).path,
                    status=self._request_log_code,
                    bytes=self._response_bytes if self._response_bytes is not None else self._request_log_size,
                    latency_ms=(time.monotonic() - self._request_started_at) * 1000,
                )

    def log_request(self, code: int | str, size: int | str = "-") -> None:
        self._request_log_code = code
        self._request_log_size = size

    def send_header(self, keyword: str, value: str) -> None:
        if keyword.lower() == "content-length":
            try:
                self._response_bytes = int(value)
            except (TypeError, ValueError):
                self._response_bytes = value
        super().send_header(keyword, value)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_http_server(host: str, port: int, root_dir: str | Path) -> ThreadingHTTPServer:
    root = Path(root_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"frontend root does not exist: {root}")

    def handler(*args: Any, **kwargs: Any) -> _StaticRequestHandler:
        return _StaticRequestHandler(*args, root=root, **kwargs)

    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Ponte frontend assets.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--root", default="frontend")
    args = parser.parse_args()
    server = create_http_server(args.host, args.port, args.root)
    print(f"Ponte frontend listening on http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
