"""Small OpenAI-compatible chat transport shared by agent components."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


class ChatCompletionError(RuntimeError):
    """Raised when an OpenAI-compatible completion cannot be obtained."""


class ChatCompletionClient(Protocol):
    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        **options: Any,
    ) -> Mapping[str, Any]:
        ...


class OpenAICompatibleChatClient:
    """Send chat-completions payloads using the middleware's stdlib transport shape."""

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
        self.timeout = float(timeout)
        self._transport = transport or self._request_json

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        **options: Any,
    ) -> Mapping[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
        }
        body.update(options)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            self.api_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            response = self._transport(request, self.timeout)
        except ChatCompletionError:
            raise
        except Exception as error:
            raise ChatCompletionError("LLM completion request failed") from error
        if not isinstance(response, Mapping):
            raise ChatCompletionError("LLM completion response must be an object")
        return response

    @staticmethod
    def _request_json(request: Request, timeout: float) -> Mapping[str, Any]:
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read()
        except (HTTPError, URLError, OSError) as error:
            raise ChatCompletionError("LLM completion request failed") from error
        try:
            decoded = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as error:
            raise ChatCompletionError("LLM completion response is not JSON") from error
        if not isinstance(decoded, Mapping):
            raise ChatCompletionError("LLM completion response must be an object")
        return decoded


def assistant_message(response: Mapping[str, Any]) -> Mapping[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ChatCompletionError("LLM completion must contain exactly one choice")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise ChatCompletionError("LLM completion choice must be an object")
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ChatCompletionError("LLM completion choice has no message")
    return message


def strict_json_content(response: Mapping[str, Any]) -> Mapping[str, Any]:
    message = assistant_message(response)
    content = message.get("content")
    if not isinstance(content, str):
        raise ChatCompletionError("LLM completion content must be a string")
    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        raise ChatCompletionError("LLM completion content must be strict JSON") from error
    if not isinstance(value, Mapping):
        raise ChatCompletionError("LLM completion JSON must be an object")
    return value
