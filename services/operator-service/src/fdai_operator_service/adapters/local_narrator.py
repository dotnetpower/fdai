"""Local-only Azure CLI narrator for the independent Operator Service."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, Protocol, cast
from urllib.parse import quote

import httpx

from fdai_operator_service.adapters.azure_cli_token import (
    AZURE_CLI_TOKEN_TIMEOUT_SECONDS,
    AZURE_OPENAI_AUDIENCE,
    azure_cli_token,
)
from fdai_operator_service.adapters.narrator_events import NarratorEventIterator
from fdai_operator_service.adapters.narrator_latency import (
    NarratorLatencyPool,
    NarratorLatencyStats,
    NarratorTarget,
)
from fdai_operator_service.adapters.narrator_payloads import (
    has_images,
    is_reasoning_model,
    narrator_messages,
    narrator_targets,
    stream_delta,
    vision_probe_content,
    vision_targets,
)
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

_MAX_PROMPT_CHARS = 32_000
_MAX_ANSWER_CHARS = 64_000
_MAX_ARTIFACT_BYTES = 1_048_576

TokenProvider = Callable[[str], Awaitable[str]]
MonotonicClock = Callable[[], float]


class AsyncHttpClient(Protocol):
    """Send the bounded Azure OpenAI request without exposing client internals."""

    def stream(self, url: str, **kwargs: Any) -> AbstractAsyncContextManager[httpx.Response]: ...


@dataclass(slots=True)
class LocalAzureNarratorAdapters:
    """Serve real local narration with Azure CLI auth and no execution authority."""

    targets: tuple[NarratorTarget, ...]
    fallback_projections: ConversationProjectionReader
    fallback_streams: ConversationStreamReader
    token_provider: TokenProvider
    http_client: AsyncHttpClient
    timeout_seconds: float = 90.0
    vision_targets: tuple[NarratorTarget, ...] = ()
    clock: MonotonicClock = monotonic
    _pool: NarratorLatencyPool = field(init=False, repr=False)
    _refresh_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("narrator timeout MUST be positive")
        self._pool = NarratorLatencyPool(
            text_targets=self.targets,
            vision_targets=self.vision_targets,
        )

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
            encoded = path.read_bytes()
        except OSError as exc:
            raise ValueError("resolved narrator artifact is unavailable or invalid") from exc
        if len(encoded) > _MAX_ARTIFACT_BYTES:
            raise ValueError("resolved narrator artifact exceeds the size limit")
        try:
            payload = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("resolved narrator artifact is unavailable or invalid") from exc
        targets = narrator_targets(payload)
        return cls(
            targets=targets,
            fallback_projections=fallback_projections,
            fallback_streams=fallback_streams,
            token_provider=token_provider or azure_cli_token,
            http_client=http_client or cast(AsyncHttpClient, httpx.AsyncClient()),
            vision_targets=vision_targets(payload),
        )

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        """Return sanitized narrator health or delegate another projection read."""
        if query.operation != "chat.health":
            return await self.fallback_projections.read(query)
        credential_available = True
        try:
            await self._token()
        except ConversationBoundaryError:
            credential_available = False
        return ConversationResponse(
            body={
                "available": credential_available,
                "mode": "azure-cli" if credential_available else "unavailable",
                "model": (
                    self._pool.ranked(vision=False)[0].deployment if credential_available else None
                ),
                "endpoint": None,
            }
        )

    async def refresh(self) -> None:
        """Coalesce one bounded text and vision probe cycle across callers."""

        task = self._refresh_task
        if task is None or task.done():
            task = asyncio.create_task(self._refresh_once())
            self._refresh_task = task
        await asyncio.shield(task)

    def latency_snapshot(self, *, vision: bool = False) -> tuple[NarratorLatencyStats, ...]:
        """Return endpoint-free rolling timing evidence for one candidate pool."""

        return self._pool.snapshot(vision=vision)

    async def aclose(self) -> None:
        """Cancel and join the process-local coalesced probe task."""

        task = self._refresh_task
        self._refresh_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

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
        return NarratorEventIterator(
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
        vision = has_images(body)
        if vision:
            raise ConversationBoundaryError(
                503,
                "narrator_image_resolution_unavailable",
                "server-owned narrator image resolution is unavailable",
            )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                token = await self._token()
                messages = narrator_messages(prompt, body)
                targets = self._pool.ranked(vision=False)
                failures: list[int] = []
                for target in targets:
                    status, answer, ttft_ms, latency_ms = await self._stream_answer(
                        target=target,
                        token=token,
                        messages=messages,
                    )
                    if answer is not None and ttft_ms is not None:
                        self._pool.record(
                            deployment=target.deployment,
                            vision=vision,
                            latency_ms=latency_ms,
                            ttft_ms=ttft_ms,
                        )
                        return answer, target.deployment
                    self._record_failure(target=target, vision=vision, elapsed_ms=latency_ms)
                    failures.append(status)
        except TimeoutError as exc:
            raise ConversationBoundaryError(
                504,
                "narrator_timeout",
                "configured narrator candidates exceeded the request deadline",
            ) from exc
        if failures and all(item == 429 for item in failures):
            status = 429
        elif failures and all(item == 503 for item in failures):
            status = 503
        else:
            status = 502
        raise ConversationBoundaryError(
            status,
            "narrator_unavailable",
            "configured narrator candidates are unavailable",
        )

    async def _token(self) -> str:
        try:
            return await asyncio.wait_for(
                self.token_provider(AZURE_OPENAI_AUDIENCE),
                timeout=min(self.timeout_seconds, AZURE_CLI_TOKEN_TIMEOUT_SECONDS),
            )
        except TimeoutError as exc:
            raise ConversationBoundaryError(
                503,
                "narrator_token_timeout",
                "narrator credential acquisition timed out",
            ) from exc

    async def _refresh_once(self) -> None:
        token = await self._token()
        probes = [
            self._probe(target=target, token=token, vision=False)
            for _ in range(2)
            for target in self.targets
        ]
        probes.extend(
            self._probe(target=target, token=token, vision=True) for target in self.vision_targets
        )
        results = await asyncio.gather(*probes, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def _probe(self, *, target: NarratorTarget, token: str, vision: bool) -> None:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "Return OK."},
            {"role": "user", "content": vision_probe_content() if vision else "OK"},
        ]
        _status, answer, ttft_ms, latency_ms = await self._stream_answer(
            target=target,
            token=token,
            messages=messages,
        )
        if answer is None or ttft_ms is None:
            self._record_failure(target=target, vision=vision, elapsed_ms=latency_ms)
            return
        self._pool.record(
            deployment=target.deployment,
            vision=vision,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
        )

    async def _stream_answer(
        self,
        *,
        target: NarratorTarget,
        token: str,
        messages: list[dict[str, Any]],
    ) -> tuple[int, str | None, float | None, float]:
        request_body: dict[str, Any] = {"messages": messages, "stream": True}
        if is_reasoning_model(target.deployment):
            request_body["max_completion_tokens"] = 2048
        else:
            request_body.update({"temperature": 0.2, "max_tokens": 2048})
        url = (
            f"{target.endpoint}/openai/deployments/{quote(target.deployment, safe='')}"
            f"/chat/completions?api-version={quote(target.api_version, safe='')}"
        )
        started = self.clock()
        chunks: list[str] = []
        answer_chars = 0
        answer_bytes = 0
        ttft_ms: float | None = None
        status = 502
        try:
            async with self.http_client.stream(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=request_body,
                timeout=self.timeout_seconds,
            ) as response:
                status = response.status_code
                if status >= 400:
                    return status, None, None, max(0.0, (self.clock() - started) * 1000)
                async for line in response.aiter_lines():
                    try:
                        delta = stream_delta(line)
                    except ValueError:
                        return (
                            502,
                            None,
                            ttft_ms,
                            max(
                                0.0,
                                (self.clock() - started) * 1000,
                            ),
                        )
                    if delta is None:
                        continue
                    if ttft_ms is None:
                        ttft_ms = max(0.0, (self.clock() - started) * 1000)
                    answer_chars += len(delta)
                    answer_bytes += len(delta.encode("utf-8"))
                    if answer_chars > _MAX_ANSWER_CHARS or answer_bytes > _MAX_ANSWER_CHARS:
                        return (
                            502,
                            None,
                            ttft_ms,
                            max(
                                0.0,
                                (self.clock() - started) * 1000,
                            ),
                        )
                    chunks.append(delta)
        except httpx.HTTPError:
            return 502, None, None, max(0.0, (self.clock() - started) * 1000)
        latency_ms = max(0.0, (self.clock() - started) * 1000)
        answer = "".join(chunks).strip()
        if not answer or len(answer) > _MAX_ANSWER_CHARS:
            return 502, None, ttft_ms, latency_ms
        return status, answer, ttft_ms, latency_ms

    def _record_failure(
        self,
        *,
        target: NarratorTarget,
        vision: bool,
        elapsed_ms: float,
    ) -> None:
        penalty_ms = max(elapsed_ms, self.timeout_seconds * 1000)
        self._pool.record(
            deployment=target.deployment,
            vision=vision,
            latency_ms=penalty_ms,
            ttft_ms=penalty_ms,
        )


__all__ = [
    "LocalAzureNarratorAdapters",
    "NarratorLatencyPool",
    "NarratorLatencyStats",
    "NarratorTarget",
]
