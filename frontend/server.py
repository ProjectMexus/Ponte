"""Small dependency-free static server for Ponte's frontend assets."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from typing import Any


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
