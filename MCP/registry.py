"""Fixed tool catalog for the documented Ponte mock APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import ContextRequirements


CONTEXT_PROPERTIES: dict[str, dict[str, str]] = {
    "mock_user_id": {"type": "string", "description": "Maps to X-Mock-User-Id."},
    "patient_id": {"type": "string", "description": "Maps to X-Patient-Id."},
    "authorization": {"type": "string", "description": "Mock Authorization header."},
    "accept_language": {"type": "string", "enum": ["zh-TW", "en-US"]},
    "request_id": {"type": "string", "description": "Maps to X-Request-Id."},
    "idempotency_key": {"type": "string", "description": "Maps to Idempotency-Key."},
}


def _object_schema(
    properties: Mapping[str, Any],
    *,
    required: tuple[str, ...] = (),
    additional_properties: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": additional_properties,
    }
    if required:
        result["required"] = list(required)
    return result


def _context_schema() -> dict[str, Any]:
    return _object_schema(CONTEXT_PROPERTIES)


def _envelope_schema(
    input_properties: Mapping[str, Any],
    *,
    input_required: tuple[str, ...] = (),
    input_additional_properties: bool = True,
) -> dict[str, Any]:
    return _object_schema(
        {
            "context": _context_schema(),
            "input": _object_schema(
                input_properties,
                required=input_required,
                additional_properties=input_additional_properties,
            ),
        },
        required=("context", "input"),
    )


def _string(description: str = "") -> dict[str, Any]:
    value: dict[str, Any] = {"type": "string"}
    if description:
        value["description"] = description
    return value


def _integer(description: str = "") -> dict[str, Any]:
    value: dict[str, Any] = {"type": "integer"}
    if description:
        value["description"] = description
    return value


def _boolean(description: str = "") -> dict[str, Any]:
    value: dict[str, Any] = {"type": "boolean"}
    if description:
        value["description"] = description
    return value


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    method: str
    path_template: str
    input_schema: dict[str, Any]
    context_requirements: ContextRequirements = field(default_factory=ContextRequirements)
    risk_level: str = "R0"
    query_fields: tuple[str, ...] = ()
    body_mode: str = "none"
    path_params: Mapping[str, str] = field(default_factory=dict)
    route_variants: Mapping[str, str] = field(default_factory=dict)
    route_selector: str | None = None

    def path_for(self, input_data: Mapping[str, Any]) -> str:
        template = self.path_template
        if self.route_selector:
            selector = input_data.get(self.route_selector)
            if selector not in self.route_variants:
                raise ValueError(f"Unsupported route selector: {self.route_selector}")
            template = self.route_variants[selector]
        for placeholder, input_key in self.path_params.items():
            if "{" + placeholder + "}" not in template:
                continue
            value = input_data.get(input_key)
            if value is None:
                raise ValueError(f"Missing path field: {input_key}")
            template = template.replace("{" + placeholder + "}", str(value))
        return template

    def to_mcp_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "_meta": {
                "ponte": {
                    "risk_level": self.risk_level,
                    "http_method": self.method,
                    "path_template": self.path_template,
                }
            },
        }


class ToolRegistry:
    def __init__(self, definitions: tuple[ToolDefinition, ...]):
        self._definitions = {definition.name: definition for definition in definitions}

    def get(self, name: str) -> ToolDefinition:
        return self._definitions[name]

    def names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def list_mcp_tools(self) -> list[dict[str, Any]]:
        return [definition.to_mcp_tool() for definition in self._definitions.values()]


def _one_account_context(*, post: bool = False) -> ContextRequirements:
    return ContextRequirements(mock_user_id=True, idempotency_key=post, request_id=False)


def _activity_context(*, post: bool = False) -> ContextRequirements:
    return ContextRequirements(mock_user_id=post, idempotency_key=post)


def _medical_context(*, patient: bool = False, post: bool = False) -> ContextRequirements:
    return ContextRequirements(
        patient_id=patient,
        authorization=True,
        idempotency_key=post,
        accept_language=True,
    )


def build_registry() -> ToolRegistry:
    """Return the fixed catalog derived from the three docs/api contracts."""

    activity_search_properties = {
        "keyword": _string(),
        "organization_id": _string(),
        "activity_type": {"type": "string", "description": "Comma-separated values."},
        "category": {"type": "string", "description": "Comma-separated values."},
        "date_from": _string("YYYY-MM-DD"),
        "date_to": _string("YYYY-MM-DD"),
        "district": _string(),
        "participant_age": _integer(),
        "registration_method": {"type": "string", "enum": ["form", "phone"]},
        "accessibility": {"type": "string", "description": "Comma-separated values."},
        "available_only": _boolean(),
        "sort": {"type": "string", "enum": ["start_at_asc", "registration_deadline_asc"]},
        "page": _integer(),
        "page_size": _integer(),
    }

    definitions = (
        ToolDefinition(
            "one_account.submit_pension_application",
            "提交養老金申請 mock 資料。",
            "POST",
            "/mock/one-account/pension/applications",
            _envelope_schema(
                {"applicant": {"type": "object"}, "payment_account": {"type": "object"}, "documents": {"type": "array"}, "consents": {"type": "object"}, "confirmation": {"type": "object"}},
                input_required=("applicant", "payment_account", "documents", "consents", "confirmation"),
            ),
            _one_account_context(post=True),
            "R2",
            body_mode="json",
        ),
        ToolDefinition(
            "one_account.get_cash_sharing_plan",
            "查詢指定年度的現金分享計劃 mock 資料。",
            "GET",
            "/mock/one-account/cash-sharing-plan",
            _envelope_schema({"year": _integer(), "include_history": _boolean()}),
            _one_account_context(),
            query_fields=("year", "include_history"),
        ),
        ToolDefinition(
            "one_account.book_government_service_center_queue",
            "預約政府綜合服務中心 mock 籌號。",
            "POST",
            "/mock/one-account/queue-tickets/government-service-center",
            _envelope_schema({"service_type": _string(), "requested_date": _string(), "confirmation": {"type": "object"}}, input_required=("service_type", "requested_date", "confirmation")),
            _one_account_context(post=True),
            "R1",
            body_mode="json",
        ),
        ToolDefinition(
            "one_account.book_identification_services_bureau_queue",
            "預約身份證明局 mock 籌號。",
            "POST",
            "/mock/one-account/queue-tickets/identification-services-bureau",
            _envelope_schema({"service_type": _string(), "requested_date": _string(), "confirmation": {"type": "object"}}, input_required=("service_type", "requested_date", "confirmation")),
            _one_account_context(post=True),
            "R1",
            body_mode="json",
        ),
        ToolDefinition(
            "one_account.list_my_queue_tickets",
            "查詢目前 mock user 的籌號。",
            "GET",
            "/mock/one-account/my/queue-tickets",
            _envelope_schema({"status": _string(), "service_category": _string(), "requested_date": _string()}),
            _one_account_context(),
            query_fields=("status", "service_category", "requested_date"),
        ),
        ToolDefinition(
            "one_account.search_elderly_activities",
            "跨機構搜尋長者文娛活動。",
            "GET",
            "/mock/elderly-activities/v1/activities",
            _envelope_schema(activity_search_properties),
            _activity_context(),
            query_fields=tuple(activity_search_properties),
        ),
        ToolDefinition(
            "one_account.get_elderly_activity",
            "查詢單一長者文娛活動詳情。",
            "GET",
            "/mock/elderly-activities/v1/activities/{activityId}",
            _envelope_schema({"activity_id": _string()}),
            _activity_context(),
            path_params={"activityId": "activity_id"},
        ),
        ToolDefinition(
            "one_account.get_activity_registration_form",
            "取得填表活動的報名 schema。",
            "GET",
            "/mock/elderly-activities/v1/activities/{activityId}/registration-form",
            _envelope_schema({"activity_id": _string()}),
            _activity_context(),
            path_params={"activityId": "activity_id"},
        ),
        ToolDefinition(
            "one_account.submit_activity_registration",
            "提交長者文娛活動填表報名。",
            "POST",
            "/mock/elderly-activities/v1/registrations",
            _envelope_schema({"activity_id": _string(), "form_id": _string(), "participant": {"type": "object"}, "consents": {"type": "object"}, "confirmation": {"type": "object"}}, input_required=("activity_id", "form_id", "participant", "consents", "confirmation")),
            _activity_context(post=True),
            "R2",
            body_mode="json",
        ),
        ToolDefinition(
            "one_account.start_phone_registration_assistance",
            "建立電話報名協助任務，不代表已完成正式報名。",
            "POST",
            "/mock/elderly-activities/v1/phone-registration-assists",
            _envelope_schema({"activity_id": _string(), "participant": {"type": "object"}, "confirmation": {"type": "object"}}, input_required=("activity_id", "participant", "confirmation")),
            _activity_context(post=True),
            "R2",
            body_mode="json",
        ),
        ToolDefinition(
            "one_account.get_activity_registration_status",
            "查詢填表報名或電話協助任務狀態。",
            "GET",
            "/mock/elderly-activities/v1/registrations/{registrationId}",
            _envelope_schema({"resource_type": {"type": "string", "enum": ["registration", "phone_assistance"]}, "registration_id": _string(), "assistance_id": _string()}, input_required=("resource_type",)),
            _activity_context(),
            path_params={"registrationId": "registration_id", "assistanceId": "assistance_id"},
            route_variants={"registration": "/mock/elderly-activities/v1/registrations/{registrationId}", "phone_assistance": "/mock/elderly-activities/v1/phone-registration-assists/{assistanceId}"},
            route_selector="resource_type",
        ),
        ToolDefinition(
            "medical.list_departments",
            "查詢可網上辦理的醫療科室。",
            "GET",
            "/mock/medical/v1/departments",
            _envelope_schema({"location_id": _string(), "keyword": _string(), "active_only": _boolean()}),
            _medical_context(),
            query_fields=("location_id", "keyword", "active_only"),
        ),
        ToolDefinition(
            "medical.list_department_doctors",
            "查詢指定科室的醫生。",
            "GET",
            "/mock/medical/v1/departments/{departmentId}/doctors",
            _envelope_schema({"department_id": _string()}, input_required=("department_id",)),
            _medical_context(),
            path_params={"departmentId": "department_id"},
        ),
        ToolDefinition(
            "medical.search_registration_slots",
            "搜尋門診掛號可用時段。",
            "GET",
            "/mock/medical/v1/registration-slots",
            _envelope_schema({"department_id": _string(), "date": _string(), "doctor_id": _string(), "session": {"type": "string", "enum": ["morning", "afternoon"]}, "location_id": _string()}, input_required=("department_id", "date")),
            _medical_context(patient=True),
            query_fields=("department_id", "date", "doctor_id", "session", "location_id"),
        ),
        ToolDefinition(
            "medical.create_registration",
            "建立門診掛號。",
            "POST",
            "/mock/medical/v1/registrations",
            _envelope_schema({"patient_id": _string(), "department_id": _string(), "doctor_id": _string(), "slot_id": _string(), "visit_reason": _string(), "notes": _string(), "consent": _boolean()}, input_required=("patient_id", "department_id", "slot_id", "consent")),
            _medical_context(patient=True, post=True),
            "R2",
            body_mode="json",
        ),
        ToolDefinition(
            "medical.list_appointment_services",
            "查詢可預約的檢查／治療服務。",
            "GET",
            "/mock/medical/v1/appointment-services",
            _envelope_schema({"department_id": _string(), "service_type": _string(), "keyword": _string(), "active_only": _boolean(), "available_only": _boolean()}),
            _medical_context(),
            query_fields=("department_id", "service_type", "keyword", "active_only", "available_only"),
        ),
        ToolDefinition(
            "medical.search_appointment_slots",
            "搜尋檢查／治療可預約時段。",
            "GET",
            "/mock/medical/v1/appointment-slots",
            _envelope_schema({"service_id": _string(), "date_from": _string(), "date_to": _string(), "doctor_id": _string(), "location_id": _string()}, input_required=("service_id", "date_from", "date_to")),
            _medical_context(patient=True),
            query_fields=("service_id", "date_from", "date_to", "doctor_id", "location_id"),
        ),
        ToolDefinition(
            "medical.create_appointment",
            "建立檢查／治療預約。",
            "POST",
            "/mock/medical/v1/appointments",
            _envelope_schema({"patient_id": _string(), "service_id": _string(), "slot_id": _string(), "referring_appointment_id": _string(), "administrative_note": _string(), "consent": _boolean()}, input_required=("patient_id", "service_id", "slot_id", "consent")),
            _medical_context(patient=True, post=True),
            "R2",
            body_mode="json",
        ),
        ToolDefinition(
            "medical.get_my_appointments",
            "查詢目前病人的預約清單。",
            "GET",
            "/mock/medical/v1/appointments",
            _envelope_schema({"status": _string(), "appointment_type": _string(), "date_from": _string(), "date_to": _string(), "page": _integer(), "page_size": _integer()}),
            _medical_context(patient=True),
            query_fields=("status", "appointment_type", "date_from", "date_to", "page", "page_size"),
        ),
        ToolDefinition(
            "medical.get_appointment",
            "查詢單筆醫療預約。",
            "GET",
            "/mock/medical/v1/appointments/{appointmentId}",
            _envelope_schema({"appointment_id": _string()}, input_required=("appointment_id",)),
            _medical_context(patient=True),
            path_params={"appointmentId": "appointment_id"},
        ),
        ToolDefinition(
            "medical.get_task_status",
            "查詢醫療提交 task 狀態。",
            "GET",
            "/mock/medical/v1/tasks/{taskId}",
            _envelope_schema({"task_id": _string()}, input_required=("task_id",)),
            _medical_context(patient=True),
            path_params={"taskId": "task_id"},
        ),
    )
    return ToolRegistry(definitions)
