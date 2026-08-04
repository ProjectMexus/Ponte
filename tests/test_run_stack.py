import os
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_stack import build_commands, frontend_url, middleware_environment


class RunStackTests(unittest.TestCase):
    def test_build_commands_uses_explicit_ports_and_data_directory(self):
        data_dir = Path("/tmp/ponte-run-stack")
        commands = build_commands(
            sys.executable,
            backend_port=18080,
            middleware_port=18090,
            frontend_port=15173,
            data_dir=data_dir,
        )

        self.assertEqual(
            commands.backend,
            [
                sys.executable,
                "-m",
                "mock_backends.server",
                "--host",
                "127.0.0.1",
                "--port",
                "18080",
                "--data-dir",
                str(data_dir),
            ],
        )
        self.assertEqual(
            commands.middleware,
            [
                sys.executable,
                "-m",
                "middleware.server",
                "--host",
                "127.0.0.1",
                "--port",
                "18090",
            ],
        )
        self.assertEqual(
            commands.frontend,
            [
                sys.executable,
                "-m",
                "frontend.server",
                "--host",
                "127.0.0.1",
                "--port",
                "15173",
            ],
        )

    def test_middleware_environment_contains_backend_url(self):
        environment = middleware_environment(
            "http://127.0.0.1:18080",
            base_environment={"EXAMPLE": "1"},
        )

        self.assertEqual(environment["PONTE_BACKEND_URL"], "http://127.0.0.1:18080")
        self.assertEqual(environment["EXAMPLE"], "1")

    def test_frontend_url_includes_middleware_override(self):
        self.assertEqual(
            frontend_url(15173, 18090),
            "http://127.0.0.1:15173/?middleware=http://127.0.0.1:18090",
        )


if __name__ == "__main__":
    unittest.main()
