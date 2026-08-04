"""Deterministic, user-safe recovery plans for task failures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import RecoveryField, RecoveryOption, RecoveryPlan


_FIELD_LABELS = {
    "contact_phone": "聯絡電話",
    "identity_document": "身份資料",
    "department_id": "科室選擇",
    "service_id": "服務選擇",
    "slot_id": "預約時段",
}
_RECOVERABLE_CODES = frozenset({
    "MISSING_REQUIRED_FIELD",
    "SCHEDULE_FULL",
    "NO_AVAILABLE_SLOTS",
    "SLOT_NOT_AVAILABLE",
    "BACKEND_UNAVAILABLE",
    "BACKEND_TIMEOUT",
})
_TRANSIENT_CODES = frozenset({"BACKEND_UNAVAILABLE", "BACKEND_TIMEOUT"})
_SUBMIT_CONFLICT_CODES = frozenset({"DUPLICATE_BOOKING"})


def build_recovery_plan(
    *,
    error: Mapping[str, Any] | None,
    step_id: str,
    workflow: str,
    data: Mapping[str, Any],
    result_data: Any,
    retryable: bool,
) -> RecoveryPlan | None:
    """Map a safe subset of a failed result into a recovery plan."""

    del workflow
    code = _error_code(error)
    if step_id == "search_slots" and result_data == []:
        return _availability_plan(error, data)
    if code == "MISSING_REQUIRED_FIELD":
        return _missing_information_plan(error)
    if code in _SUBMIT_CONFLICT_CODES:
        return _booking_conflict_plan(data)
    if code in {"SCHEDULE_FULL", "NO_AVAILABLE_SLOTS", "SLOT_NOT_AVAILABLE"}:
        return _availability_plan(error, data)
    if code in _TRANSIENT_CODES and retryable:
        return _temporary_failure_plan(code)
    return None


def is_hard_failure(error: Mapping[str, Any] | None) -> bool:
    """Return whether an error has no deterministic recovery plan."""

    return error is not None and _error_code(error) not in _RECOVERABLE_CODES


def _missing_information_plan(error: Mapping[str, Any] | None) -> RecoveryPlan:
    details = _details(error)
    raw_fields: list[Any] = []
    if isinstance(details.get("field"), str):
        raw_fields.append(details["field"])
    if isinstance(details.get("fields"), list):
        raw_fields.extend(details["fields"])

    fields: list[RecoveryField] = []
    seen: set[str] = set()
    for value in raw_fields:
        if not isinstance(value, str) or not value.strip():
            continue
        name = value.strip()
        if name in seen:
            continue
        seen.add(name)
        fields.append(RecoveryField(
            name=name,
            label=_FIELD_LABELS.get(name, "必要資料"),
            reason="服務中心需要這項資料才能繼續。",
        ))

    return RecoveryPlan(
        category="missing_information",
        reason_code="MISSING_REQUIRED_FIELD",
        explanation="服務中心需要補充資料才能繼續。",
        required_fields=tuple(fields),
        options=(
            RecoveryOption("human_help", "轉接人工協助"),
            RecoveryOption("cancel", "取消這次服務"),
        ),
    )


def _booking_conflict_plan(data: Mapping[str, Any]) -> RecoveryPlan:
    options: list[RecoveryOption] = []
    search_option = _same_service_search_option(data)
    if search_option.payload.get("service_id") and search_option.payload.get("date_from") and search_option.payload.get("date_to"):
        options.append(search_option)
    options.extend([
        RecoveryOption("cancel", "取消這次預約", {}),
        RecoveryOption("human_help", "轉接人工協助", {}),
    ])
    return RecoveryPlan(
        category="booking_conflict",
        reason_code="DUPLICATE_BOOKING",
        explanation="你已有同一時間的有效預約，這個時段不能再預約；可以重新查找其他可預約時段，或選擇其他協助方式。",
        options=tuple(options),
    )


def _availability_plan(
    error: Mapping[str, Any] | None,
    data: Mapping[str, Any],
) -> RecoveryPlan:
    details = _details(error)
    candidates = details.get("alternatives")
    if not isinstance(candidates, list):
        candidates = details.get("available_slots")
    options = _alternative_options(candidates, data)
    reason_code = _error_code(error) or "NO_AVAILABLE_SLOTS"
    if reason_code == "SLOT_NOT_AVAILABLE":
        options.insert(0, _same_service_search_option(data))
    if not options:
        options = [RecoveryOption("retry", "重新搜尋", {})]
    options.append(RecoveryOption("cancel", "取消這次預約", {}))
    if reason_code not in {"SCHEDULE_FULL", "NO_AVAILABLE_SLOTS", "SLOT_NOT_AVAILABLE"}:
        reason_code = "NO_AVAILABLE_SLOTS"
    explanation = (
        "剛才選擇的時段已被其他預約佔用，請重新搜尋其他可預約時段。"
        if reason_code == "SLOT_NOT_AVAILABLE"
        else "目前選擇的服務和日期範圍沒有可預約名額。"
    )
    return RecoveryPlan(
        category="availability",
        reason_code=reason_code,
        explanation=explanation,
        options=tuple(options),
    )


def _same_service_search_option(data: Mapping[str, Any]) -> RecoveryOption:
    payload: dict[str, Any] = {}
    service_id = data.get("service_id")
    if isinstance(service_id, str) and service_id.strip():
        payload["service_id"] = service_id.strip()
    for key in ("date_from", "date_to"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()
    return RecoveryOption("search_slots", "重新搜尋其他可預約時段", payload)


def _alternative_options(value: Any, data: Mapping[str, Any]) -> list[RecoveryOption]:
    if not isinstance(value, list):
        return []
    options: list[RecoveryOption] = []
    for index, candidate in enumerate(value, start=1):
        if not isinstance(candidate, Mapping):
            continue
        slot_id = candidate.get("slot_id") or candidate.get("id")
        if isinstance(slot_id, str) and slot_id.strip():
            options.append(RecoveryOption(
                "select_slot",
                f"選擇其他可預約時段 {index}",
                {"slot_id": slot_id.strip()},
            ))
            continue
        service_id = candidate.get("service_id")
        if isinstance(service_id, str) and service_id.strip():
            payload = {"service_id": service_id.strip()}
            for key in ("date_from", "date_to"):
                value = candidate.get(key, data.get(key))
                if isinstance(value, str) and value.strip():
                    payload[key] = value.strip()
            options.append(RecoveryOption(
                "search_slots",
                f"搜尋其他服務時段 {index}",
                payload,
            ))
    return options


def _temporary_failure_plan(reason_code: str) -> RecoveryPlan:
    return RecoveryPlan(
        category="temporary_failure",
        reason_code=reason_code,
        explanation="服務中心暫時未能完成這一步，但這項服務仍可以繼續。",
        options=(
            RecoveryOption("retry", "再試一次"),
            RecoveryOption("cancel", "取消這次服務"),
            RecoveryOption("human_help", "轉接人工協助"),
        ),
    )


def _error_code(error: Mapping[str, Any] | None) -> str | None:
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code.strip().upper() if isinstance(code, str) and code.strip() else None


def _details(error: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(error, Mapping) or not isinstance(error.get("details"), Mapping):
        return {}
    return error["details"]
