"""API-key OpenAI-compatible chat backend."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from starlette.exceptions import HTTPException

from fdai.core.metering.emitter import MeteringEmitter
from fdai.delivery.operator_api.routes.chat_backend_common import (
    _completion_body_params,
    _default_chat_http_client,
    _metering_scope,
    _raise_if_content_filtered,
    _raise_upstream_error,
    _structured_completion_body,
    _structured_content,
    _structured_result,
    _token_usage,
    _usage_summary,
)
from fdai.delivery.operator_api.routes.chat_model_trace import (
    begin_model_call,
    complete_model_call,
)
from fdai.delivery.operator_api.routes.chat_prompt import _build_messages

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OpenAiCompatibleChatBackendConfig:
    """Endpoint + auth binding for the OpenAI-compatible chat backend."""

    provider: str  # "openai" or "azure"
    base_url: str
    api_key: str
    model: str  # deployment name for provider=azure
    api_version: str = "2024-08-01-preview"
    temperature: float = 0.2
    max_tokens: int = 2048
    # 90s accommodates reasoning models (gpt-5, o1/o3/o4) that can take
    # 60-90s to emit the first token. The SSE route layers a heartbeat on
    # top so HTTP intermediaries do not drop an idle connection.
    timeout_seconds: float = 90.0


class OpenAiCompatibleChatBackend:
    """Chat backend that proxies to any OpenAI-compatible chat/completions.

    Auth is API-key only (``Authorization: Bearer`` for OpenAI,
    ``api-key`` header for Azure). Keyless (managed-identity) auth is
    intentionally deferred to a future revision to keep the console
    slice small; a fork that needs it can inject its own backend.
    """

    def __init__(
        self,
        *,
        config: OpenAiCompatibleChatBackendConfig,
        http_client: httpx.AsyncClient | None = None,
        metering: MeteringEmitter | None = None,
    ) -> None:
        if config.provider not in {"openai", "azure"}:
            raise ValueError("provider MUST be 'openai' or 'azure'")
        if not config.base_url.startswith(("https://", "http://")):
            raise ValueError("base_url MUST be an absolute URL")
        if not config.api_key:
            raise ValueError("api_key MUST NOT be empty")
        if not config.model:
            raise ValueError("model MUST NOT be empty")
        self._config = config
        self._http = http_client if http_client is not None else _default_chat_http_client()
        self._metering = metering

    def _url(self) -> str:
        base = self._config.base_url.rstrip("/")
        if self._config.provider == "azure":
            return f"{base}/openai/deployments/{self._config.model}/chat/completions"
        return f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._config.provider == "azure":
            h["api-key"] = self._config.api_key
        else:
            h["Authorization"] = f"Bearer {self._config.api_key}"
        return h

    def _params(self) -> dict[str, str]:
        if self._config.provider == "azure":
            return {"api-version": self._config.api_version}
        return {}

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        messages = _build_messages(prompt, view_context, history)
        trace_call = begin_model_call(
            kind="answer",
            model=self._config.model,
            messages=messages,
        )

        body: dict[str, Any] = {
            "messages": messages,
            **_completion_body_params(
                self._config.model,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
            ),
        }
        if self._config.provider == "openai":
            body["model"] = self._config.model

        try:
            response = await self._http.post(
                self._url(),
                params=self._params(),
                headers=self._headers(),
                json=body,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            _LOG.warning("chat backend HTTP error: %s", exc)
            raise HTTPException(status_code=502, detail="chat upstream unreachable") from exc
        if response.status_code >= 400:
            _raise_upstream_error(response.status_code, response.text)
        try:
            envelope = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="chat upstream returned non-JSON") from exc
        _raise_if_content_filtered(envelope)

        choices = envelope.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HTTPException(status_code=502, detail="chat upstream returned no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise HTTPException(status_code=502, detail="chat upstream returned no content")
        reply: dict[str, Any] = {"answer": content.strip(), "model": self._config.model}
        usage = _usage_summary(envelope.get("usage"))
        if usage is not None:
            reply["usage"] = usage
        complete_model_call(trace_call, response_content=content, usage=usage)
        measured_usage = _token_usage(usage)
        if measured_usage is not None and self._metering is not None:
            await self._metering.emit_safe(measured_usage, usage_scope=_metering_scope())
        return reply

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_content: str | list[dict[str, object]],
        schema_name: str,
        schema: Mapping[str, object],
        max_tokens: int,
    ) -> Mapping[str, object]:
        """Return one strict JSON-schema completion from the configured model."""

        body = _structured_completion_body(
            model=self._config.model,
            system_prompt=system_prompt,
            user_content=user_content,
            schema_name=schema_name,
            schema=schema,
            max_tokens=max_tokens,
        )
        trace_call = begin_model_call(
            kind=f"structured:{schema_name}",
            model=self._config.model,
            messages=body["messages"],
        )
        if self._config.provider == "openai":
            body["model"] = self._config.model
        try:
            response = await self._http.post(
                self._url(),
                params=self._params(),
                headers=self._headers(),
                json=body,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            _LOG.warning("chat structured completion HTTP error: %s", exc)
            raise HTTPException(status_code=502, detail="chat upstream unreachable") from exc
        if response.status_code >= 400:
            _raise_upstream_error(response.status_code, response.text)
        try:
            envelope = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="chat upstream returned non-JSON") from exc
        _raise_if_content_filtered(envelope)
        result = _structured_result(envelope)
        complete_model_call(
            trace_call,
            response_content=_structured_content(envelope),
            usage=_usage_summary(envelope.get("usage")),
        )
        return result
