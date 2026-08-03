import unittest

from MCP.errors import InvalidToolArguments
from MCP.models import ContextRequirements, ToolContext


class ToolContextTests(unittest.TestCase):
    def test_builds_allowlisted_headers_for_medical_post(self):
        context = ToolContext.from_arguments({
            "context": {
                "authorization": "Bearer mock-user-token",
                "patient_id": "P-10001",
                "request_id": "REQ-1",
                "idempotency_key": "KEY-1",
                "accept_language": "zh-TW",
            },
            "input": {},
        })
        headers = context.to_headers(
            ContextRequirements(
                authorization=True,
                patient_id=True,
                idempotency_key=True,
                request_id=True,
                accept_language=True,
            ),
            method="POST",
        )
        self.assertEqual(headers["Authorization"], "Bearer mock-user-token")
        self.assertEqual(headers["X-Patient-Id"], "P-10001")
        self.assertEqual(headers["Idempotency-Key"], "KEY-1")
        self.assertEqual(headers["Accept-Language"], "zh-TW")
        self.assertNotIn("context", headers)

    def test_rejects_post_without_idempotency_key(self):
        context = ToolContext.from_arguments({"context": {}, "input": {}})
        with self.assertRaises(InvalidToolArguments):
            context.to_headers(
                ContextRequirements(idempotency_key=True), method="POST"
            )


if __name__ == "__main__":
    unittest.main()
