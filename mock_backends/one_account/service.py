"""Business operations for the One Account mock domain."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from typing import Any, Callable

from mock_backends.core.contracts import Clock, IdGenerator, IdempotencyStore, RecordRepository
from mock_backends.core.errors import DomainError
from mock_backends.core.http import BackendResponse, success_body
from mock_backends.core.idempotency import canonical_json_hash
from mock_backends.core.persistence import MemoryRepository

from .contracts import parse_date, required_body, required_idempotency_key, required_user_id
from .fixtures import SERVICE_CENTERS, activity as activity_fixture, activities, cash_sharing_plan


class OneAccountService:
    def __init__(
        self,
        clock: Clock,
        ids: IdGenerator,
        application_repository: RecordRepository,
        ticket_repository: RecordRepository,
        idempotency: IdempotencyStore,
        activity_registration_repository: RecordRepository | None = None,
        phone_assistance_repository: RecordRepository | None = None,
    ) -> None:
        self.clock = clock
        self.ids = ids
        self.application_repository = application_repository
        self.ticket_repository = ticket_repository
        self.idempotency = idempotency
        self.activity_registration_repository = activity_registration_repository or MemoryRepository()
        self.phone_assistance_repository = phone_assistance_repository or MemoryRepository()

    def _response(self, request_id: str, status: int, data: Any) -> BackendResponse:
        return BackendResponse(status=status, body=success_body(request_id, data))

    @staticmethod
    def _saved_response(saved: dict[str, Any]) -> BackendResponse:
        response = saved["response"]
        return BackendResponse(
            status=response["status"],
            body=deepcopy(response["body"]),
            headers=deepcopy(response.get("headers", {"Content-Type": "application/json"})),
        )

    def _idempotent(
        self,
        user_id: str,
        path: str,
        headers: dict[str, str],
        body: dict[str, Any],
        operation: Callable[[], BackendResponse],
    ) -> BackendResponse:
        key = required_idempotency_key(headers)
        scope = f"{user_id}:{path}"
        request_hash = canonical_json_hash(body)
        saved = self.idempotency.lookup(scope, key)
        if saved is not None:
            self.idempotency.remember(scope, key, request_hash, saved["response"])
            return self._saved_response(saved)
        response = operation()
        self.idempotency.remember(
            scope,
            key,
            request_hash,
            {"status": response.status, "body": response.body, "headers": response.headers},
        )
        return response

    def submit_pension_application(
        self,
        user_id: str,
        headers: dict[str, str],
        body: dict[str, Any] | None,
        request_id: str,
        path: str = "/pension/applications",
    ) -> BackendResponse:
        payload = required_body(body)

        def create() -> BackendResponse:
            applicant = payload.get("applicant")
            account = payload.get("payment_account")
            documents = payload.get("documents")
            consents = payload.get("consents")
            confirmation = payload.get("confirmation")
            if not isinstance(applicant, dict) or not applicant.get("full_name"):
                raise DomainError(400, "VALIDATION_ERROR", "applicant.full_name 為必填欄位。")
            if not isinstance(account, dict):
                raise DomainError(400, "VALIDATION_ERROR", "payment_account 為必填欄位。")
            document_types = {
                item.get("document_type")
                for item in documents
                if isinstance(item, dict)
            } if isinstance(documents, list) else set()
            missing = sorted({"identity_document", "bank_account_proof"} - document_types)
            if missing:
                raise DomainError(422, "MISSING_DOCUMENT", "缺少必要的 mock 文件。", {"missing": missing})
            if not isinstance(consents, dict) or consents.get("data_processing") is not True:
                raise DomainError(422, "CONSENT_REQUIRED", "必須同意資料處理。")
            if not isinstance(confirmation, dict) or not confirmation.get("confirmation_id"):
                raise DomainError(409, "CONFIRMATION_REQUIRED", "提交養老金申請前需要本人確認。")
            if self.application_repository.find(
                lambda item: item.get("user_id") == user_id
                and item.get("application_type") == "pension"
                and item.get("applicant", {}).get("id_document_number")
                == applicant.get("id_document_number")
            ):
                raise DomainError(409, "DUPLICATE_SUBMISSION", "同一 mock user 已有相同申請。")

            application_id = self.ids.next("PEN")
            submitted_at = self.clock.now().isoformat()
            record = {
                "id": application_id,
                "application_id": application_id,
                "user_id": user_id,
                "application_type": "pension",
                "applicant": deepcopy(applicant),
                "status": "SUBMITTED",
                "submitted_at": submitted_at,
                "request": deepcopy(payload),
            }
            self.application_repository.insert(record)
            application = {
                "application_id": application_id,
                "application_type": "pension",
                "applicant_name": applicant["full_name"],
                "status": "SUBMITTED",
                "submitted_at": submitted_at,
                "next_action": {
                    "type": "WAIT_FOR_REVIEW",
                    "message": "申請已提交，Mock 審核服務將在下一次狀態檢查時返回結果。",
                },
            }
            return self._response(
                request_id,
                201,
                {
                    "application": application,
                    "receipt": {
                        "receipt_id": self.ids.next("REC"),
                        "official_reference": self.ids.next("PEN-MOCK"),
                        "received_at": submitted_at,
                    },
                },
            )

        return self._idempotent(user_id, path, headers, payload, create)

    def get_cash_sharing_plan(
        self,
        user_id: str,
        query: dict[str, list[str]],
        request_id: str,
    ) -> BackendResponse:
        values = query.get("year", [])
        raw_year = values[0] if values else str(self.clock.now().year)
        try:
            year = int(raw_year)
        except ValueError as exc:
            raise DomainError(400, "INVALID_YEAR", "year 必須是四位數字。") from exc
        plan = cash_sharing_plan(year)
        if plan is None:
            raise DomainError(404, "PLAN_NOT_FOUND", "指定年度沒有 mock 計劃。", {"year": year})
        if (query.get("include_history", ["false"])[0].lower() != "true"):
            plan["history"] = []
        plan["last_updated_at"] = self.clock.now().isoformat()
        return self._response(request_id, 200, {"plan": plan, "history": plan.pop("history")})

    def create_queue_ticket(
        self,
        user_id: str,
        queue_type: str,
        body: dict[str, Any] | None,
        headers: dict[str, str],
        request_id: str,
        path: str,
    ) -> BackendResponse:
        payload = required_body(body)

        def create() -> BackendResponse:
            confirmation = payload.get("confirmation")
            if not isinstance(confirmation, dict) or not confirmation.get("confirmation_id"):
                raise DomainError(409, "CONFIRMATION_REQUIRED", "建立籌號前需要使用者確認。")
            center_id = payload.get("service_center_id")
            expected_center = "GSC-MAIN" if queue_type == "government_service_center" else "IDB-MAIN"
            if center_id != expected_center or center_id not in SERVICE_CENTERS:
                raise DomainError(422, "INVALID_SERVICE_CENTER", "不支援的服務中心 ID。", {"service_center_id": center_id})
            requested_date = parse_date(payload.get("requested_date"), "requested_date")
            if requested_date < self.clock.now().date():
                raise DomainError(422, "INVALID_REQUESTED_DATE", "requested_date 不可以是過去日期。")
            service_type = payload.get("service_type")
            if queue_type == "government_service_center":
                allowed = {"general_counter", "social_service_counter", "other"}
            else:
                allowed = {"identity_card_renewal", "identity_card_replacement", "travel_document"}
            if service_type not in allowed:
                raise DomainError(422, "INVALID_SERVICE_TYPE", "不支援的辦理事項。", {"service_type": service_type})
            if queue_type == "identification_services_bureau" and not payload.get("document_type"):
                raise DomainError(400, "VALIDATION_ERROR", "document_type 為必填欄位。")
            duplicate = self.ticket_repository.find(
                lambda item: item.get("user_id") == user_id
                and item.get("service_center_id") == center_id
                and item.get("service_type") == service_type
                and item.get("requested_date") == requested_date.isoformat()
                and item.get("status") in {"WAITING", "CALLED"}
            )
            if duplicate:
                raise DomainError(409, "ACTIVE_TICKET_EXISTS", "同一 mock user 已有有效籌號。")

            ticket_id = self.ids.next("Q-GSC" if queue_type == "government_service_center" else "Q-IDB")
            issued_at = self.clock.now().isoformat()
            prefix = "A" if queue_type == "government_service_center" else "B"
            position = 20 + len(self.ticket_repository.list()) + 1
            ticket = {
                "ticket_id": ticket_id,
                "id": ticket_id,
                "user_id": user_id,
                "service_category": SERVICE_CENTERS[center_id]["service_category"],
                "service_center_id": center_id,
                "service_center_name": SERVICE_CENTERS[center_id]["service_center_name"],
                "service_type": service_type,
                "requested_date": requested_date.isoformat(),
                "ticket_number": f"{prefix}{position:03d}",
                "status": "WAITING",
                "queue_position": position,
                "now_serving": f"{prefix}{max(1, position - 11):03d}",
                "estimated_wait_minutes": max(5, position * 2),
                "issued_at": issued_at,
                "valid_until": f"{requested_date.isoformat()}T17:00:00+08:00",
                "instructions": [
                    "請於指定日期到服務中心報到。",
                    "籌號接近時，Mock Notification Service 會發送提醒。",
                ],
            }
            if queue_type == "identification_services_bureau":
                ticket["document_type"] = payload["document_type"]
            self.ticket_repository.insert(ticket)
            return self._response(request_id, 201, {"ticket": ticket})

        return self._idempotent(user_id, path, headers, payload, create)

    def list_queue_tickets(
        self,
        user_id: str,
        query: dict[str, list[str]],
        request_id: str,
    ) -> BackendResponse:
        tickets = self.ticket_repository.find(lambda item: item.get("user_id") == user_id)
        requested_status = set(query.get("status", [""])[0].split(",")) - {""}
        if requested_status:
            tickets = [ticket for ticket in tickets if ticket.get("status") in requested_status]
        return self._response(
            request_id,
            200,
            {"tickets": tickets, "meta": {"total": len(tickets)}},
        )

    @staticmethod
    def _query_value(query: dict[str, list[str]], name: str, default: str = "") -> str:
        value = query.get(name, [default])
        if isinstance(value, list):
            return value[0] if value else default
        return str(value)

    @staticmethod
    def _csv(query: dict[str, list[str]], name: str) -> set[str]:
        return {item.strip() for item in OneAccountService._query_value(query, name).split(",") if item.strip()}

    def _activity_or_error(self, activity_id: str) -> dict[str, Any]:
        item = activity_fixture(activity_id)
        if item is None or item.get("status") != "published":
            raise DomainError(
                404,
                "ACTIVITY_NOT_FOUND",
                "找不到指定的活動，或活動已不再公開。",
                {"activity_id": activity_id},
            )
        return item

    def _activity_registered_count(self, activity_id: str) -> int:
        return len(
            self.activity_registration_repository.find(
                lambda item: item.get("activity_id") == activity_id
            )
        )

    def _activity_for_response(self, item: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(item)
        registered = self._activity_registered_count(item["activity_id"])
        availability = result["availability"]
        availability["registered"] = availability["registered"] + registered
        availability["remaining"] = max(0, availability["quota"] - availability["registered"])
        availability["last_checked_at"] = self.clock.now().isoformat()
        result.pop("form", None)
        return result

    def search_activities(
        self,
        query: dict[str, list[str]],
        request_id: str,
    ) -> BackendResponse:
        now = self.clock.now()
        keyword = self._query_value(query, "keyword").casefold()
        organization_id = self._query_value(query, "organization_id")
        activity_types = self._csv(query, "activity_type")
        categories = self._csv(query, "category")
        districts = self._csv(query, "district")
        methods = self._csv(query, "registration_method")
        accessibility = self._csv(query, "accessibility")
        try:
            date_from = parse_date(self._query_value(query, "date_from"), "date_from") if self._query_value(query, "date_from") else now.date()
            date_to = parse_date(self._query_value(query, "date_to"), "date_to") if self._query_value(query, "date_to") else None
            participant_age = int(self._query_value(query, "participant_age")) if self._query_value(query, "participant_age") else None
            page = int(self._query_value(query, "page", "1"))
            page_size = int(self._query_value(query, "page_size", "20"))
        except ValueError as exc:
            raise DomainError(400, "INVALID_QUERY", "活動搜尋 query parameter 格式不正確。") from exc
        if page < 1 or page_size < 1 or page_size > 100:
            raise DomainError(400, "INVALID_QUERY", "page/page_size 超出有效範圍。")
        if date_to is not None and date_to < date_from:
            raise DomainError(400, "INVALID_QUERY", "date_to 不可以早於 date_from。")
        available_only = self._query_value(query, "available_only", "true").lower() != "false"

        matched: list[dict[str, Any]] = []
        for raw in activities():
            item = self._activity_for_response(raw)
            start_at = datetime.fromisoformat(item["schedule"]["start_at"])
            start_date = start_at.date()
            search_text = " ".join(
                [
                    item["title"],
                    item["summary"],
                    item["organization"]["name"],
                    *item.get("tags", []),
                ]
            ).casefold()
            if item["status"] != "published":
                continue
            if available_only and (
                start_at <= now
                or item["registration"]["status"] != "open"
                or item["availability"]["remaining"] <= 0
            ):
                continue
            if keyword and keyword not in search_text:
                continue
            if organization_id and item["organization"]["organization_id"] != organization_id:
                continue
            if activity_types and item["activity_type"] not in activity_types:
                continue
            if categories and item["category"] not in categories:
                continue
            if districts and item["venue"]["district"] not in districts:
                continue
            if methods and item["registration"]["method"] not in methods:
                continue
            if date_to is not None and not (date_from <= start_date <= date_to):
                continue
            if date_to is None and start_date < date_from:
                continue
            if participant_age is not None:
                age_min = item["audience"].get("age_min")
                age_max = item["audience"].get("age_max")
                if age_min is not None and participant_age < age_min:
                    continue
                if age_max is not None and participant_age > age_max:
                    continue
            if accessibility and not accessibility.issubset(set(item["participation"].get("accessibility", []))):
                continue
            matched.append(item)

        sort = self._query_value(query, "sort", "start_at_asc")
        if sort == "start_at_asc":
            matched.sort(key=lambda item: item["schedule"]["start_at"])
        elif sort == "registration_deadline_asc":
            matched.sort(key=lambda item: item["registration"]["deadline"])
        else:
            raise DomainError(400, "INVALID_QUERY", "sort 不支援。")
        total = len(matched)
        start = (page - 1) * page_size
        page_items = matched[start:start + page_size]
        return self._response(
            request_id,
            200,
            {
                "activities": page_items,
                "meta": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "has_next": start + page_size < total,
                },
            },
        )

    def get_activity(self, activity_id: str, request_id: str) -> BackendResponse:
        item = self._activity_or_error(activity_id)
        return self._response(request_id, 200, self._activity_for_response(item))

    def get_activity_registration_form(self, activity_id: str, request_id: str) -> BackendResponse:
        item = self._activity_or_error(activity_id)
        if item["registration"]["method"] != "form":
            raise DomainError(
                409,
                "PHONE_REGISTRATION_REQUIRED",
                "此活動需要致電機構報名，沒有線上填表 schema。",
                {
                    "activity_id": activity_id,
                    "phone": item["registration"]["phone"],
                    "phone_hours": item["registration"]["phone_hours"],
                },
            )
        form = item.get("form")
        if not form:
            raise DomainError(500, "MOCK_SERVICE_ERROR", "活動表格 fixture 不完整。", retryable=False)
        return self._response(
            request_id,
            200,
            {
                "activity_id": activity_id,
                "form_id": form["form_id"],
                "method": "form",
                "title": form["title"],
                "requires_confirmation": True,
                "fields": form["fields"],
                "consents": [{"name": "personal_data", "label": "同意只為本活動報名使用資料", "required": True}],
                "submission": {"method": "POST", "path": "/mock/elderly-activities/v1/registrations"},
            },
        )

    @staticmethod
    def _mask_phone(phone: str) -> str:
        if phone.startswith("+853-") and len(phone) >= 13:
            return f"+853-****-{phone[-4:]}"
        if len(phone) > 4:
            return "*" * (len(phone) - 4) + phone[-4:]
        return "****"

    def create_activity_registration(
        self,
        user_id: str,
        body: dict[str, Any] | None,
        headers: dict[str, str],
        request_id: str,
        path: str,
    ) -> BackendResponse:
        payload = required_body(body)

        def create() -> BackendResponse:
            activity_id = payload.get("activity_id")
            item = self._activity_or_error(activity_id)
            if item["registration"]["method"] != "form":
                raise DomainError(409, "PHONE_REGISTRATION_REQUIRED", "此活動必須使用電話報名。")
            current = self._activity_for_response(item)
            if current["availability"]["remaining"] <= 0 or current["registration"]["status"] != "open":
                raise DomainError(409, "ACTIVITY_FULL", "提交時活動已沒有剩餘名額。", {"activity_id": activity_id})
            form = item.get("form") or {}
            if payload.get("form_id") != form.get("form_id"):
                raise DomainError(422, "FORM_VERSION_MISMATCH", "form_id 不是活動目前的表格 schema。")
            participant = payload.get("participant")
            if not isinstance(participant, dict):
                raise DomainError(422, "MISSING_REQUIRED_FIELD", "participant 為必填欄位。")
            missing = [field["name"] for field in form.get("fields", []) if field.get("required") and not participant.get(field["name"])]
            if missing:
                raise DomainError(422, "MISSING_REQUIRED_FIELD", "缺少表格必要資料。", {"fields": missing})
            age = participant.get("age")
            if not isinstance(age, int):
                raise DomainError(422, "MISSING_REQUIRED_FIELD", "participant.age 為必填欄位。", {"field": "age"})
            if age < item["audience"]["age_min"] or (item["audience"].get("age_max") and age > item["audience"]["age_max"]):
                raise DomainError(422, "AGE_REQUIREMENT_NOT_MET", "參加者年齡不符合活動條件。")
            consents = payload.get("consents")
            if not isinstance(consents, dict) or consents.get("personal_data") is not True:
                raise DomainError(422, "CONSENT_REQUIRED", "必須同意活動報名資料使用。")
            confirmation = payload.get("confirmation")
            if not isinstance(confirmation, dict) or not confirmation.get("confirmation_id"):
                raise DomainError(422, "CONFIRMATION_REQUIRED", "沒有 Ponte Workflow 的明確確認記錄。")
            if self.activity_registration_repository.find(
                lambda record: record.get("user_id") == user_id and record.get("activity_id") == activity_id
            ):
                raise DomainError(409, "DUPLICATE_ACTIVITY_REGISTRATION", "同一 mock 使用者已報名同一活動。")
            registration_id = self.ids.next("REG")
            task_id = self.ids.next("TASK")
            submitted_at = self.clock.now().isoformat()
            registration = {
                "registration_id": registration_id,
                "id": registration_id,
                "user_id": user_id,
                "activity_id": activity_id,
                "method": "form",
                "status": "confirmed",
                "participant": deepcopy(participant),
                "submitted_at": submitted_at,
                "task_id": task_id,
            }
            self.activity_registration_repository.insert(registration)
            safe_registration = {
                "registration_id": registration_id,
                "activity_id": activity_id,
                "method": "form",
                "status": "confirmed",
                "participant": {"display_name": participant["full_name"], "phone_masked": self._mask_phone(participant["phone"])},
                "submitted_at": submitted_at,
                "next_action": {"type": "ATTEND_ACTIVITY", "message": f"請於 {item['schedule']['start_at']} 到 {item['venue']['name']} 報到。"},
            }
            return self._response(
                request_id,
                201,
                {
                    "registration": safe_registration,
                    "receipt": {"receipt_id": self.ids.next("REC"), "official_reference": self.ids.next("ORG-A-MOCK"), "issued_at": submitted_at, "display_message": f"{item['organization']['short_name']} 已收到你的活動報名。"},
                    "task": {"task_id": task_id, "workflow_type": "elderly_activity_form_registration_v1", "status": "completed", "current_step": "complete"},
                },
            )

        return self._idempotent(user_id, path, headers, payload, create)

    def get_activity_registration(self, user_id: str, registration_id: str, request_id: str) -> BackendResponse:
        record = self.activity_registration_repository.get(registration_id)
        if record is None or record.get("user_id") != user_id:
            raise DomainError(404, "REGISTRATION_NOT_FOUND", "找不到指定的活動報名。")
        item = self._activity_or_error(record["activity_id"])
        participant = record["participant"]
        registration = {
            "registration_id": registration_id,
            "activity_id": record["activity_id"],
            "method": "form",
            "status": record["status"],
            "participant": {"display_name": participant["full_name"], "phone_masked": self._mask_phone(participant["phone"])},
            "submitted_at": record["submitted_at"],
            "updated_at": record["submitted_at"],
            "next_action": {"type": "ATTEND_ACTIVITY", "message": f"請於 {item['schedule']['start_at']} 到 {item['venue']['name']} 報到。"},
        }
        return self._response(request_id, 200, registration)

    def create_phone_assistance(
        self,
        user_id: str,
        body: dict[str, Any] | None,
        headers: dict[str, str],
        request_id: str,
        path: str,
    ) -> BackendResponse:
        payload = required_body(body)

        def create() -> BackendResponse:
            activity_id = payload.get("activity_id")
            item = self._activity_or_error(activity_id)
            if item["registration"]["method"] != "phone":
                raise DomainError(409, "FORM_REGISTRATION_AVAILABLE", "該活動可用線上表格，應改用 POST /registrations。")
            current = self._activity_for_response(item)
            if current["availability"]["remaining"] <= 0:
                raise DomainError(409, "ACTIVITY_FULL", "建立協助時活動已沒有名額。")
            participant = payload.get("participant")
            if not isinstance(participant, dict) or not participant.get("full_name") or not participant.get("phone") or not isinstance(participant.get("age"), int):
                raise DomainError(422, "MISSING_CALL_INFORMATION", "缺少電話報名所需的參加者資料。")
            if "圖書館讀者證" in item["registration"].get("required_information", []) and "library_reader_card" not in participant:
                raise DomainError(422, "MISSING_CALL_INFORMATION", "缺少圖書館讀者證資料。")
            confirmation = payload.get("confirmation")
            if not isinstance(confirmation, dict) or not confirmation.get("confirmation_id"):
                raise DomainError(422, "CONFIRMATION_REQUIRED", "沒有 Ponte Workflow 的明確確認記錄。")
            if self.phone_assistance_repository.find(
                lambda record: record.get("user_id") == user_id
                and record.get("activity_id") == activity_id
                and record.get("status") not in {"completed", "failed"}
            ):
                raise DomainError(409, "DUPLICATE_PHONE_ASSISTANCE", "同一 mock 使用者已有未完成的電話協助任務。")
            assistance_id = self.ids.next("PRA")
            task_id = self.ids.next("TASK")
            created_at = self.clock.now().isoformat()
            assistance = {
                "assistance_id": assistance_id,
                "id": assistance_id,
                "user_id": user_id,
                "activity_id": activity_id,
                "activity_title": item["title"],
                "organization_id": item["organization"]["organization_id"],
                "method": "phone",
                "status": "waiting_for_phone_call",
                "organization_phone": item["registration"]["phone"],
                "phone_hours": item["registration"]["phone_hours"],
                "required_information": item["registration"]["required_information"],
                "created_at": created_at,
                "updated_at": created_at,
                "participant": deepcopy(participant),
                "task_id": task_id,
            }
            self.phone_assistance_repository.insert(assistance)
            safe_assistance = {
                "assistance_id": assistance_id,
                "activity_id": activity_id,
                "activity_title": item["title"],
                "organization_id": item["organization"]["organization_id"],
                "method": "phone",
                "status": "ready_for_call",
                "organization_phone": item["registration"]["phone"],
                "phone_hours": item["registration"]["phone_hours"],
                "required_information": item["registration"]["required_information"],
                "call_script": [f"你好，我想報名 {item['schedule']['start_at'][:10]} 的「{item['title']}」。", f"參加者姓名是{participant['full_name']}，{participant['age']}歲。", "請問現在還有名額嗎？"],
                "next_action": "尚未完成官方報名：由 Agent 或長者在服務時間致電機構，並把結果更新到此協助任務。",
                "created_at": created_at,
                "expires_at": f"{item['registration']['deadline']}T19:00:00+08:00",
            }
            return self._response(
                request_id,
                202,
                {
                    "assistance": safe_assistance,
                    "task": {"task_id": task_id, "workflow_type": "elderly_activity_phone_registration_v1", "status": "waiting_for_phone_call", "current_step": "call_organization"},
                },
            )

        return self._idempotent(user_id, path, headers, payload, create)

    def get_phone_assistance(self, user_id: str, assistance_id: str, request_id: str) -> BackendResponse:
        record = self.phone_assistance_repository.get(assistance_id)
        if record is None or record.get("user_id") != user_id:
            raise DomainError(404, "PHONE_ASSISTANCE_NOT_FOUND", "找不到指定的電話報名協助任務。")
        return self._response(
            request_id,
            200,
            {
                "assistance_id": assistance_id,
                "activity_id": record["activity_id"],
                "activity_title": record["activity_title"],
                "organization_id": record["organization_id"],
                "method": "phone",
                "status": record["status"],
                "organization_phone": record["organization_phone"],
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
                "next_action": "等待 Agent 或長者致電機構；尚未完成官方報名。",
                "events": [{"event_type": "phone_assistance_created", "timestamp": record["created_at"]}],
            },
        )
