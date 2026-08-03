"""Business operations for the One Account mock domain."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from mock_backends.core.contracts import Clock, IdGenerator, IdempotencyStore, RecordRepository
from mock_backends.core.errors import DomainError
from mock_backends.core.http import BackendResponse, success_body
from mock_backends.core.idempotency import canonical_json_hash

from .contracts import parse_date, required_body, required_idempotency_key, required_user_id
from .fixtures import SERVICE_CENTERS, cash_sharing_plan


class OneAccountService:
    def __init__(
        self,
        clock: Clock,
        ids: IdGenerator,
        application_repository: RecordRepository,
        ticket_repository: RecordRepository,
        idempotency: IdempotencyStore,
    ) -> None:
        self.clock = clock
        self.ids = ids
        self.application_repository = application_repository
        self.ticket_repository = ticket_repository
        self.idempotency = idempotency

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
