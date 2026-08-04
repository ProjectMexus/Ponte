import unittest

from MCP.registry import build_registry
from middleware.contracts import ToolCall
from middleware.diagnostics import (
    DiagnosticCommand,
    DiagnosticCommandError,
    build_diagnostic_call,
    describe_diagnostic_command,
    diagnostic_requires_confirmation,
)


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()

    def test_parse_read_command_with_json_input(self):
        command = DiagnosticCommand.parse(
            'mcp one_account.get_cash_sharing_plan {"year":2026}'
        )
        self.assertEqual(command.tool_name, "one_account.get_cash_sharing_plan")
        self.assertEqual(command.input_data, {"year": 2026})

    def test_parse_missing_json_as_empty_object(self):
        command = DiagnosticCommand.parse("mcp medical.list_departments")
        self.assertEqual(command.input_data, {})

    def test_non_command_returns_none(self):
        self.assertIsNone(DiagnosticCommand.parse("我想查詢醫療預約"))

    def test_malformed_command_has_safe_error(self):
        with self.assertRaises(DiagnosticCommandError) as raised:
            DiagnosticCommand.parse("mcp medical.list_departments {")
        self.assertEqual(raised.exception.code, "INVALID_DIAGNOSTIC_COMMAND")

    def test_non_object_json_has_safe_error(self):
        with self.assertRaises(DiagnosticCommandError) as raised:
            DiagnosticCommand.parse("mcp medical.list_departments []")
        self.assertEqual(raised.exception.code, "INVALID_DIAGNOSTIC_COMMAND")

    def test_missing_tool_name_has_safe_error(self):
        with self.assertRaises(DiagnosticCommandError) as raised:
            DiagnosticCommand.parse("mcp")
        self.assertEqual(raised.exception.code, "INVALID_DIAGNOSTIC_COMMAND")

    def test_descriptor_resolves_path_and_risk(self):
        descriptor = describe_diagnostic_command(
            self.registry,
            DiagnosticCommand("medical.get_appointment", {"appointment_id": "APT-1"}),
        )
        self.assertEqual(descriptor["tool_name"], "medical.get_appointment")
        self.assertEqual(descriptor["http_method"], "GET")
        self.assertEqual(descriptor["path"], "/mock/medical/v1/appointments/APT-1")
        self.assertEqual(descriptor["risk_level"], "R0")

    def test_unknown_tool_has_safe_error(self):
        with self.assertRaises(DiagnosticCommandError) as raised:
            describe_diagnostic_command(
                self.registry,
                DiagnosticCommand("unknown.tool", {}),
            )
        self.assertEqual(raised.exception.code, "UNKNOWN_DIAGNOSTIC_TOOL")

    def test_post_requires_confirmation(self):
        command = DiagnosticCommand(
            "one_account.book_government_service_center_queue",
            {
                "service_type": "general",
                "requested_date": "2026-08-20",
                "confirmation": {"confirmation_id": "demo"},
            },
        )
        self.assertTrue(diagnostic_requires_confirmation(self.registry, command))

    def test_get_does_not_require_confirmation(self):
        command = DiagnosticCommand("medical.list_departments", {})
        self.assertFalse(diagnostic_requires_confirmation(self.registry, command))

    def test_build_call_uses_only_controlled_envelope_and_copies_input(self):
        command = DiagnosticCommand(
            "medical.list_departments",
            {"keyword": "心臟", "nested": {"value": 1}},
        )
        call = build_diagnostic_call(
            command,
            {"authorization": "Bearer mock-user-token"},
            "diagnostic_medical_list_departments",
        )

        self.assertIsInstance(call, ToolCall)
        self.assertEqual(call.name, command.tool_name)
        self.assertEqual(call.step_id, "diagnostic_medical_list_departments")
        self.assertEqual(
            call.arguments,
            {
                "context": {"authorization": "Bearer mock-user-token"},
                "input": {"keyword": "心臟", "nested": {"value": 1}},
            },
        )
        self.assertIsNot(call.arguments["input"], command.input_data)
        self.assertIsNot(call.arguments["input"]["nested"], command.input_data["nested"])


if __name__ == "__main__":
    unittest.main()
