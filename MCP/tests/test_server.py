import io
import json
import unittest

from MCP.registry import build_registry
from MCP.server import MCPServer


class NoopAdapter:
    def invoke(self, definition, arguments):
        return {"request_id": "REQ-1", "data": {"ok": True, "tool": definition.name}}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer(build_registry(), NoopAdapter())

    def test_initialize_returns_capabilities(self):
        result = self.server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1"}},
        })
        self.assertEqual(result["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", result["result"]["capabilities"])

    def test_tools_list_returns_21_tools(self):
        result = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(result["result"]["tools"]), 21)

    def test_tools_call_returns_structured_content(self):
        result = self.server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "medical.list_departments", "arguments": {"context": {}, "input": {}}},
        })
        self.assertFalse(result["result"].get("isError", False))
        self.assertEqual(result["result"]["structuredContent"]["data"]["ok"], True)

    def test_initialized_notification_has_no_response(self):
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))


if __name__ == "__main__":
    unittest.main()
