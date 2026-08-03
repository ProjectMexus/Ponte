import threading
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from frontend.server import create_http_server


class FrontendStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_http_server("127.0.0.1", 0, Path("frontend"))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_client_asset_is_served(self):
        with self.opener.open(self.base_url + "/mcp-client.js") as response:
            self.assertIn("MiddlewareClient", response.read().decode("utf-8"))

    def test_path_traversal_is_not_served(self):
        with self.assertRaises(Exception):
            self.opener.open(self.base_url + "/../docs/PonteArch.md")


if __name__ == "__main__":
    unittest.main()
