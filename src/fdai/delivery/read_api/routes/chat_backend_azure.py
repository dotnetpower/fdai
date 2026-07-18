"""Workload-identity Azure chat backend."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from starlette.exceptions import HTTPException

from fdai.core.metering.emitter import MeteringEmitter
from fdai.delivery.azure.llm.request_target import (
    COGNITIVE_SERVICES_SCOPE,
    ModelRequestTarget,
)
from fdai.delivery.read_api.routes.chat_backend_common import (
    _completion_body_params,
    _default_chat_http_client,
    _metering_scope,
    _raise_upstream_error,
    _token_usage,
    _usage_summary,
)
from fdai.delivery.read_api.routes.chat_prompt import _build_messages
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOG = logging.getLogger(__name__)


class AzureAdChatBackend:
    """Chat backend that authenticates to Azure OpenAI with workload identity.

    Production injects the Container App's managed identity. Local development
    falls back to the current ``az login`` session when no identity is injected.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        api_version: str = "2024-08-01-preview",
        temperature: float = 0.2,
        max_tokens: int = 2048,
        # 90s: reasoning models (gpt-5, o1/o3/o4) can take 60-90s to first
        # token; the SSE route layers a heartbeat on top for intermediaries.
        timeout_seconds: float = 90.0,
        api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI,
        auth_audience: str = COGNITIVE_SERVICES_SCOPE,
        http_client: httpx.AsyncClient | None = None,
        identity: WorkloadIdentity | None = None,
        metering: MeteringEmitter | None = None,
    ) -> None:
        target = ModelRequestTarget(
            endpoint=endpoint,
            deployment=deployment,
            api_style=api_style,
            api_version=api_version,
            auth_audience=auth_audience,
        )
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._api_version = api_version
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._http = http_client if http_client is not None else _default_chat_http_client()
        self._workload_identity = identity
        self._target = target
        self._metering = metering
        # Lazy identity - defer import so this module stays importable
        # in tests that never touch Azure.
        self._identity_cached: Any = None

    def _identity(self) -> Any:
        if self._identity_cached is None:
            from fdai.delivery.azure.dev_workload_identity import AzureCliWorkloadIdentity

            self._identity_cached = AzureCliWorkloadIdentity()
        return self._identity_cached

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        import asyncio

        try:
            token = (
                await self._workload_identity.get_token(self._target.auth_audience)
                if self._workload_identity is not None
                else await asyncio.to_thread(
                    self._identity().get_token_sync,
                    self._target.auth_audience,
                )
            )
        except Exception as exc:
            _LOG.warning("chat backend workload identity failed: %s", exc)
            raise HTTPException(status_code=502, detail="chat auth failed") from exc

        messages = _build_messages(prompt, view_context, history)

        body: dict[str, Any] = {
            "messages": messages,
            **_completion_body_params(
                self._deployment,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            ),
        }
        request = self._target.operation("chat/completions")
        if request.model_body_field is not None:
            body["model"] = request.model_body_field
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
        }
        try:
            response = await self._http.post(
                request.url,
                params=request.params,
                headers=headers,
                json=body,
                timeout=self._timeout,
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
        choices = envelope.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HTTPException(status_code=502, detail="chat upstream returned no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise HTTPException(status_code=502, detail="chat upstream returned no content")
        reply: dict[str, Any] = {"answer": content.strip(), "model": self._deployment}
        usage = _usage_summary(envelope.get("usage"))
        if usage is not None:
            reply["usage"] = usage
        measured_usage = _token_usage(usage)
        if measured_usage is not None and self._metering is not None:
            await self._metering.emit_safe(measured_usage, usage_scope=_metering_scope())
        return reply

    async def answer_stream(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream the answer token by token via Azure OpenAI ``stream=true``.

        Yields ``{"type": "token", "delta": str}`` per content chunk, then a
        terminal ``{"type": "done", "answer": str, "model": str}``. Auth /
        body building mirror :meth:`answer`; only the transport differs.
        Read-only - no state mutation, no privileged call.
        """
        import asyncio

        try:
            token = (
                await self._workload_identity.get_token(self._target.auth_audience)
                if self._workload_identity is not None
                else await asyncio.to_thread(
                    self._identity().get_token_sync,
                    self._target.auth_audience,
                )
            )
        except Exception as exc:
            _LOG.warning("chat backend workload identity failed: %s", exc)
            raise HTTPException(status_code=502, detail="chat auth failed") from exc

        messages = _build_messages(prompt, view_context, history)

        body: dict[str, Any] = {
            "messages": messages,
            "stream": True,
            # Ask Azure OpenAI for a terminal usage chunk (empty choices +
            # ``usage``) so the deck can show tokens spent per reply.
            "stream_options": {"include_usage": True},
            **_completion_body_params(
                self._deployment,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            ),
        }
        request = self._target.operation("chat/completions")
        if request.model_body_field is not None:
            body["model"] = request.model_body_field
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
        }
        collected: list[str] = []
        stream_usage: dict[str, int] | None = None
        try:
            async with self._http.stream(
                "POST",
                request.url,
                params=request.params,
                headers=headers,
                json=body,
                timeout=self._timeout,
            ) as response:
                if response.status_code >= 400:
                    err_body = (await response.aread()).decode("utf-8", "replace")
                    _raise_upstream_error(response.status_code, err_body)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        continue
                    maybe_usage = (
                        _usage_summary(obj.get("usage")) if isinstance(obj, dict) else None
                    )
                    if maybe_usage is not None:
                        stream_usage = maybe_usage
                    choices = obj.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                    piece = delta.get("content") if isinstance(delta, dict) else None
                    if isinstance(piece, str) and piece:
                        collected.append(piece)
                        yield {"type": "token", "delta": piece}
        except httpx.HTTPError as exc:
            _LOG.warning("chat stream HTTP error: %s", exc)
            raise HTTPException(status_code=502, detail="chat upstream unreachable") from exc
        done: dict[str, Any] = {
            "type": "done",
            "answer": "".join(collected).strip(),
            "model": self._deployment,
        }
        if stream_usage is not None:
            done["usage"] = stream_usage
        measured_usage = _token_usage(stream_usage)
        if measured_usage is not None and self._metering is not None:
            await self._metering.emit_safe(measured_usage, usage_scope=_metering_scope())
        yield done
