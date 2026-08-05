"""Independent interpreter boundary for backend-result recovery guidance."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from ponte_logging import endpoint_label, log_debug_event, log_event

from .contracts import RecoveryPlan


_ALLOWED_ACTIONS = frozenset({"retry", "search_slots", "select_slot", "cancel", "human_help"})
_ALLOWED_FIELD_NAMES = frozenset({
    "contact_phone",
    "identity_document",
    "department_id",
    "service_id",
    "slot_id",
})
_NO_RESPONSE = object()


class TaskRecoveryInterpreter(Protocol):
    """Understand a sanitized backend result and return a validated recovery plan."""

    def interpret(
        self,
        *,
        error: Mapping[str, Any] | None,
        step_id: str,
        workflow: str,
        data: Mapping[str, Any],
        fallback: RecoveryPlan | None,
    ) -> RecoveryPlan | None:
        ...


class DeterministicTaskRecoveryInterpreter:
    """Default recovery interpreter used when no separate LLM client is configured."""

    source = "deterministic_fallback"

    def interpret(
        self,
        *,
        error: Mapping[str, Any] | None,
        step_id: str,
        workflow: str,
        data: Mapping[str, Any],
        fallback: RecoveryPlan | None,
    ) -> RecoveryPlan | None:
        del error, step_id, workflow, data
        return fallback


class LlmTaskRecoveryInterpreter:
    """Call a separate OpenAI-compatible endpoint for recovery interpretation."""

    source = "task_recovery_llm"

    def __init__(
        self,
        api_url: str,
        *,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        timeout: float = 8.0,
        transport: Any | None = None,
    ) -> None:
        if not isinstance(api_url, str) or not api_url.strip():
            raise ValueError("api_url must be a non-empty string")
        if not api_url.startswith(("http://", "https://")):
            raise ValueError("api_url must use http:// or https://")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_url = api_url.strip()
        self.api_key = api_key
        self.model = model.strip()
        self.timeout = timeout
        self._transport = transport or self._request_json

    def interpret(
        self,
        *,
        error: Mapping[str, Any] | None,
        step_id: str,
        workflow: str,
        data: Mapping[str, Any],
        fallback: RecoveryPlan | None,
    ) -> RecoveryPlan | None:
        del fallback
        request_id = f"LLM-REC-{uuid.uuid4().hex[:12].upper()}"
        started_at = time.monotonic()
        safe_error = _safe_error(error)
        safe_data = _safe_data(data)
        request_body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 Ponte 的 Task Recovery LLM，不是 intent classifier。"
                        "只理解已清理的 backend/tool error 和 workflow context，"
                        "並只返回一個 JSON object："
                        '{"category":"...","reason_code":"...","explanation":"...",'
                        '"required_fields":[],"options":[{"action":"...",'
                        '"label":"...","payload":{}}]}。'
                        "可用 action 只有 retry、search_slots、select_slot、cancel、human_help；"
                        "不可執行 tool、不可改變 workflow state、不可辨識 intent。"
                        "不要輸出 backend 原始訊息、request id、病人身份或未提供的資料。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "step_id": step_id,
                        "workflow": workflow,
                        "error": safe_error,
                        "data": safe_data,
                    }, ensure_ascii=False, separators=(",", ":")),
                },
            ],
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            self.api_url,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        log_event(
            "llm",
            "send",
            request_id=request_id,
            operation="task_recovery",
            model=self.model,
            endpoint=endpoint_label(self.api_url),
            message_count=len(request_body["messages"]),
            message_chars=sum(len(message["content"]) for message in request_body["messages"]),
        )
        log_debug_event(
            "llm",
            "send_debug",
            request_id=request_id,
            operation="task_recovery",
            model=self.model,
            endpoint=endpoint_label(self.api_url),
            prompt=request_body["messages"],
        )
        response: object = _NO_RESPONSE
        receive_debug_logged = False
        try:
            response = self._transport(request, self.timeout)
            plan = _parse_plan_response(response, safe_error)
            latency_ms = round((time.monotonic() - started_at) * 1000)
            log_debug_event(
                "llm",
                "receive_debug",
                request_id=request_id,
                operation="task_recovery",
                response=response,
                outcome="success" if plan is not None else "invalid_plan",
                latency_ms=latency_ms,
            )
            receive_debug_logged = True
            log_event(
                "llm",
                "receive",
                request_id=request_id,
                operation="task_recovery",
                model=self.model,
                outcome="success" if plan is not None else "invalid_plan",
                error_code=safe_error.get("code"),
                latency_ms=latency_ms,
            )
            return plan
        except Exception as error:
            if not receive_debug_logged:
                log_debug_event(
                    "llm",
                    "receive_debug",
                    request_id=request_id,
                    operation="task_recovery",
                    response_unavailable=response is _NO_RESPONSE,
                    outcome="error",
                    error_type=type(error).__name__,
                    latency_ms=round((time.monotonic() - started_at) * 1000),
                )
            log_event(
                "llm",
                "error",
                request_id=request_id,
                operation="task_recovery",
                model=self.model,
                outcome="error",
                error_code="llm_task_recovery_error",
                error_type=type(error).__name__,
                latency_ms=round((time.monotonic() - started_at) * 1000),
            )
            return None

    def _request_json(self, request: Request, timeout: float) -> Mapping[str, Any]:
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as error:
            raise RuntimeError(f"task recovery HTTP {error.code}") from error
        except (URLError, OSError) as error:
            raise RuntimeError("task recovery endpoint unavailable") from error
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("task recovery endpoint returned invalid JSON") from error
        if not isinstance(value, Mapping):
            raise RuntimeError("task recovery endpoint returned a non-object")
        return value


def build_task_recovery_interpreter() -> TaskRecoveryInterpreter:
    """Build the independent recovery interpreter from its own environment keys."""

    api_url = os.environ.get("PONTE_TASK_RECOVERY_LLM_API_URL", "").strip()
    if not api_url:
        return DeterministicTaskRecoveryInterpreter()
    return LlmTaskRecoveryInterpreter(
        api_url,
        api_key=os.environ.get("PONTE_TASK_RECOVERY_LLM_API_KEY", ""),
        model=os.environ.get("PONTE_TASK_RECOVERY_LLM_MODEL", "gpt-4o-mini"),
    )


def _safe_error(error: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(error, Mapping):
        return {}
    result: dict[str, Any] = {
        "code": error.get("code"),
        "retryable": bool(error.get("retryable", False)),
    }
    if isinstance(error.get("status"), int):
        result["status"] = error["status"]
    details = error.get("details")
    if isinstance(details, Mapping):
        safe_details: dict[str, Any] = {}
        for key in ("field", "fields", "alternatives", "available_slots"):
            if key in details:
                safe_details[key] = details[key]
        if safe_details:
            result["details"] = safe_details
    return result


def _safe_data(data: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        return {}
    allowed = {"service_id", "date_from", "date_to", "doctor_id", "location_id"}
    result = {key: value for key, value in data.items() if key in allowed}
    services = data.get("services")
    if isinstance(services, list):
        result["services"] = _safe_services(services)
    return result


def _safe_services(value: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for service in value:
        if not isinstance(service, Mapping):
            continue
        service_id = service.get("id")
        if not isinstance(service_id, str) or not service_id.strip():
            continue
        safe_service: dict[str, Any] = {"id": service_id.strip()}
        for key in ("name", "name_en"):
            label = service.get(key)
            if isinstance(label, str) and label.strip():
                safe_service[key] = label.strip()
        if service.get("active") is False:
            safe_service["active"] = False
        result.append(safe_service)
    return result


def _parse_plan_response(response: object, error: Mapping[str, Any]) -> RecoveryPlan | None:
    value: Any = response
    if isinstance(response, Mapping) and "recovery" in response:
        value = response["recovery"]
    elif isinstance(response, Mapping) and "choices" in response:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            return None
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str):
            return None
        try:
            value = json.loads(_strip_json_fence(content))
        except json.JSONDecodeError:
            return None
    if not isinstance(value, Mapping):
        return None

    category = value.get("category")
    reason_code = value.get("reason_code")
    explanation = value.get("explanation")
    expected_code = error.get("code")
    if not all(isinstance(item, str) and item.strip() for item in (category, reason_code, explanation)):
        return None
    if isinstance(expected_code, str) and reason_code.strip().upper() != expected_code.strip().upper():
        return None

    fields: list[Any] = []
    raw_fields = value.get("required_fields", [])
    if not isinstance(raw_fields, list):
        return None
    for raw_field in raw_fields:
        if not isinstance(raw_field, Mapping):
            return None
        name = raw_field.get("name")
        label = raw_field.get("label")
        if not isinstance(name, str) or name not in _ALLOWED_FIELD_NAMES or not isinstance(label, str) or not label.strip():
            return None
        from .contracts import RecoveryField

        fields.append(RecoveryField(
            name=name,
            label=label,
            input_type=raw_field.get("input_type", "text"),
            reason=raw_field.get("reason", ""),
        ))

    options: list[Any] = []
    raw_options = value.get("options", [])
    if not isinstance(raw_options, list):
        return None
    for raw_option in raw_options:
        if not isinstance(raw_option, Mapping):
            return None
        action = raw_option.get("action")
        label = raw_option.get("label")
        payload = raw_option.get("payload", {})
        if action not in _ALLOWED_ACTIONS or not isinstance(label, str) or not label.strip() or not isinstance(payload, Mapping):
            return None
        safe_payload = _safe_option_payload(action, payload)
        if safe_payload is None:
            return None
        from .contracts import RecoveryOption

        options.append(RecoveryOption(action, label, safe_payload))
    if not options:
        return None
    return RecoveryPlan(
        category=category,
        reason_code=reason_code,
        explanation=explanation,
        required_fields=tuple(fields),
        options=tuple(options),
    )


def _safe_option_payload(action: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    if action in {"retry", "cancel", "human_help"}:
        return {} if not payload else None
    if action == "select_slot":
        slot_id = payload.get("slot_id")
        return {"slot_id": slot_id} if isinstance(slot_id, str) and slot_id.strip() else None
    if action == "search_slots":
        allowed = {"service_id", "date_from", "date_to", "doctor_id", "location_id"}
        if any(key not in allowed for key in payload):
            return None
        required = {key: payload.get(key) for key in ("service_id", "date_from", "date_to")}
        if not all(isinstance(value, str) and value.strip() for value in required.values()):
            return None
        return {key: str(value).strip() for key, value in payload.items() if isinstance(value, str) and value.strip()}
    return None


def _strip_json_fence(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    return cleaned
