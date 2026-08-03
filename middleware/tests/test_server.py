import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from middleware.server import create_application, create_http_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = create_application("http://backend.test", "PAT-DEMO-001", "Bearer mock-user-token")
        cls.server = create_http_server("127.0.0.1", 0, cls.application)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            return response.status, json.loads(response.read())

    def test_tools_endpoint_returns_registry(self):
        status, payload = self.request("GET", "/api/mcp/tools")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["tools"]), 21)

    def test_malformed_json_is_safe_client_error(self):
        request = Request(self.base_url + "/api/interactions/message", data=b"{", method="POST", headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 400)
        error_body = json.loads(raised.exception.read())
        self.assertNotIn("traceback", json.dumps(error_body).lower())


if __name__ == "__main__":
    unittest.main()
