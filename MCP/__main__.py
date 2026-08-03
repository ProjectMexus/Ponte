"""Command-line entry point for ``python -m MCP``."""

from __future__ import annotations

import sys

from .registry import build_registry
from .rest_adapter import RestAdapter
from .server import MCPServer


def main() -> None:
    server = MCPServer(build_registry(), RestAdapter.from_environment())
    server.run(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
