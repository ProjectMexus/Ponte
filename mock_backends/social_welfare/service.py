"""Minimal social welfare search and referral handoff service."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from mock_backends.core.contracts import Clock, IdGenerator, IdempotencyStore, RecordRepository
from mock_backends.core.errors import DomainError
from mock_backends.core.http import BackendResponse, success_body
from mock_backends.core.idempotency import canonical_json_hash

from .contracts import body_or_empty, required_body, required_idempotency_key
from .fixtures import case_workers, services


class SocialWelfareService:
    def __init__(
        self,
        clock: Clock,
        ids: IdGenerator,
        referral_repository: RecordRepository,
        idempotency: IdempotencyStore,
    ) -> None:
        self.clock = clock
        self.ids = ids
        self.referral_repository = referral_repository
        self.idempotency = idempotency

    def _response(self, request_id: str, status: int, data: Any, meta: dict[str, Any] | None = None) -> BackendResponse:
        body = success_body(request_id, data)
        if meta is not None:
            body["meta"] = meta
        return BackendResponse(status, body)

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

    def search_services(self, query: dict[str, list[str]], request_id: str) -> BackendResponse:
        keyword = self._value(query, "keyword").casefold()
        category = self._value(query, "category")
        district = self._value(query, "district")
        accessibility = {item.strip() for item in self._value(query, "accessibility").split(",") if item.strip()}
        active_only = self._value(query, "active_only", "true").lower() != "false"
        result = []
        for item in services():
            if active_only and not item["active"]:
                continue
            searchable = f"{item['name']} {item['summary']} {item['category']}".casefold()
            if keyword and keyword not in searchable:
                continue
            if category and item["category"] != category:
                continue
            if district and district not in item["districts"]:
                continue
            if accessibility and not accessibility.issubset(set(item["accessibility"])):
                continue
            result.append(item)
        return self._response(request_id, 200, {"services": result}, {"total": len(result)})

    def _service(self, service_id: str) -> dict[str, Any]:
        for item in services():
            if item["service_id"] == service_id and item["active"]:
                return item
        raise DomainError(404, "SERVICE_NOT_FOUND", "找不到指定的社福服務。", {"service_id": service_id})

    @staticmethod
    def _referral_view(record: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(record)
        result.pop("id", None)
        result.pop("user_id", None)
        result.pop("request", None)
        return result

    def create_referral(self, user_id: str, body: dict[str, Any] | None, headers: dict[str, str], request_id: str, path: str) -> BackendResponse:
        payload = required_body(body)

        def create() -> BackendResponse:
            service_id = payload.get("service_id")
            service = self._service(service_id)
            subject = payload.get("subject")
            if not isinstance(subject, dict) or not subject.get("display_name"):
                raise DomainError(422, "MISSING_REQUIRED_FIELD", "subject.display_name 為必填欄位。")
            if not payload.get("need_summary"):
                raise DomainError(422, "MISSING_REQUIRED_FIELD", "need_summary 為必填欄位。")
            if not isinstance(payload.get("preferred_contact"), dict):
                raise DomainError(422, "MISSING_REQUIRED_FIELD", "preferred_contact 為必填欄位。")
            consents = payload.get("consents")
            if not isinstance(consents, dict) or consents.get("data_sharing") is not True:
                raise DomainError(422, "CONSENT_REQUIRED", "建立轉介前必須同意資料共享。")
            confirmation = payload.get("confirmation")
            if not isinstance(confirmation, dict) or not confirmation.get("confirmation_id"):
                raise DomainError(409, "CONFIRMATION_REQUIRED", "建立轉介前需要長者明確確認。")
            referral_id = self.ids.next("REF")
            created_at = self.clock.now().isoformat()
            record = {
                "id": referral_id,
                "referral_id": referral_id,
                "user_id": user_id,
                "service": deepcopy(service),
                "subject": deepcopy(subject),
                "need_summary": payload["need_summary"],
                "preferred_contact": deepcopy(payload["preferred_contact"]),
                "status": "PENDING",
                "created_at": created_at,
                "updated_at": created_at,
                "assigned_worker": None,
                "next_action": {"type": "WAIT_FOR_CASE_WORKER", "message": "等待社工接手，Mock 服務會在下一次狀態檢查時更新。"},
                "request": deepcopy(payload),
            }
            self.referral_repository.insert(record)
            return self._response(
                request_id,
                201,
                {
                    "referral": self._referral_view(record),
                    "receipt": {"receipt_id": self.ids.next("REC"), "reference": self.ids.next("WELFARE-MOCK"), "issued_at": created_at},
                },
            )

        return self._idempotent(user_id, path, headers, payload, create)

    def get_referral(self, user_id: str, referral_id: str, request_id: str) -> BackendResponse:
        record = self.referral_repository.get(referral_id)
        if record is None or record.get("user_id") != user_id:
            raise DomainError(404, "REFERRAL_NOT_FOUND", "找不到指定的社福轉介。")
        return self._response(request_id, 200, {"referral": self._referral_view(record)})

    def assign_referral(self, user_id: str, referral_id: str, body: dict[str, Any] | None, headers: dict[str, str], request_id: str, path: str) -> BackendResponse:
        payload = body_or_empty(body)

        def assign() -> BackendResponse:
            record = self.referral_repository.get(referral_id)
            if record is None or record.get("user_id") != user_id:
                raise DomainError(404, "REFERRAL_NOT_FOUND", "找不到指定的社福轉介。")
            if record.get("status") == "ASSIGNED":
                raise DomainError(409, "REFERRAL_ALREADY_ASSIGNED", "轉介已由社工接手。")
            worker_id = payload.get("case_worker_id", "CW-001")
            worker = next((item for item in case_workers() if item["case_worker_id"] == worker_id), None)
            if worker is None:
                raise DomainError(422, "CASE_WORKER_NOT_FOUND", "找不到指定的 mock case worker。")
            updated = deepcopy(record)
            updated["status"] = "ASSIGNED"
            updated["assigned_worker"] = worker
            updated["updated_at"] = self.clock.now().isoformat()
            updated["next_action"] = {"type": "WAIT_FOR_CONTACT", "message": "Mock 社工已接手，將按偏好聯絡時間跟進。"}
            self.referral_repository.replace(referral_id, updated)
            return self._response(request_id, 200, {"referral": self._referral_view(updated)})

        return self._idempotent(user_id, path, headers, payload, assign)
