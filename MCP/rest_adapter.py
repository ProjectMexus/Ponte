"""Controlled REST transport for the documented Ponte mock APIs."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from .errors import (
    AdapterError,
    BackendInvalidResponse,
    BackendTimeout,
    BackendUnavailable,
    InvalidToolArguments,
)
from .models import RestRequest, ToolContext
from .registry import ToolDefinition


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: Any = None


class HttpTransport(Protocol):
    def request(self, request: RestRequest, timeout: float) -> HttpResponse:
        ...


class UrllibTransport:
    """HTTP transport using only Python's standard library."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        # Mock backends are addressed directly; environment proxies must not
        # intercept local fixture or Ponte backend requests.
        self.opener = build_opener(ProxyHandler({}))

    def request(self, request: RestRequest, timeout: float) -> HttpResponse:
        query = urlencode(list(request.query.items()))
        url = f"{self.base_url}{request.path}"
        if query:
            url = f"{url}?{query}"
        headers = {"Accept": "application/json", **dict(request.headers)}
        data: bytes | None = None
        if request.body is not None:
            headers.setdefault("Content-Type", "application/json")
            data = json.dumps(request.body, ensure_ascii=False).encode("utf-8")
        http_request = Request(url, data=data, headers=headers, method=request.method)
        try:
            with self.opener.open(http_request, timeout=timeout) as response:
                return HttpResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=self._decode_json(response.read()),
                )
        except HTTPError as error:
            raw_body = error.read()
            try:
                body = self._decode_json(raw_body)
            except BackendInvalidResponse:
                body = {"error": {"code": "HTTP_ERROR", "message": str(error)}}
            return HttpResponse(status=error.code, headers=dict(error.headers.items()), body=body)
        except (TimeoutError, socket.timeout) as error:
            raise BackendTimeout(details={"reason": str(error)}) from error
        except URLError as error:
            reason = error.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise BackendTimeout(details={"reason": str(reason)}) from error
            raise BackendUnavailable(details={"reason": str(reason)}) from error
        except OSError as error:
            raise BackendUnavailable(details={"reason": str(error)}) from error

    @staticmethod
    def _decode_json(raw: bytes) -> Any:
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BackendInvalidResponse(details={"reason": str(error)}) from error


class RestAdapter:
    """Map a registry definition and MCP envelope to one REST request."""

    def __init__(self, base_url: str, transport: HttpTransport | None = None, timeout: float = 10.0):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("backend base URL must use http:// or https://")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or UrllibTransport(self.base_url)

    @classmethod
    def from_environment(cls, *, timeout: float = 10.0) -> "RestAdapter":
        return cls(os.environ.get("PONTE_BACKEND_URL", "http://127.0.0.1:8080"), timeout=timeout)

    def invoke(self, definition: ToolDefinition, arguments: Mapping[str, Any]) -> dict[str, Any]:
        context = ToolContext.from_arguments(arguments)
        self._validate_required_input(definition, context.input)
        try:
            path = definition.path_for(context.input)
        except ValueError as error:
            raise InvalidToolArguments(str(error)) from error

        query: dict[str, str] = {}
        for key in definition.query_fields:
            if key in context.input and context.input[key] is not None:
                query[key] = self._serialize_query_value(context.input[key])

        body = dict(context.input) if definition.body_mode == "json" else None
        request = RestRequest(
            method=definition.method,
            path=path,
            query=query,
            body=body,
            headers=context.to_headers(definition.context_requirements, method=definition.method),
        )
        response = self.transport.request(request, self.timeout)
        if 200 <= response.status < 300:
            if not isinstance(response.body, dict):
                raise BackendInvalidResponse(status=response.status, details={"body_type": type(response.body).__name__})
            return response.body
        raise self._backend_error(response)

    @staticmethod
    def _validate_required_input(definition: ToolDefinition, input_data: Mapping[str, Any]) -> None:
        input_schema = definition.input_schema["properties"]["input"]
        for field_name in input_schema.get("required", ()):
            if field_name not in input_data:
                raise InvalidToolArguments(
                    f"Missing required input field: {field_name}",
                    details={"field": f"input.{field_name}"},
                )

    @staticmethod
    def _serialize_query_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, tuple)):
            return ",".join(str(item) for item in value)
        return str(value)

    @staticmethod
    def _backend_error(response: HttpResponse) -> AdapterError:
        body = response.body if isinstance(response.body, dict) else {}
        error = body.get("error") if isinstance(body.get("error"), dict) else body
        code = error.get("code", "BACKEND_HTTP_ERROR")
        message = error.get("message", f"Backend returned HTTP {response.status}")
        retryable = bool(error.get("retryable", response.status >= 500))
        return AdapterError(
            code=code,
            message=message,
            status=response.status,
            details=error,
            retryable=retryable,
        )
