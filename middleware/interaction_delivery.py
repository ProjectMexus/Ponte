"""Deterministic delivery projections for canonical interaction results.

The interaction core owns workflow state.  This module only turns that state
into channel-facing text and workspace data, so wording or speech-provider
availability cannot change the authoritative result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from .interaction_contracts import CanonicalInteractionResult
from .speech import to_cantonese_spoken


_VIEW_TITLES = {
    "appointment_list": "我的醫療預約",
    "service_selection": "選擇醫療服務",
    "slot_selection": "選擇預約時段",
    "appointment_confirmation": "確認預約",
    "appointment_recovery": "處理預約問題",
    "appointment_completed": "預約完成",
    "cash_sharing_summary": "現金分享計劃",
    "cash_sharing_recovery": "處理現金分享查詢問題",
}

_SERVICE_INTENTS = frozenset({"select_service", "service_selection"})
_SLOT_INTENTS = frozenset({"select_slot", "slot_selection"})
_CONFIRMATION_INTENTS = frozenset({
    "confirm",
    "confirmation",
    "confirm_appointment",
    "appointment_confirmation",
})
_RECOVERY_INTENTS = frozenset({"recover", "recovery", "appointment_recovery"})
_COMPLETED_INTENTS = frozenset({"complete", "completed", "appointment_completed"})
_CANCELLED_INTENTS = frozenset({"cancel", "cancelled", "canceled"})


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _text(value: Any, default: str = "") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is None:
        return default
    return str(value)


def _normalised(value: Any) -> str:
    return _text(value).casefold().replace("-", "_").replace(" ", "_")


def _task(result: CanonicalInteractionResult) -> dict[str, Any]:
    return _as_mapping(result.task)


def _facts(result: CanonicalInteractionResult) -> dict[str, Any]:
    return _as_mapping(result.facts)


def _record_name(record: Mapping[str, Any], *, fallback: str = "") -> str:
    for key in ("display", "name", "label", "service", "title"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _appointment_details(result: CanonicalInteractionResult) -> dict[str, str]:
    facts = _facts(result)
    details: dict[str, str] = {}
    appointment = facts.get("appointment")
    if not isinstance(appointment, Mapping):
        appointment = _as_mapping(result.receipt).get("appointment")
    if not isinstance(appointment, Mapping):
        appointment = _as_mapping(result.confirmation).get("appointment")
    if not isinstance(appointment, Mapping):
        appointment = {}

    service = appointment.get("service")
    if isinstance(service, Mapping):
        service = _record_name(service)
    if service:
        details["service"] = _text(service)
    for key in ("date", "time", "location"):
        if appointment.get(key) is not None:
            details[key] = _text(appointment[key])
    return details


def _detail_suffix(details: Mapping[str, str]) -> str:
    labels = (
        ("service", "服務"),
        ("date", "日期"),
        ("time", "時間"),
        ("location", "地點"),
    )
    parts = [f"{label}：{details[key]}" for key, label in labels if details.get(key)]
    return "；".join(parts)


def _cash_summary_text(facts: Mapping[str, Any]) -> str:
    plan = _as_mapping(facts.get("plan"))
    # Report the backend statuses verbatim; a completed read-only lookup must
    # never claim registration, adjudication, or payout happened.
    parts = ["我已查到你的現金分享計劃資料，這次只讀查詢已完成。"]
    if plan.get("status") is not None:
        parts.append(f"計劃狀態：{_text(plan['status'])}。")
    eligibility = _as_mapping(plan.get("eligibility"))
    if eligibility.get("status") is not None:
        parts.append(f"資格狀態：{_text(eligibility['status'])}。")
    payout = _as_mapping(plan.get("payout"))
    if payout.get("payment_status") is not None:
        parts.append(f"發放狀態：{_text(payout['payment_status'])}。")
    return "".join(parts)


def _cash_recovery_text(reason: Any) -> str:
    return {
        "backend_unavailable": "暫時未能查詢現金分享計劃，請稍後重試或選擇其他協助。",
        "invalid_backend_response": "現金分享計劃服務的回覆不完整，請重試或選擇其他協助。",
        "human_help_requested": "已記錄你需要人工協助，可隨時取消這次查詢。",
    }.get(_normalised(reason), "暫時未能完成現金分享查詢，請選擇下一步。")


class ResponseComposer:
    """Compose fixed, channel-neutral written and spoken response text."""

    @staticmethod
    def compose(result: CanonicalInteractionResult) -> dict[str, str]:
        intent = _normalised(result.response_intent)
        task = _task(result)
        facts = _facts(result)
        status = _normalised(task.get("status"))
        details = _appointment_details(result)

        if intent == "cash_sharing_summary":
            display_text = _cash_summary_text(facts)
        elif intent == "cash_sharing_recovery":
            recovery = _as_mapping(result.recovery)
            display_text = _cash_recovery_text(recovery.get("reason"))
        elif intent == "appointment_list" or "appointments" in facts:
            display_text = "我已查到你的醫療預約。"
        elif status == "completed" or result.receipt is not None or intent in _COMPLETED_INTENTS:
            display_text = "預約已完成。"
            receipt = _as_mapping(result.receipt)
            if receipt.get("receipt_id"):
                display_text += f"參考編號：{_text(receipt['receipt_id'])}。"
        elif intent in _CANCELLED_INTENTS or status in {"cancelled", "canceled"}:
            display_text = "已取消這次協助，沒有作出更改。"
        elif result.recovery is not None or intent in _RECOVERY_INTENTS or status in {"recovery", "awaiting_recovery"}:
            recovery = _as_mapping(result.recovery)
            message = recovery.get("message") or recovery.get("explanation")
            display_text = _text(message, "暫時未能完成預約，請選擇下一步。")
        elif result.confirmation is not None or status == "awaiting_confirmation" or intent in _CONFIRMATION_INTENTS:
            display_text = "請確認這個時段後再提交預約。"
            suffix = _detail_suffix(details)
            if suffix:
                display_text += f"{suffix}。"
        elif intent in _SLOT_INTENTS or task.get("current_step") in {"select_slot", "slot_selection"} or "slots" in facts:
            slots = _as_list(facts.get("slots"))
            prefix = f"我已查到 {len(slots)} 個可預約時段。" if slots else ""
            display_text = f"{prefix}請選擇一個可預約時段。"
        elif intent in _SERVICE_INTENTS or task.get("current_step") in {"select_service", "service_selection"} or "services" in facts:
            services = _as_list(facts.get("services"))
            prefix = f"我已查到 {len(services)} 項可預約服務。" if services else ""
            display_text = f"{prefix}請選擇你想預約的服務。"
        else:
            display_text = "請選擇下一步。"

        return {
            "display_text": display_text,
            "speech_text": to_cantonese_spoken(display_text),
        }


def _view_for(result: CanonicalInteractionResult) -> str:
    intent = _normalised(result.response_intent)
    task = _task(result)
    facts = _facts(result)
    status = _normalised(task.get("status"))

    if intent == "cash_sharing_summary":
        return "cash_sharing_summary"
    if intent == "cash_sharing_recovery":
        return "cash_sharing_recovery"
    if _normalised(task.get("type")) == "cash_sharing_query":
        return "cash_sharing_recovery" if result.recovery is not None else "cash_sharing_summary"
    if intent == "appointment_list" or "appointments" in facts:
        return "appointment_list"
    if status == "completed" or result.receipt is not None or intent in _COMPLETED_INTENTS:
        return "appointment_completed"
    if result.recovery is not None or status in {"recovery", "awaiting_recovery"} or intent in _RECOVERY_INTENTS:
        return "appointment_recovery"
    if result.confirmation is not None or status == "awaiting_confirmation" or intent in _CONFIRMATION_INTENTS:
        return "appointment_confirmation"
    if intent in _SLOT_INTENTS or task.get("current_step") in {"select_slot", "slot_selection"} or "slots" in facts:
        return "slot_selection"
    if intent in _SERVICE_INTENTS or task.get("current_step") in {"select_service", "service_selection"} or "services" in facts:
        return "service_selection"
    return "appointment_list"


def _field(key: str, label: str, value: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "value": deepcopy(value)}


def _selection_records(value: Any) -> list[Any]:
    records = []
    for item in _as_list(value):
        if isinstance(item, Mapping):
            records.append(deepcopy(dict(item)))
        else:
            records.append(deepcopy(item))
    return records


def _appointment_fields(result: CanonicalInteractionResult) -> list[dict[str, Any]]:
    details = _appointment_details(result)
    labels = (
        ("service", "服務"),
        ("date", "日期"),
        ("time", "時間"),
        ("location", "地點"),
    )
    return [_field(key, label, details[key]) for key, label in labels if details.get(key)]


def _appointment_list_fields(facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate one field per appointment with human-readable label and value."""
    fields: list[dict[str, Any]] = []
    for i, appt in enumerate(_as_list(facts.get("appointments"))):
        if not isinstance(appt, Mapping):
            continue
        # Extract service name
        service = appt.get("service")
        if isinstance(service, Mapping):
            service_name = _record_name(service, fallback="未知服務")
        elif isinstance(service, str):
            service_name = service
        else:
            service_name = "未知服務"
        # Extract date and time from start
        start = _text(appt.get("start"))
        date_part = start[:10] if len(start) >= 10 else start
        time_part = start[11:16] if len(start) >= 16 else ""
        # Extract location
        location = appt.get("location")
        if isinstance(location, Mapping):
            location_name = _record_name(location)
        elif isinstance(location, str):
            location_name = location
        else:
            location_name = ""
        # Extract status
        status = _text(appt.get("status"))
        # Build value string
        value_parts = [date_part, time_part, location_name, status]
        value = " · ".join(filter(None, value_parts))
        fields.append(_field(f"appointment_{i}", service_name, value))
    return fields


