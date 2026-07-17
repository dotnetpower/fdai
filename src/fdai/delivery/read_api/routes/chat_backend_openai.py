"""API-key OpenAI-compatible chat backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from starlette.exceptions import HTTPException

from fdai.delivery.read_api.routes.chat_backend_common import (
    _completion_body_params,
    _default_chat_http_client,
    _raise_upstream_error,
)
from fdai.delivery.read_api.routes.chat_prompt import _build_messages

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
    max_tokens: int = 800
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

        choices = envelope.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HTTPException(status_code=502, detail="chat upstream returned no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise HTTPException(status_code=502, detail="chat upstream returned no content")
        return {"answer": content.strip(), "model": self._config.model}
