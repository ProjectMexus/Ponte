import unittest

from MCP.registry import build_registry


EXPECTED_ROUTES = {
    "one_account.submit_pension_application": ("POST", "/mock/one-account/pension/applications"),
    "one_account.get_cash_sharing_plan": ("GET", "/mock/one-account/cash-sharing-plan"),
    "one_account.book_government_service_center_queue": (
        "POST",
        "/mock/one-account/queue-tickets/government-service-center",
    ),
    "one_account.book_identification_services_bureau_queue": (
        "POST",
        "/mock/one-account/queue-tickets/identification-services-bureau",
    ),
    "one_account.list_my_queue_tickets": ("GET", "/mock/one-account/my/queue-tickets"),
    "one_account.search_elderly_activities": (
        "GET",
        "/mock/elderly-activities/v1/activities",
    ),
    "one_account.get_elderly_activity": (
        "GET",
        "/mock/elderly-activities/v1/activities/{activityId}",
    ),
    "one_account.get_activity_registration_form": (
        "GET",
        "/mock/elderly-activities/v1/activities/{activityId}/registration-form",
    ),
    "one_account.submit_activity_registration": (
        "POST",
        "/mock/elderly-activities/v1/registrations",
    ),
    "one_account.start_phone_registration_assistance": (
        "POST",
        "/mock/elderly-activities/v1/phone-registration-assists",
    ),
    "one_account.get_activity_registration_status": (
        "GET",
        "/mock/elderly-activities/v1/registrations/{registrationId}",
    ),
    "medical.list_departments": ("GET", "/mock/medical/v1/departments"),
    "medical.list_department_doctors": (
        "GET",
        "/mock/medical/v1/departments/{departmentId}/doctors",
    ),
    "medical.search_registration_slots": (
        "GET",
        "/mock/medical/v1/registration-slots",
    ),
    "medical.create_registration": ("POST", "/mock/medical/v1/registrations"),
    "medical.list_appointment_services": (
        "GET",
        "/mock/medical/v1/appointment-services",
    ),
    "medical.search_appointment_slots": (
        "GET",
        "/mock/medical/v1/appointment-slots",
    ),
    "medical.create_appointment": ("POST", "/mock/medical/v1/appointments"),
    "medical.get_my_appointments": ("GET", "/mock/medical/v1/appointments"),
    "medical.get_appointment": (
        "GET",
        "/mock/medical/v1/appointments/{appointmentId}",
    ),
    "medical.get_task_status": ("GET", "/mock/medical/v1/tasks/{taskId}"),
}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()

    def test_catalog_has_exactly_21_documented_tools(self):
        self.assertEqual(len(self.registry.names()), 21)
        self.assertEqual(set(self.registry.names()), set(EXPECTED_ROUTES))
        self.assertNotIn("social_welfare.search_services", self.registry.names())
        self.assertNotIn("notification.send_reminder", self.registry.names())

    def test_catalog_preserves_documented_http_routes(self):
        for name, (method, path) in EXPECTED_ROUTES.items():
            definition = self.registry.get(name)
            self.assertEqual(definition.method, method, name)
            self.assertEqual(definition.path_template, path, name)

    def test_medical_create_registration_is_post_and_requires_context(self):
        definition = self.registry.get("medical.create_registration")
        self.assertEqual(definition.method, "POST")
        self.assertEqual(definition.path_template, "/mock/medical/v1/registrations")
        self.assertTrue(definition.context_requirements.authorization)
        self.assertTrue(definition.context_requirements.patient_id)
        self.assertTrue(definition.context_requirements.idempotency_key)

    def test_activity_status_has_explicit_route_selector(self):
        definition = self.registry.get("one_account.get_activity_registration_status")
        self.assertEqual(definition.method, "GET")
        self.assertEqual(set(definition.route_variants), {"registration", "phone_assistance"})
        self.assertEqual(
            definition.route_variants["phone_assistance"],
            "/mock/elderly-activities/v1/phone-registration-assists/{assistanceId}",
        )

    def test_tools_list_has_input_schema(self):
        for tool in self.registry.list_mcp_tools():
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertEqual(set(tool["inputSchema"]["required"]), {"context", "input"})
            self.assertEqual(
                set(tool["inputSchema"]["properties"]), {"context", "input"}
            )

    def test_input_schema_keeps_documented_query_and_body_fields(self):
        search = self.registry.get("one_account.search_elderly_activities")
        self.assertEqual(
            set(search.input_schema["properties"]["input"]["properties"]),
            {
                "keyword",
                "organization_id",
                "activity_type",
                "category",
                "date_from",
                "date_to",
                "district",
                "participant_age",
                "registration_method",
                "accessibility",
                "available_only",
                "sort",
                "page",
                "page_size",
            },
        )

        medical = self.registry.get("medical.create_registration")
        self.assertEqual(
            set(medical.input_schema["properties"]["input"]["required"]),
            {"patient_id", "department_id", "slot_id", "consent"},
        )
        self.assertEqual(medical.body_mode, "json")

    def test_context_schema_is_allowlisted(self):
        definition = self.registry.get("medical.list_departments")
        context_schema = definition.input_schema["properties"]["context"]
        self.assertFalse(context_schema["additionalProperties"])
        self.assertEqual(
            set(context_schema["properties"]),
            {
                "mock_user_id",
                "patient_id",
                "authorization",
                "accept_language",
                "request_id",
                "idempotency_key",
            },
        )


if __name__ == "__main__":
    unittest.main()
