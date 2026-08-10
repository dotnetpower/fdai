"""Local-only Azure CLI narrator for the independent Operator Service."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import quote, urlparse

import httpx

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationEventStream,
    ConversationProjectionReader,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamReader,
    ConversationStreamRequest,
    JsonObject,
    StreamEvent,
)

_AZURE_OPENAI_AUDIENCE = "https://cognitiveservices.azure.com/"
_MAX_PROMPT_CHARS = 32_000
_MAX_ANSWER_CHARS = 64_000

TokenProvider = Callable[[str], Awaitable[str]]


class AsyncHttpClient(Protocol):
    """Send the bounded Azure OpenAI request without exposing client internals."""

    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


@dataclass(frozen=True, slots=True)
class NarratorTarget:
    """One validated Azure OpenAI narrator deployment from the resolved artifact."""

    endpoint: str
    deployment: str
    api_version: str


class _EventIterator(AsyncIterator[StreamEvent]):
    def __init__(self, events: tuple[StreamEvent, ...]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> _EventIterator:
        return self

    async def __anext__(self) -> StreamEvent:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        """Close the finite local narrator stream."""


@dataclass(slots=True)
class LocalAzureNarratorAdapters:
    """Serve real local narration with Azure CLI auth and no execution authority."""

    targets: tuple[NarratorTarget, ...]
    fallback_projections: ConversationProjectionReader
    fallback_streams: ConversationStreamReader
    token_provider: TokenProvider
    http_client: AsyncHttpClient
    timeout_seconds: float = 90.0

    @classmethod
    def from_environment(
        cls,
        values: Mapping[str, str],
        *,
        fallback_projections: ConversationProjectionReader,
        fallback_streams: ConversationStreamReader,
        token_provider: TokenProvider | None = None,
        http_client: AsyncHttpClient | None = None,
    ) -> LocalAzureNarratorAdapters:
        """Build a local narrator from the prepared resolved-model artifact."""
        path_value = values.get("LLM_RESOLVED_MODELS_PATH", "").strip()
        if not path_value:
            raise ValueError("LLM_RESOLVED_MODELS_PATH MUST be configured for local narration")
        path = Path(path_value)
        if not path.is_absolute() or not path.is_file():
            raise ValueError("LLM_RESOLVED_MODELS_PATH MUST name an existing absolute file")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("resolved narrator artifact is unavailable or invalid") from exc
        targets = _targets(payload)
        return cls(
            targets=targets,
            fallback_projections=fallback_projections,
            fallback_streams=fallback_streams,
            token_provider=token_provider or _azure_cli_token,
            http_client=http_client or cast(AsyncHttpClient, httpx.AsyncClient()),
        )

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        """Return sanitized narrator health or delegate another projection read."""
        if query.operation != "chat.health":
            return await self.fallback_projections.read(query)
        credential_available = True
        try:
            await self.token_provider(_AZURE_OPENAI_AUDIENCE)
        except ConversationBoundaryError:
            credential_available = False
        return ConversationResponse(
            body={
                "available": credential_available,
                "mode": "azure-cli" if credential_available else "unavailable",
                "model": self.targets[0].deployment if credential_available else None,
                "endpoint": None,
            }
        )

    async def open(self, request: ConversationStreamRequest) -> ConversationEventStream:
        """Call the configured narrator and expose one bounded canonical SSE turn."""
        if request.operation != "chat.stream":
            return await self.fallback_streams.open(request)
        prompt = request.body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _MAX_PROMPT_CHARS:
            raise ConversationBoundaryError(
                400,
                "invalid_prompt",
                "prompt MUST be non-empty and bounded",
            )
        answer, model = await self._answer(prompt.strip(), request.body)
        verification: JsonObject = {
            "status": "unverified",
            "authority": "model-knowledge",
            "checks_completed": 0,
            "checks_total": 0,
            "evidence_refs": [],
            "reason_code": "local_narrator_model_knowledge",
            "claims": [],
            "failed_claim_ids": [],
        }
        return _EventIterator(
            (
                StreamEvent(event="token", data={"seq": 1, "revision": 0, "delta": answer}),
                StreamEvent(
                    event="done",
                    data={
                        "seq": 2,
                        "revision": 0,
                        "answer": answer,
                        "model": model,
                        "source": f"llm:{model}",
                        "verification": verification,
                    },
                ),
            )
        )

    async def _answer(self, prompt: str, body: Mapping[str, Any]) -> tuple[str, str]:
        token = await self.token_provider(_AZURE_OPENAI_AUDIENCE)
        messages = _messages(prompt, body)
        failures: list[int] = []
        for target in self.targets:
            request_body: dict[str, Any] = {"messages": messages}
            if _is_reasoning_model(target.deployment):
                request_body["max_completion_tokens"] = 2048
            else:
                request_body.update({"temperature": 0.2, "max_tokens": 2048})
            url = (
                f"{target.endpoint}/openai/deployments/{quote(target.deployment, safe='')}"
                f"/chat/completions?api-version={quote(target.api_version, safe='')}"
            )
            try:
                response = await self.http_client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                    timeout=self.timeout_seconds,
                )
            except httpx.HTTPError:
                failures.append(502)
                continue
            if response.status_code >= 400:
                failures.append(response.status_code)
                continue
            answer = _answer_text(response)
            if answer is not None:
                return answer, target.deployment
            failures.append(502)
        status = 429 if failures and all(item == 429 for item in failures) else 502
        raise ConversationBoundaryError(
            status,
            "narrator_unavailable",
            "configured narrator candidates are unavailable",
        )


async def _azure_cli_token(audience: str) -> str:
    if shutil.which("az") is None:
        raise ConversationBoundaryError(503, "azure_cli_unavailable", "Azure CLI is unavailable")
    try:
        process = await asyncio.create_subprocess_exec(
            "az",
            "account",
            "get-access-token",
            "--resource",
            audience,
            "--query",
            "accessToken",
            "-o",
            "tsv",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ConversationBoundaryError(
            503,
            "azure_cli_unavailable",
            "Azure CLI is unavailable",
        ) from exc
    stdout, _ = await process.communicate()
    token = stdout.decode().strip()
    if process.returncode != 0 or not token:
        raise ConversationBoundaryError(
            503,
            "azure_cli_token_unavailable",
            "Azure CLI token is unavailable",
        )
    return token


def _targets(payload: object) -> tuple[NarratorTarget, ...]:
    if not isinstance(payload, dict):
        raise ValueError("resolved narrator artifact MUST be an object")
    raw = payload.get("narrator_candidates")
    candidates = raw if isinstance(raw, list) and raw else [payload.get("narrator")]
    targets: list[NarratorTarget] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        endpoint = candidate.get("endpoint")
        deployment = candidate.get("deployment")
        api_version = candidate.get("api_version", "2024-08-01-preview")
        if (
            isinstance(endpoint, str)
            and _is_allowed_endpoint(endpoint)
            and isinstance(deployment, str)
            and deployment.strip()
            and isinstance(api_version, str)
            and api_version.strip()
        ):
            targets.append(NarratorTarget(endpoint.rstrip("/"), deployment, api_version))
    if not targets:
        raise ValueError("resolved narrator artifact contains no usable narrator candidate")
    return tuple(targets)


def _messages(prompt: str, body: Mapping[str, Any]) -> list[dict[str, str]]:
    context = body.get("view_context")
    history = body.get("history")
    context_text = json.dumps(context, ensure_ascii=False, sort_keys=True)[:24_000]
    messages = [
        {
            "role": "system",
            "content": (
                "You are Bragi, the FDAI presentation narrator. Answer the operator directly. "
                "Use only supplied screen context or clearly label general model knowledge. "
                "Never claim current cloud state without evidence and never approve or execute "
                "actions."
            ),
        },
        {"role": "system", "content": f"Current screen context: {context_text}"},
    ]
    if isinstance(history, list):
        for item in history[-12:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                messages.append({"role": role, "content": content[:8_000]})
    messages.append({"role": "user", "content": prompt})
    return messages


def _answer_text(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        return None
    normalized = content.strip()
    return normalized if normalized and len(normalized) <= _MAX_ANSWER_CHARS else None


def _is_reasoning_model(deployment: str) -> bool:
    normalized = deployment.casefold()
    return any(token in normalized for token in ("gpt-5", "o1", "o3", "o4"))


def _is_allowed_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and hostname.endswith(".openai.azure.com")
    )


__all__ = ["LocalAzureNarratorAdapters", "NarratorTarget"]
