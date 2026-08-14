"""Focused tests for the real local Azure CLI narrator adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fdai_operator_service.adapters.local_narrator import (
    LocalAzureNarratorAdapters,
    NarratorLatencyPool,
    NarratorTarget,
)
from fdai_operator_service.adapters.narrator_periodic_scheduler import (
    PeriodicNarratorRefreshScheduler,
)
from fdai_operator_service.environment import (
    DEFAULT_NARRATOR_PROBE_INTERVAL_SECONDS,
    LOCAL_AZURE_NARRATOR_ENV,
    NARRATOR_PROBE_INTERVAL_ENV,
    OperatorEnvironment,
    OperatorServiceConfigurationError,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamRequest,
    PrincipalScope,
)


class FallbackAdapters:
    async def read(self, query: ConversationQuery) -> ConversationResponse:
        return ConversationResponse({"operation": query.operation})

    async def open(self, request: ConversationStreamRequest):  # type: ignore[no-untyped-def]
        del request
        raise AssertionError("fallback stream MUST NOT handle chat.stream")


class RecordingHttpClient:
    def __init__(self, answer: str = "Grounded local narrator answer.") -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict[str, object]]] = []

    @asynccontextmanager
    async def stream(self, url: str, **kwargs: object) -> AsyncIterator[httpx.Response]:
        self.calls.append((url, kwargs))
        yield _stream_response(answer=self.answer)


class ScriptedHttpClient:
    def __init__(self, statuses: list[int]) -> None:
        self.statuses = iter(statuses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    @asynccontextmanager
    async def stream(self, url: str, **kwargs: object) -> AsyncIterator[httpx.Response]:
        self.calls.append((url, kwargs))
        status = next(self.statuses)
        yield _stream_response(status=status)


class LinesHttpClient:
    def __init__(self, lines: tuple[str, ...]) -> None:
        self.lines = lines

    @asynccontextmanager
    async def stream(self, url: str, **kwargs: object) -> AsyncIterator[httpx.Response]:
        del url, kwargs
        response = httpx.Response(200)

        async def aiter_lines() -> AsyncIterator[str]:
            for line in self.lines:
                yield line

        response.aiter_lines = aiter_lines  # type: ignore[method-assign]
        yield response


class BlockingHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    @asynccontextmanager
    async def stream(self, url: str, **kwargs: object) -> AsyncIterator[httpx.Response]:
        self.calls.append((url, kwargs))
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        yield _stream_response()


def _stream_response(*, status: int = 200, answer: str = "OK") -> httpx.Response:
    content = "\n".join(
        (
            f'data: {{"choices":[{{"delta":{{"content":{json.dumps(answer)}}}}}]}}',
            "data: [DONE]",
            "",
        )
    )
    return httpx.Response(status, content=content.encode())


class IncrementingClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.001
        return self.value


def _artifact(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "narrator": {
                    "endpoint": "https://example.openai.azure.com",
                    "deployment": "narrator-gpt-5-mini",
                    "api_version": "2024-08-01-preview",
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _pool_artifact(path: Path, *, vision: bool = False) -> Path:
    payload: dict[str, object] = {
        "narrator_candidates": [
            {
                "endpoint": "https://first.openai.azure.com",
                "deployment": "narrator-first",
            },
            {
                "endpoint": "https://second.openai.azure.com",
                "deployment": "narrator-second",
            },
        ]
    }
    if vision:
        payload["vision_candidates"] = [
            {
                "endpoint": "https://vision.openai.azure.com",
                "deployment": "narrator-vision",
            }
        ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


async def test_local_narrator_calls_provider_and_emits_canonical_turn(tmp_path: Path) -> None:
    client = RecordingHttpClient()

    async def token_provider(audience: str) -> str:
        assert audience == "https://cognitiveservices.azure.com/"
        return "test-token"

    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=token_provider,
        http_client=client,
    )
    source = await adapter.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Owner"})),
            body={"prompt": "What is visible?", "view_context": {"headline": "Dashboard"}},
        )
    )
    events = [event async for event in source]

    assert [event.event for event in events] == ["token", "done"]
    assert events[1].data["answer"] == "Grounded local narrator answer."
    assert events[1].data["source"] == "llm:narrator-gpt-5-mini"
    verification = events[1].data["verification"]
    assert isinstance(verification, dict)
    assert verification["status"] == "unverified"
    assert len(client.calls) == 1
    _, kwargs = client.calls[0]
    assert kwargs["headers"] == {
        "Authorization": "Bearer test-token",
        "Content-Type": "application/json",
    }
    assert "max_completion_tokens" in kwargs["json"]  # type: ignore[operator]
    assert "temperature" not in kwargs["json"]  # type: ignore[operator]


async def test_local_narrator_health_requires_a_real_token(tmp_path: Path) -> None:
    async def unavailable_token(_audience: str) -> str:
        raise ConversationBoundaryError(503, "token_unavailable", "token unavailable")

    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=unavailable_token,
        http_client=RecordingHttpClient(),
    )
    result = await adapter.read(
        ConversationQuery(operation="chat.health", scope=PrincipalScope("operator-1"))
    )

    assert result.body == {
        "available": False,
        "mode": "unavailable",
        "model": None,
        "endpoint": None,
    }


async def test_local_narrator_delegates_non_health_projection(tmp_path: Path) -> None:
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=RecordingHttpClient(),
    )
    result = await adapter.read(
        ConversationQuery(operation="user.context", scope=PrincipalScope("operator-1"))
    )
    assert result.body == {"operation": "user.context"}


async def _token() -> str:
    return "test-token"


def test_local_narrator_flag_is_dev_only() -> None:
    base = {
        "FDAI_ENTRA_TENANT_ID": "tenant",
        "FDAI_API_AUDIENCE": "audience",
        "FDAI_RBAC_READERS_GROUP_ID": "reader",
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": "contributor",
        "FDAI_RBAC_APPROVERS_GROUP_ID": "approver",
        "FDAI_RBAC_OWNERS_GROUP_ID": "owner",
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID": "break-glass",
        LOCAL_AZURE_NARRATOR_ENV: "1",
    }
    with pytest.raises(ValueError, match="requires RUNTIME_ENV=dev"):
        OperatorEnvironment.parse({**base, "RUNTIME_ENV": "prod"})
    environment = OperatorEnvironment.parse({**base, "RUNTIME_ENV": "dev"})
    assert environment.local_azure_narrator is True
    assert environment.narrator_probe_interval_seconds == DEFAULT_NARRATOR_PROBE_INTERVAL_SECONDS

    for value in ("29", "3601", "invalid"):
        with pytest.raises(OperatorServiceConfigurationError, match=NARRATOR_PROBE_INTERVAL_ENV):
            OperatorEnvironment.parse(
                {
                    **base,
                    "RUNTIME_ENV": "dev",
                    NARRATOR_PROBE_INTERVAL_ENV: value,
                }
            )


def test_local_narrator_rejects_non_azure_token_destination(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "narrator": {
                    "endpoint": "https://attacker.example.com",
                    "deployment": "narrator-gpt-4o-mini",
                }
            }
        ),
        encoding="utf-8",
    )
    fallback = FallbackAdapters()

    with pytest.raises(ValueError, match="no usable narrator candidate"):
        LocalAzureNarratorAdapters.from_environment(
            {"LLM_RESOLVED_MODELS_PATH": str(path)},
            fallback_projections=fallback,
            fallback_streams=fallback,
            token_provider=lambda _audience: _token(),
            http_client=RecordingHttpClient(),
        )


def test_local_narrator_rejects_oversized_artifact_and_candidate_pool(tmp_path: Path) -> None:
    fallback = FallbackAdapters()
    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * 1_048_577, encoding="utf-8")
    with pytest.raises(ValueError, match="size limit"):
        LocalAzureNarratorAdapters.from_environment(
            {"LLM_RESOLVED_MODELS_PATH": str(oversized)},
            fallback_projections=fallback,
            fallback_streams=fallback,
            token_provider=lambda _audience: _token(),
            http_client=RecordingHttpClient(),
        )

    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        json.dumps(
            {
                "narrator_candidates": [
                    {
                        "endpoint": f"https://candidate-{index}.openai.azure.com",
                        "deployment": f"candidate-{index}",
                    }
                    for index in range(9)
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="candidate limit"):
        LocalAzureNarratorAdapters.from_environment(
            {"LLM_RESOLVED_MODELS_PATH": str(candidates)},
            fallback_projections=fallback,
            fallback_streams=fallback,
            token_provider=lambda _audience: _token(),
            http_client=RecordingHttpClient(),
        )


def test_narrator_latency_pool_bounds_independent_timing_windows() -> None:
    first = NarratorTarget("https://first.openai.azure.com", "first", "v1")
    second = NarratorTarget("https://second.openai.azure.com", "second", "v1")
    vision = NarratorTarget("https://vision.openai.azure.com", "vision", "v1")
    pool = NarratorLatencyPool(text_targets=(first, second), vision_targets=(vision,))

    for value in range(1, 10):
        pool.record(
            deployment="first",
            vision=False,
            latency_ms=float(value),
            ttft_ms=float(value) / 2,
        )
    pool.record(deployment="second", vision=False, latency_ms=3.0, ttft_ms=1.0)

    stats = pool.snapshot()
    assert stats[0].sample_count == 8
    assert stats[0].latency_p50_ms == 5.5
    assert stats[0].latency_p95_ms == pytest.approx(8.65)
    assert stats[0].ttft_p50_ms == 2.75
    assert [target.deployment for target in pool.ranked(vision=False)] == ["second", "first"]
    assert pool.snapshot(vision=True)[0].sample_count == 0


def test_narrator_latency_pool_rejects_invalid_samples_and_duplicate_deployments() -> None:
    target = NarratorTarget("https://first.openai.azure.com", "duplicate", "v1")
    with pytest.raises(ValueError, match="deployments MUST be unique"):
        NarratorLatencyPool(text_targets=(target, target), vision_targets=())

    pool = NarratorLatencyPool(text_targets=(target,), vision_targets=())
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="timing sample"):
            pool.record(
                deployment="duplicate",
                vision=False,
                latency_ms=value,
                ttft_ms=1.0,
            )


async def test_narrator_refresh_coalesces_bounded_text_and_vision_probes(
    tmp_path: Path,
) -> None:
    client = BlockingHttpClient()
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_pool_artifact(tmp_path / "models.json", vision=True))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=client,
    )
    adapter.clock = IncrementingClock()

    first = asyncio.create_task(adapter.refresh())
    await client.started.wait()
    second = asyncio.create_task(adapter.refresh())
    client.release.set()
    await asyncio.gather(first, second)

    assert len(client.calls) == 5
    assert [item.sample_count for item in adapter.latency_snapshot()] == [2, 2]
    assert [item.sample_count for item in adapter.latency_snapshot(vision=True)] == [1]
    assert all(
        item.ttft_p50_ms is not None
        and item.latency_p50_ms is not None
        and item.ttft_p50_ms < item.latency_p50_ms
        for item in (*adapter.latency_snapshot(), *adapter.latency_snapshot(vision=True))
    )
    vision_body = client.calls[-1][1]["json"]
    assert "image_url" in json.dumps(vision_body)


async def test_periodic_scheduler_closes_real_shielded_probe(tmp_path: Path) -> None:
    client = BlockingHttpClient()
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_pool_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=client,
    )
    scheduler = PeriodicNarratorRefreshScheduler(adapter, interval_seconds=60)

    await scheduler.start()
    await asyncio.wait_for(client.started.wait(), timeout=1)
    await asyncio.wait_for(scheduler.aclose(), timeout=1)

    assert client.cancelled.is_set()


async def test_narrator_failure_penalty_fails_over_and_reorders_pool(tmp_path: Path) -> None:
    client = ScriptedHttpClient([500, 200, 200])
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_pool_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=client,
    )
    adapter.clock = IncrementingClock()
    request = ConversationStreamRequest(
        operation="chat.stream",
        scope=PrincipalScope("operator-1"),
        body={"prompt": "Summarize."},
    )

    first_events = [event async for event in await adapter.open(request)]
    second_events = [event async for event in await adapter.open(request)]

    assert first_events[-1].data["model"] == "narrator-second"
    assert second_events[-1].data["model"] == "narrator-second"
    assert "narrator-first" in client.calls[0][0]
    assert "narrator-second" in client.calls[1][0]
    assert "narrator-second" in client.calls[2][0]


@pytest.mark.parametrize("field", ("image_ids", "images"))
async def test_narrator_image_turn_requires_server_owned_resolution(
    tmp_path: Path,
    field: str,
) -> None:
    client = RecordingHttpClient()
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_pool_artifact(tmp_path / "models.json", vision=True))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=client,
    )

    with pytest.raises(ConversationBoundaryError) as raised:
        await adapter.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=PrincipalScope("operator-1"),
                body={"prompt": "Describe image.", field: ["att-example"]},
            )
        )
    assert raised.value.status_code == 503
    assert raised.value.code == "narrator_image_resolution_unavailable"
    assert client.calls == []


async def test_narrator_all_text_candidates_fail_unavailable(tmp_path: Path) -> None:
    client = ScriptedHttpClient([500, 500])
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_pool_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=client,
    )
    adapter.clock = IncrementingClock()

    with pytest.raises(ConversationBoundaryError) as raised:
        await adapter.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=PrincipalScope("operator-1"),
                body={"prompt": "Summarize."},
            )
        )

    assert raised.value.status_code == 502
    assert raised.value.code == "narrator_unavailable"
    assert len(client.calls) == 2


async def test_narrator_token_provider_and_answer_are_bounded(tmp_path: Path) -> None:
    fallback = FallbackAdapters()
    blocked = asyncio.Event()

    async def blocked_token(_audience: str) -> str:
        await blocked.wait()
        return "unreachable"

    timeout_adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "timeout.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=blocked_token,
        http_client=RecordingHttpClient(),
    )
    timeout_adapter.timeout_seconds = 0.001
    with pytest.raises(ConversationBoundaryError) as timeout:
        await timeout_adapter.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=PrincipalScope("operator-1"),
                body={"prompt": "Summarize."},
            )
        )
    assert timeout.value.code == "narrator_timeout"

    oversized_client = RecordingHttpClient(answer="x" * 64_001)
    oversized_adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "answer.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=oversized_client,
    )
    with pytest.raises(ConversationBoundaryError) as oversized:
        await oversized_adapter.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=PrincipalScope("operator-1"),
                body={"prompt": "Summarize."},
            )
        )
    assert oversized.value.status_code == 502
    assert oversized.value.code == "narrator_unavailable"


async def test_narrator_preserves_all_unavailable_status(tmp_path: Path) -> None:
    client = ScriptedHttpClient([503, 503])
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_pool_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=client,
    )

    with pytest.raises(ConversationBoundaryError) as raised:
        await adapter.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=PrincipalScope("operator-1"),
                body={"prompt": "Summarize."},
            )
        )

    assert raised.value.status_code == 503


@pytest.mark.parametrize(
    "line",
    (
        "data: {malformed",
        'data: {"choices":"invalid"}',
        "data: " + ("x" * 131_073),
    ),
)
async def test_narrator_malformed_sse_fails_closed(tmp_path: Path, line: str) -> None:
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=LinesHttpClient((line, "data: [DONE]")),
    )

    with pytest.raises(ConversationBoundaryError) as raised:
        await adapter.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=PrincipalScope("operator-1"),
                body={"prompt": "Summarize."},
            )
        )

    assert raised.value.status_code == 502


async def test_narrator_unicode_answer_obeys_wire_byte_bound(tmp_path: Path) -> None:
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=RecordingHttpClient(answer="가" * 30_000),
    )

    with pytest.raises(ConversationBoundaryError) as raised:
        await adapter.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=PrincipalScope("operator-1"),
                body={"prompt": "Summarize."},
            )
        )

    assert raised.value.status_code == 502
