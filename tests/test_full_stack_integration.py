import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from frontend.server import create_http_server as create_frontend_http_server
from middleware.server import create_application, create_http_server
from mock_backends.server import create_http_server as create_backend_http_server


class FullStackIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.backend = create_backend_http_server(
            "127.0.0.1",
            0,
            Path(self.tempdir.name),
        )
        self.backend_thread = threading.Thread(
            target=self.backend.serve_forever,
            daemon=True,
        )
        self.backend_thread.start()

        self.middleware_app = create_application(
            f"http://127.0.0.1:{self.backend.server_port}",
            "PAT-DEMO-001",
            "Bearer mock-user-token",
        )
        self.middleware = create_http_server(
            "127.0.0.1",
            0,
            self.middleware_app,
        )
        self.middleware_thread = threading.Thread(
            target=self.middleware.serve_forever,
            daemon=True,
        )
        self.middleware_thread.start()

        self.frontend = create_frontend_http_server("127.0.0.1", 0, Path("frontend"))
        self.frontend_thread = threading.Thread(
            target=self.frontend.serve_forever,
            daemon=True,
        )
        self.frontend_thread.start()
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        for server, thread in (
            (self.frontend, self.frontend_thread),
            (self.middleware, self.middleware_thread),
            (self.backend, self.backend_thread),
        ):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.tempdir.cleanup()

    def get(self, path):
        with self.opener.open(
            f"http://127.0.0.1:{self.frontend.server_port}{path}"
        ) as response:
            return response.read().decode("utf-8")

    def get_middleware(self, path):
        with self.opener.open(
            f"http://127.0.0.1:{self.middleware.server_port}{path}"
        ) as response:
            return json.loads(response.read())

    def post_middleware(self, path, body):
        request = Request(
            f"http://127.0.0.1:{self.middleware.server_port}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.opener.open(request) as response:
            return json.loads(response.read())

    def test_frontend_to_mcp_to_backend_message_flow(self):
        html = self.get("/")
        client_js = self.get("/mcp-client.js")
        health = self.get_middleware("/api/health")
        response = self.post_middleware(
            "/api/interactions/message",
            {
                "session_id": "BROWSER-SMOKE-1",
                "message": "我想查詢醫療預約",
                "source": "text",
            },
        )

        self.assertIn("公共服務助手", html)
        self.assertIn("MiddlewareClient", client_js)
        self.assertTrue(health["backend_reachable"])
        self.assertEqual(response["task_state"], "selecting_service")
        self.assertEqual(
            [event["tool_name"] for event in response["tool_events"]],
            [
                "medical.get_my_appointments",
                "medical.list_appointment_services",
            ],
        )

        process = self.middleware_app.mcp_client.process
        self.assertIsNotNone(process)
        self.assertIsNone(process.poll())
        self.assertEqual(process.args[1:3], ["-m", "MCP"])


if __name__ == "__main__":
    unittest.main()
