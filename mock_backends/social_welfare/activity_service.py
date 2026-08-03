"""Longer-running activity registration operations in the social welfare domain."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from mock_backends.core.contracts import Clock, IdGenerator, IdempotencyStore, RecordRepository
from mock_backends.core.errors import DomainError
from mock_backends.core.http import BackendResponse, success_body
from mock_backends.core.idempotency import canonical_json_hash

from .activity_fixtures import activities, activity as activity_fixture
from .contracts import required_body, required_idempotency_key


class ElderlyActivitiesService:
    def __init__(
        self,
        clock: Clock,
        ids: IdGenerator,
        registration_repository: RecordRepository,
        phone_assistance_repository: RecordRepository,
        idempotency: IdempotencyStore,
    ) -> None:
        self.clock = clock
        self.ids = ids
        self.registration_repository = registration_repository
        self.phone_assistance_repository = phone_assistance_repository
        self.idempotency = idempotency

    def _response(self, request_id: str, status: int, data: Any) -> BackendResponse:
        return BackendResponse(status, success_body(request_id, data))

    @staticmethod
    def _saved_response(saved: dict[str, Any]) -> BackendResponse:
        response = saved["response"]
        return BackendResponse(response["status"], deepcopy(response["body"]), deepcopy(response.get("headers", {"Content-Type": "application/json"})))

    def _idempotent(self, user_id: str, path: str, headers: dict[str, str], body: dict[str, Any], operation: Callable[[], BackendResponse]) -> BackendResponse:
        key = required_idempotency_key(headers)
        scope = f"{user_id}:{path}"
        request_hash = canonical_json_hash(body)
        saved = self.idempotency.lookup(scope, key)
        if saved is not None:
            self.idempotency.remember(scope, key, request_hash, saved["response"])
            return self._saved_response(saved)
        response = operation()
        self.idempotency.remember(scope, key, request_hash, {"status": response.status, "body": response.body, "headers": response.headers})
        return response

    @staticmethod
    def _value(query: dict[str, list[str]], name: str, default: str = "") -> str:
        value = query.get(name, [default])
        if isinstance(value, list):
            return value[0] if value else default
        return str(value)

    @staticmethod
    def _csv(query: dict[str, list[str]], name: str) -> set[str]:
        return {item.strip() for item in ElderlyActivitiesService._value(query, name).split(",") if item.strip()}

    def _activity_or_error(self, activity_id: str) -> dict[str, Any]:
        item = activity_fixture(activity_id)
        if item is None or item.get("status") != "published":
            raise DomainError(404, "ACTIVITY_NOT_FOUND", "找不到指定的活動，或活動已不再公開。", {"activity_id": activity_id})
        return item

    def _registered_count(self, activity_id: str) -> int:
        return len(self.registration_repository.find(lambda item: item.get("activity_id") == activity_id))

    def _activity_for_response(self, item: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(item)
        result.pop("form", None)
        registered = self._registered_count(item["activity_id"])
        result["availability"]["registered"] += registered
        result["availability"]["remaining"] = max(0, result["availability"]["quota"] - result["availability"]["registered"])
        result["availability"]["last_checked_at"] = self.clock.now().isoformat()
        return result

    def search(self, query: dict[str, list[str]], request_id: str) -> BackendResponse:
        now = self.clock.now()
        keyword = self._value(query, "keyword").casefold()
        organization_id = self._value(query, "organization_id")
        activity_types = self._csv(query, "activity_type")
        categories = self._csv(query, "category")
        methods = self._csv(query, "registration_method")
        accessibility = self._csv(query, "accessibility")
        district = self._value(query, "district")
        try:
            date_from = datetime.fromisoformat(self._value(query, "date_from") + "T00:00:00+08:00").date() if self._value(query, "date_from") else now.date()
            date_to = datetime.fromisoformat(self._value(query, "date_to") + "T00:00:00+08:00").date() if self._value(query, "date_to") else None
            participant_age = int(self._value(query, "participant_age")) if self._value(query, "participant_age") else None
            page = int(self._value(query, "page", "1"))
            page_size = int(self._value(query, "page_size", "20"))
        except ValueError as exc:
            raise DomainError(400, "INVALID_QUERY", "活動搜尋 query parameter 格式不正確。") from exc
        if page < 1 or page_size < 1 or page_size > 100 or (date_to is not None and date_to < date_from):
            raise DomainError(400, "INVALID_QUERY", "活動搜尋 query parameter 超出有效範圍。")
        available_only = self._value(query, "available_only", "true").lower() != "false"
        matched = []
        for raw in activities():
            item = self._activity_for_response(raw)
            start = datetime.fromisoformat(item["schedule"]["start_at"])
            start_date = start.date()
            searchable = " ".join([item["title"], item["summary"], item["organization"]["name"], *item["tags"]]).casefold()
            if available_only and (start <= now or item["registration"]["status"] != "open" or item["availability"]["remaining"] <= 0):
                continue
            if keyword and keyword not in searchable:
                continue
            if organization_id and item["organization"]["organization_id"] != organization_id:
                continue
            if activity_types and item["activity_type"] not in activity_types:
                continue
            if categories and item["category"] not in categories:
                continue
            if methods and item["registration"]["method"] not in methods:
                continue
            if district and item["venue"]["district"] != district:
                continue
            if not (date_from <= start_date and (date_to is None or start_date <= date_to)):
                continue
            if participant_age is not None and participant_age < item["audience"]["age_min"]:
                continue
            if accessibility and not accessibility.issubset(set(item["participation"]["accessibility"])):
                continue
            matched.append(item)
        sort = self._value(query, "sort", "start_at_asc")
        if sort == "start_at_asc":
            matched.sort(key=lambda item: item["schedule"]["start_at"])
        elif sort == "registration_deadline_asc":
            matched.sort(key=lambda item: item["registration"]["deadline"])
        else:
            raise DomainError(400, "INVALID_QUERY", "sort 不支援。")
        total = len(matched)
        start = (page - 1) * page_size
        return self._response(request_id, 200, {"activities": matched[start:start + page_size], "meta": {"page": page, "page_size": page_size, "total": total, "has_next": start + page_size < total}})

    def get_activity(self, activity_id: str, request_id: str) -> BackendResponse:
        return self._response(request_id, 200, self._activity_for_response(self._activity_or_error(activity_id)))

    def get_registration_form(self, activity_id: str, request_id: str) -> BackendResponse:
        item = self._activity_or_error(activity_id)
        if item["registration"]["method"] != "form":
            raise DomainError(409, "PHONE_REGISTRATION_REQUIRED", "此活動需要致電機構報名，沒有線上填表 schema。", {"activity_id": activity_id, "phone": item["registration"]["phone"], "phone_hours": item["registration"]["phone_hours"]})
        form = item.get("form")
        if form is None:
            raise DomainError(500, "MOCK_SERVICE_ERROR", "活動表格 fixture 不完整。")
        return self._response(request_id, 200, {"activity_id": activity_id, "form_id": form["form_id"], "method": "form", "title": form["title"], "requires_confirmation": True, "fields": form["fields"], "consents": [{"name": "personal_data", "label": "同意只為本活動報名使用資料", "required": True}], "submission": {"method": "POST", "path": "/mock/elderly-activities/v1/registrations"}})

    @staticmethod
    def _mask_phone(phone: str) -> str:
        return f"+853-****-{phone[-4:]}" if phone.startswith("+853-") else "*" * max(0, len(phone) - 4) + phone[-4:]

    def create_registration(self, user_id: str, body: dict[str, Any] | None, headers: dict[str, str], request_id: str, path: str) -> BackendResponse:
        payload = required_body(body)

        def create() -> BackendResponse:
            item = self._activity_or_error(payload.get("activity_id"))
            if item["registration"]["method"] != "form":
                raise DomainError(409, "PHONE_REGISTRATION_REQUIRED", "此活動必須使用電話報名。")
            current = self._activity_for_response(item)
            if current["availability"]["remaining"] <= 0 or item["registration"]["status"] != "open":
                raise DomainError(409, "ACTIVITY_FULL", "提交時活動已沒有剩餘名額。")
            form = item["form"]
            if payload.get("form_id") != form["form_id"]:
                raise DomainError(422, "FORM_VERSION_MISMATCH", "form_id 不是活動目前的表格 schema。")
            participant = payload.get("participant")
            if not isinstance(participant, dict):
                raise DomainError(422, "MISSING_REQUIRED_FIELD", "participant 為必填欄位。")
            missing = [field["name"] for field in form["fields"] if field["required"] and not participant.get(field["name"])]
            if missing:
                raise DomainError(422, "MISSING_REQUIRED_FIELD", "缺少表格必要資料。", {"fields": missing})
            if participant["age"] < item["audience"]["age_min"]:
                raise DomainError(422, "AGE_REQUIREMENT_NOT_MET", "參加者年齡不符合活動條件。")
            if not isinstance(payload.get("consents"), dict) or payload["consents"].get("personal_data") is not True:
                raise DomainError(422, "CONSENT_REQUIRED", "必須同意活動報名資料使用。")
            if not isinstance(payload.get("confirmation"), dict) or not payload["confirmation"].get("confirmation_id"):
                raise DomainError(422, "CONFIRMATION_REQUIRED", "沒有 Ponte Workflow 的明確確認記錄。")
            if self.registration_repository.find(lambda record: record.get("user_id") == user_id and record.get("activity_id") == item["activity_id"]):
                raise DomainError(409, "DUPLICATE_ACTIVITY_REGISTRATION", "同一 mock 使用者已報名同一活動。")
            registration_id = self.ids.next("REG")
            submitted_at = self.clock.now().isoformat()
            self.registration_repository.insert({"id": registration_id, "registration_id": registration_id, "user_id": user_id, "activity_id": item["activity_id"], "status": "confirmed", "participant": deepcopy(participant), "submitted_at": submitted_at})
            return self._response(request_id, 201, {"registration": {"registration_id": registration_id, "activity_id": item["activity_id"], "method": "form", "status": "confirmed", "participant": {"display_name": participant["full_name"], "phone_masked": self._mask_phone(participant["phone"])}, "submitted_at": submitted_at, "next_action": {"type": "ATTEND_ACTIVITY", "message": f"請於 {item['schedule']['start_at']} 到 {item['venue']['name']} 報到。"}}, "receipt": {"receipt_id": self.ids.next("REC"), "official_reference": self.ids.next("ORG-MOCK"), "issued_at": submitted_at, "display_message": f"{item['organization']['short_name']} 已收到你的活動報名。"}, "task": {"task_id": self.ids.next("TASK"), "workflow_type": "elderly_activity_form_registration_v1", "status": "completed", "current_step": "complete"}})

        return self._idempotent(user_id, path, headers, payload, create)

    def get_registration(self, user_id: str, registration_id: str, request_id: str) -> BackendResponse:
        record = self.registration_repository.get(registration_id)
        if record is None or record.get("user_id") != user_id:
            raise DomainError(404, "REGISTRATION_NOT_FOUND", "找不到指定的活動報名。")
        item = self._activity_or_error(record["activity_id"])
        participant = record["participant"]
        return self._response(request_id, 200, {"registration_id": registration_id, "activity_id": record["activity_id"], "method": "form", "status": record["status"], "participant": {"display_name": participant["full_name"], "phone_masked": self._mask_phone(participant["phone"])}, "submitted_at": record["submitted_at"], "next_action": {"type": "ATTEND_ACTIVITY", "message": f"請於 {item['schedule']['start_at']} 到 {item['venue']['name']} 報到。"}})

    def create_phone_assistance(self, user_id: str, body: dict[str, Any] | None, headers: dict[str, str], request_id: str, path: str) -> BackendResponse:
        payload = required_body(body)

        def create() -> BackendResponse:
            item = self._activity_or_error(payload.get("activity_id"))
            if item["registration"]["method"] != "phone":
                raise DomainError(409, "FORM_REGISTRATION_AVAILABLE", "該活動可用線上表格，應改用 POST /registrations。")
            if self._activity_for_response(item)["availability"]["remaining"] <= 0:
                raise DomainError(409, "ACTIVITY_FULL", "建立協助時活動已沒有名額。")
            participant = payload.get("participant")
            if not isinstance(participant, dict) or not participant.get("full_name") or not participant.get("phone") or not isinstance(participant.get("age"), int):
                raise DomainError(422, "MISSING_CALL_INFORMATION", "缺少電話報名所需的參加者資料。")
            if not isinstance(payload.get("confirmation"), dict) or not payload["confirmation"].get("confirmation_id"):
                raise DomainError(422, "CONFIRMATION_REQUIRED", "沒有 Ponte Workflow 的明確確認記錄。")
            if self.phone_assistance_repository.find(lambda record: record.get("user_id") == user_id and record.get("activity_id") == item["activity_id"] and record.get("status") not in {"completed", "failed"}):
                raise DomainError(409, "DUPLICATE_PHONE_ASSISTANCE", "同一 mock 使用者已有未完成的電話協助任務。")
            assistance_id = self.ids.next("PRA")
            created_at = self.clock.now().isoformat()
            self.phone_assistance_repository.insert({"id": assistance_id, "assistance_id": assistance_id, "user_id": user_id, "activity_id": item["activity_id"], "activity_title": item["title"], "organization_id": item["organization"]["organization_id"], "status": "waiting_for_phone_call", "organization_phone": item["registration"]["phone"], "created_at": created_at, "updated_at": created_at, "participant": deepcopy(participant)})
            return self._response(request_id, 202, {"assistance": {"assistance_id": assistance_id, "activity_id": item["activity_id"], "activity_title": item["title"], "organization_id": item["organization"]["organization_id"], "method": "phone", "status": "ready_for_call", "organization_phone": item["registration"]["phone"], "phone_hours": item["registration"]["phone_hours"], "required_information": item["registration"]["required_information"], "call_script": [f"你好，我想報名 {item['schedule']['start_at'][:10]} 的「{item['title']}」。", f"參加者姓名是{participant['full_name']}，{participant['age']}歲。", "請問現在還有名額嗎？"], "next_action": "尚未完成官方報名：由 Agent 或長者在服務時間致電機構，並把結果更新到此協助任務。", "created_at": created_at, "expires_at": f"{item['registration']['deadline']}T19:00:00+08:00"}, "task": {"task_id": self.ids.next("TASK"), "workflow_type": "elderly_activity_phone_registration_v1", "status": "waiting_for_phone_call", "current_step": "call_organization"}})

        return self._idempotent(user_id, path, headers, payload, create)

    def get_phone_assistance(self, user_id: str, assistance_id: str, request_id: str) -> BackendResponse:
        record = self.phone_assistance_repository.get(assistance_id)
        if record is None or record.get("user_id") != user_id:
            raise DomainError(404, "PHONE_ASSISTANCE_NOT_FOUND", "找不到指定的電話報名協助任務。")
        return self._response(request_id, 200, {"assistance_id": assistance_id, "activity_id": record["activity_id"], "activity_title": record["activity_title"], "organization_id": record["organization_id"], "method": "phone", "status": record["status"], "organization_phone": record["organization_phone"], "created_at": record["created_at"], "updated_at": record["updated_at"], "next_action": "等待 Agent 或長者致電機構；尚未完成官方報名。", "events": [{"event_type": "phone_assistance_created", "timestamp": record["created_at"]}]})
