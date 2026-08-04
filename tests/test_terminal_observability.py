import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from frontend.server import create_http_server as create_frontend_http_server
from middleware.intent import KeywordIntentRecognizer
from middleware.server import create_application, create_http_server as create_middleware_http_server
from mock_backends.server import create_http_server as create_backend_http_server


class RecordingMcpClient:
    def __init__(self):
        self.closed = False

    def start(self):
        return None

    def call_tool(self, name, arguments):
        return {"request_id": "REQ-TEST", "data": {"tool": name, "arguments": arguments}}

    def close(self):
        self.closed = True


class TerminalObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.frontend = create_frontend_http_server("127.0.0.1", 0, Path("frontend"))
        self.backend = create_backend_http_server("127.0.0.1", 0, Path(self.tempdir.name))
        application = create_application(
            f"http://127.0.0.1:{self.backend.server_port}",
            "PAT-DEMO-001",
            "Bearer middleware-token",
            mcp_client=RecordingMcpClient(),
            intent_recognizer=KeywordIntentRecognizer(),
        )
        self.middleware = create_middleware_http_server("127.0.0.1", 0, application)
        self.servers = (self.frontend, self.middleware, self.backend)
        self.threads = tuple(
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in self.servers
        )
        for thread in self.threads:
            thread.start()

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
        for server in self.servers:
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.tempdir.cleanup()

    def request(self, server, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        request_body = None if body is None else json.dumps(body, ensure_ascii=False)
        connection.request(method, path, body=request_body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        connection.close()
        return status, raw

    def test_frontend_logs_safe_request_summary(self):
        with self.assertLogs("ponte", level="INFO") as captured:
            status, raw = self.request(
                self.frontend,
                "GET",
                "/?query_secret=PATIENT_SECRET_HTTP_VALUE",
            )

        self.assertEqual(status, 200)
        self.assertTrue(raw)
        output = "\n".join(captured.output)
        self.assertIn("[frontend] request_end", output)
        self.assertIn("method=GET", output)
        self.assertIn("path=/", output)
        self.assertIn("status=200", output)
        self.assertRegex(output, r"bytes=\d+")
        self.assertIn("latency_ms=", output)
        self.assertNotIn("PATIENT_SECRET_HTTP_VALUE", output)
        self.assertNotIn("Authorization", output)

    def test_frontend_error_does_not_log_query_values(self):
        with self.assertLogs("ponte", level="INFO") as captured:
            status, _ = self.request(
                self.frontend,
                "GET",
                "/missing?query_secret=PATIENT_SECRET_HTTP_VALUE",
            )

        self.assertEqual(status, 404)
        output = "\n".join(captured.output)
        self.assertIn("[frontend] request_end", output)
        self.assertIn("path=/missing", output)
        self.assertIn("status=404", output)
        self.assertNotIn("PATIENT_SECRET_HTTP_VALUE", output)

    def test_middleware_logs_start_and_end_without_request_values(self):
        with self.assertLogs("ponte", level="INFO") as captured:
            status, raw = self.request(
                self.middleware,
                "GET",
                "/api/mcp/tools?query_secret=PATIENT_SECRET_HTTP_VALUE",
                headers={"Authorization": "Bearer PATIENT_SECRET_HTTP_VALUE"},
            )

        self.assertEqual(status, 200)
        self.assertIn(b'"tools"', raw)
        output = "\n".join(captured.output)
        self.assertIn("[middleware] request_start", output)
        self.assertIn("[middleware] request_end", output)
        self.assertIn("method=GET", output)
        self.assertIn("path=/api/mcp/tools", output)
        self.assertIn("request_id=HTTP-MW-", output)
        self.assertIn("status=200", output)
        self.assertIn("latency_ms=", output)
        self.assertNotIn("PATIENT_SECRET_HTTP_VALUE", output)
        self.assertNotIn("Authorization", output)

    def test_backend_logs_start_and_end_without_request_values(self):
        with self.assertLogs("ponte", level="INFO") as captured:
            status, raw = self.request(
                self.backend,
                "GET",
                "/mock/medical/v1/departments?patient=PATIENT_SECRET_HTTP_VALUE",
                body={"body_secret": "PATIENT_SECRET_HTTP_VALUE"},
                headers={
                    "Authorization": "Bearer PATIENT_SECRET_HTTP_VALUE",
                    "X-Request-Id": "PATIENT_SECRET_HTTP_VALUE",
                },
            )

        self.assertEqual(status, 200)
        self.assertIn(b'"data"', raw)
        output = "\n".join(captured.output)
        self.assertIn("[backend] request_start", output)
        self.assertIn("[backend] request_end", output)
        self.assertIn("method=GET", output)
        self.assertIn("path=/mock/medical/v1/departments", output)
        self.assertIn("request_id=HTTP-BE-", output)
        self.assertIn("status=200", output)
        self.assertIn("bytes=", output)
        self.assertIn("latency_ms=", output)
        self.assertNotIn("PATIENT_SECRET_HTTP_VALUE", output)
        self.assertNotIn("Authorization", output)


if __name__ == "__main__":
    unittest.main()
