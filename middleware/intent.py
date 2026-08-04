"""Intent recognition contracts and the LLM/keyword hybrid implementation."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


IntentName = Literal[
    "medical_appointment",
    "cash_sharing",
    "elderly_activity",
    "general",
]
IntentSource = Literal["keyword", "llm"]


@dataclass(frozen=True)
class IntentDecision:
    """Normalized intent output consumed by the interaction controller."""

    intent: IntentName
    source: IntentSource
    confidence: float | None = None
    matched_term: str | None = None

    @property
    def is_medical(self) -> bool:
        return self.intent == "medical_appointment"

    @property
    def is_cash_sharing(self) -> bool:
        return self.intent == "cash_sharing"

    @property
    def is_elderly_activity(self) -> bool:
        return self.intent == "elderly_activity"


class IntentRecognitionError(RuntimeError):
    """Raised when an LLM response cannot be used as an intent decision."""


class IntentRecognizer(ABC):
    """Abstract intent recognition interface."""

    @abstractmethod
    def recognize(self, message: str) -> IntentDecision:
        """Return a normalized decision for one user message."""


class KeywordIntentRecognizer(IntentRecognizer):
    """Deterministic fallback for the supported domain intent groups."""

    DEFAULT_CASH_SHARING_TERMS = ("現金分享", "現金分享計劃")
    DEFAULT_ELDERLY_ACTIVITY_TERMS = ("長者活動", "文娛活動", "興趣班")
    DEFAULT_MEDICAL_TERMS = ("醫療", "預約", "覆診", "睇醫生", "改期")

    def __init__(
        self,
        medical_terms: tuple[str, ...] | None = None,
        cash_sharing_terms: tuple[str, ...] | None = None,
        elderly_activity_terms: tuple[str, ...] | None = None,
    ) -> None:
        self.cash_sharing_terms = cash_sharing_terms or self.DEFAULT_CASH_SHARING_TERMS
        self.elderly_activity_terms = elderly_activity_terms or self.DEFAULT_ELDERLY_ACTIVITY_TERMS
        self.medical_terms = medical_terms or self.DEFAULT_MEDICAL_TERMS

    def recognize(self, message: str) -> IntentDecision:
        if not isinstance(message, str):
            raise ValueError("message must be a string")
        for term in self.cash_sharing_terms:
            if term in message:
                return IntentDecision("cash_sharing", "keyword", 1.0, term)
        for term in self.elderly_activity_terms:
            if term in message:
                return IntentDecision("elderly_activity", "keyword", 1.0, term)
        for term in self.medical_terms:
            if term in message:
                return IntentDecision("medical_appointment", "keyword", 1.0, term)
        return IntentDecision("general", "keyword", 1.0)


class LlmIntentRecognizer(IntentRecognizer):
    """Call an OpenAI-compatible JSON chat-completions endpoint via stdlib HTTP."""

    def __init__(
        self,
        api_url: str,
        *,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        timeout: float = 8.0,
        transport: Callable[[Request, float], Mapping[str, Any]] | None = None,
    ) -> None:
        if not isinstance(api_url, str) or not api_url.strip():
            raise ValueError("api_url must be a non-empty string")
        if not api_url.startswith(("http://", "https://")):
            raise ValueError("api_url must use http:// or https://")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        self.api_url = api_url.strip()
        self.api_key = api_key
        self.model = model.strip()
        self.timeout = timeout
        self._transport = transport or self._request_json

    def recognize(self, message: str) -> IntentDecision:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        request_body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 Ponte 的 intent classifier。只能返回 JSON object，格式為 "
                        '{"intent":"medical_appointment"、"cash_sharing"、"elderly_activity"或"general",'
                        '"confidence":0到1}。'
                        "cash_sharing 包括現金分享或現金分享計劃；"
                        "elderly_activity 包括長者活動、文娛活動或興趣班；"
                        "medical_appointment 包括醫療、預約、覆診、睇醫生或改期；"
                        "其他內容使用 general。"
                    ),
                },
                {"role": "user", "content": message},
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
        try:
            response = self._transport(request, self.timeout)
            return self._parse_response(response)
        except IntentRecognitionError:
            raise
        except Exception as error:
            raise IntentRecognitionError("LLM intent request failed") from error

    def _request_json(self, request: Request, timeout: float) -> Mapping[str, Any]:
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IntentRecognitionError("LLM intent request failed") from error
        if not isinstance(value, Mapping):
            raise IntentRecognitionError("LLM response must be a JSON object")
        return value

    @classmethod
    def _parse_response(cls, response: Mapping[str, Any]) -> IntentDecision:
        if "intent" in response:
            value: Any = response
        else:
            choices = response.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
                raise IntentRecognitionError("LLM response has no choices")
            message = choices[0].get("message")
            content = message.get("content") if isinstance(message, Mapping) else None
            if not isinstance(content, str):
                raise IntentRecognitionError("LLM response content must be a string")
            value = cls._parse_content(content)
        if not isinstance(value, Mapping):
            raise IntentRecognitionError("LLM intent payload must be an object")
        intent = cls._normalize_intent(value.get("intent"))
        confidence = value.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise IntentRecognitionError("LLM confidence must be numeric")
            confidence = max(0.0, min(1.0, float(confidence)))
        return IntentDecision(intent, "llm", confidence)

    @staticmethod
    def _parse_content(content: str) -> Mapping[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned[3:-3].strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError as error:
            raise IntentRecognitionError("LLM response content is not valid JSON") from error
        if not isinstance(value, Mapping):
            raise IntentRecognitionError("LLM response content must be a JSON object")
        return value

    @staticmethod
    def _normalize_intent(value: Any) -> IntentName:
        if not isinstance(value, str):
            raise IntentRecognitionError("LLM intent must be a string")
        normalized = value.strip().casefold()
        if normalized in {"medical", "medical_appointment", "appointment", "booking"}:
            return "medical_appointment"
        if normalized in {"cash", "cash_sharing"}:
            return "cash_sharing"
        if normalized in {"activity", "elderly_activity"}:
            return "elderly_activity"
        if normalized in {"general", "other", "unknown", "none"}:
            return "general"
        raise IntentRecognitionError("LLM returned an unsupported intent")


class HybridIntentRecognizer(IntentRecognizer):
    """Use LLM recognition when configured and keyword recognition as fallback."""

    def __init__(
        self,
        llm: IntentRecognizer | None = None,
        fallback: IntentRecognizer | None = None,
    ) -> None:
        self.llm = llm
        self.fallback = fallback or KeywordIntentRecognizer()

    def recognize(self, message: str) -> IntentDecision:
        if self.llm is not None:
            try:
                return self.llm.recognize(message)
            except IntentRecognitionError:
                pass
        return self.fallback.recognize(message)


def build_intent_recognizer() -> IntentRecognizer:
    """Build the default recognizer from environment configuration."""

    api_url = os.environ.get("PONTE_LLM_API_URL", "").strip()
    llm = None
    if api_url:
        llm = LlmIntentRecognizer(
            api_url,
            api_key=os.environ.get("PONTE_LLM_API_KEY", ""),
            model=os.environ.get("PONTE_LLM_MODEL", "gpt-4o-mini"),
        )
    return HybridIntentRecognizer(llm=llm)