def _service_selection_fields(facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate one field per service with human-readable label and value."""
    fields: list[dict[str, Any]] = []
    for i, svc in enumerate(_as_list(facts.get("services"))):
        if not isinstance(svc, Mapping):
            continue
        name = _record_name(svc, fallback="未知服務")
        # Extract duration
        duration = svc.get("duration_minutes")
        duration_text = f"{duration} 分鐘" if duration else ""
        # Build value string (department_id is just an ID, not a displayable object)
        value = duration_text
        fields.append(_field(f"service_{i}", name, value))
    return fields


def _slot_selection_fields(facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate one field per slot with human-readable label and value."""
    fields: list[dict[str, Any]] = []
    for i, slot in enumerate(_as_list(facts.get("slots"))):
        if not isinstance(slot, Mapping):
            continue
        # Extract date and time from start
        start = _text(slot.get("start"))
        date_part = start[:10] if len(start) >= 10 else start
        time_part = start[11:16] if len(start) >= 16 else ""
        label = f"{date_part} {time_part}".strip() if date_part or time_part else "時段"
        # Extract service
        service = slot.get("service")
        if isinstance(service, Mapping):
            service_name = _record_name(service)
        elif isinstance(service, str):
            service_name = service
        else:
            service_name = ""
        # Extract location
        location = slot.get("location")
        if isinstance(location, Mapping):
            location_name = _record_name(location)
        elif isinstance(location, str):
            location_name = location
        else:
            location_name = ""
        # Extract remaining capacity
        remaining = slot.get("remaining")
        remaining_text = f"剩餘 {remaining} 名" if remaining is not None else ""
        # Build value string
        value_parts = [service_name, location_name, remaining_text]
        value = " · ".join(filter(None, value_parts))
        fields.append(_field(f"slot_{i}", label, value))
    return fields


def _cash_summary_fields(facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    plan = _as_mapping(facts.get("plan"))
    fields: list[dict[str, Any]] = []
    if plan.get("plan_name") is not None:
        fields.append(_field("plan_name", "計劃名稱", plan["plan_name"]))
    if plan.get("year") is not None:
        fields.append(_field("year", "年度", plan["year"]))
    if plan.get("status") is not None:
        fields.append(_field("plan_status", "計劃狀態", plan["status"]))
    eligibility = _as_mapping(plan.get("eligibility"))
    if eligibility:
        fields.append(_field("eligibility", "資格狀況", deepcopy(dict(eligibility))))
    payout = _as_mapping(plan.get("payout"))
    if payout.get("amount") is not None:
        fields.append(_field("amount", "金額", payout["amount"]))
    if payout.get("currency") is not None:
        fields.append(_field("currency", "貨幣", payout["currency"]))
    if payout.get("payment_status") is not None:
        fields.append(_field("payment_status", "發放狀態", payout["payment_status"]))
    if payout.get("scheduled_date") is not None:
        fields.append(_field("scheduled_date", "預計發放日期", payout["scheduled_date"]))
    if plan.get("last_updated_at") is not None:
        fields.append(_field("last_updated_at", "最後更新", plan["last_updated_at"]))
    return fields


def _fields_for(result: CanonicalInteractionResult, view: str) -> list[dict[str, Any]]:
    facts = _facts(result)
    if view == "cash_sharing_summary":
        return _cash_summary_fields(facts)
    if view == "cash_sharing_recovery":
        recovery = _as_mapping(result.recovery)
        fields = []
        for key, label in (("reason", "原因"), ("message", "訊息"), ("explanation", "說明")):
            if recovery.get(key) is not None:
                fields.append(_field(key, label, recovery[key]))
        return fields
    if view == "appointment_list":
        return _appointment_list_fields(facts)
    if view == "service_selection":
        return _service_selection_fields(facts)
    if view == "slot_selection":
        return _slot_selection_fields(facts)
    if view == "appointment_confirmation":
        fields = _appointment_fields(result)
        confirmation = _as_mapping(result.confirmation)
        if confirmation.get("confirmation_id"):
            fields.append(_field("confirmation_id", "確認編號", confirmation["confirmation_id"]))
        return fields
    if view == "appointment_recovery":
        recovery = _as_mapping(result.recovery)
        fields = []
        for key, label in (("reason", "原因"), ("reason_code", "原因代碼"), ("message", "訊息"), ("explanation", "說明")):
            if recovery.get(key) is not None:
                fields.append(_field(key, label, recovery[key]))
        return fields
    if view == "appointment_completed":
        fields = _appointment_fields(result)
        receipt = _as_mapping(result.receipt)
        if receipt.get("receipt_id"):
            fields.insert(0, _field("receipt_id", "收據編號", receipt["receipt_id"]))
        if receipt.get("issued_at"):
            fields.append(_field("issued_at", "發出時間", receipt["issued_at"]))
        return fields
    return []


def _action_label(event: Mapping[str, Any]) -> str:
    event_type = _normalised(event.get("type"))
    decision = _normalised(event.get("decision"))
    if event_type == "confirmation_decision":
        return {
            "approve": "確認預約",
            "reject": "取消預約",
            "modify": "修改資料",
        }.get(decision, "處理確認")
    return {
        "service_selected": "選擇服務",
        "slot_selected": "選擇時段",
        "recovery_action": "處理問題",
        "cancel_task": "取消預約",
    }.get(event_type, "繼續")


def _project_actions(result: CanonicalInteractionResult) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for action in _as_list(result.allowed_actions):
        if not isinstance(action, Mapping):
            continue
        action_copy = deepcopy(dict(action))
        event = action.get("event")
        if isinstance(event, Mapping):
            event_copy = deepcopy(dict(event))
        else:
            # Keep the frontend contract stable even if a caller supplies a
            # bare event instead of the normal {label, event} envelope.
            event_copy = deepcopy(dict(action))
            action_copy = {"event": event_copy}
        action_copy["event"] = event_copy
        if not isinstance(action_copy.get("label"), str) or not action_copy["label"].strip():
            action_copy["label"] = _action_label(event_copy)
        projected.append(action_copy)
    return projected


class WorkspaceProjector:
    """Project canonical facts and server-issued actions into workspace data."""

    @staticmethod
    def project(result: CanonicalInteractionResult) -> dict[str, Any]:
        view = _view_for(result)
        return {
            "view": view,
            "title": _VIEW_TITLES[view],
            "fields": _fields_for(result, view),
            "actions": _project_actions(result),
            "artifact": deepcopy(dict(result.receipt)) if isinstance(result.receipt, Mapping) else None,
        }


def _speech_metadata(audio: Any) -> dict[str, Any]:
    if isinstance(audio, Mapping):
        metadata = deepcopy(dict(audio))
        metadata["status"] = metadata.get("status") or "ready"
        metadata.pop("content", None)
        return metadata
    content = getattr(audio, "content", None)
    content_type = getattr(audio, "content_type", None)
    metadata: dict[str, Any] = {"status": "ready"}
    if isinstance(content_type, str) and content_type:
        metadata["content_type"] = content_type
    if isinstance(content, (bytes, bytearray, memoryview)):
        metadata["byte_length"] = len(content)
    return metadata


class DeliveryOrchestrator:
    """Combine deterministic projections and isolate optional TTS failures."""

    @staticmethod
    def deliver(
        result: CanonicalInteractionResult,
        speech_adapter: Any | None = None,
        speech_settings: Any | None = None,
    ) -> dict[str, Any]:
        response = ResponseComposer.compose(result)
        workspace = WorkspaceProjector.project(result)
        speech_audio: dict[str, Any] = {"status": "unavailable"}

        if speech_adapter is not None:
            try:
                audio = speech_adapter.synthesize(response["speech_text"], speech_settings)
            except Exception:
                audio = None
            if audio is not None:
                speech_audio = _speech_metadata(audio)

        return {
            "interaction_id": _text(result.interaction_id),
            "task": deepcopy(dict(result.task)) if isinstance(result.task, Mapping) else {},
            "response": response,
            "workspace": workspace,
            "confirmation": deepcopy(dict(result.confirmation)) if isinstance(result.confirmation, Mapping) else None,
            "recovery": deepcopy(dict(result.recovery)) if isinstance(result.recovery, Mapping) else None,
            "receipt": deepcopy(dict(result.receipt)) if isinstance(result.receipt, Mapping) else None,
            "speech_audio": speech_audio,
        }
