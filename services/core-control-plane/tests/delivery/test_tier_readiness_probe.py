from __future__ import annotations

import httpx
import pytest
from fdai.delivery import tier_readiness_probe as probe
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity


class _VectorModel:
    dim = 384

    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = iter(vectors)
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        return next(self._vectors)


def _unit(index: int, *, width: int = 384) -> list[float]:
    return [1.0 if position == index else 0.0 for position in range(width)]


def _near(index: int, other: int) -> list[float]:
    vector = [0.0] * 384
    vector[index], vector[other] = 0.95, 0.31
    return vector


async def _ok() -> int:
    return 200


@pytest.mark.asyncio
async def test_passes_when_paraphrase_clears_threshold_and_unrelated_does_not() -> None:
    model = _VectorModel([_unit(0), _near(0, 1), _unit(2)])
    report = await probe.run_probe(
        embedding_model=model, t2_call=_ok, threshold=0.8, pattern_status="durable_patterns=0"
    )
    assert report.passed
    assert model.calls == 3
    assert report.t1_embedding_dim == 384
    assert report.t1_similar_score is not None and report.t1_unrelated_score is not None
    assert report.t1_similar_score >= 0.8 > report.t1_unrelated_score


@pytest.mark.asyncio
async def test_wrong_dimension_fails_t1() -> None:
    model = _VectorModel([_unit(0, width=3072), _unit(0, width=3072), _unit(1, width=3072)])
    report = await probe.run_probe(
        embedding_model=model, t2_call=_ok, threshold=0.8, pattern_status="x"
    )
    assert not report.t1_passed and not report.passed


@pytest.mark.asyncio
async def test_provider_429_is_recorded_without_retry() -> None:
    calls = 0

    async def throttled() -> int:
        nonlocal calls
        calls += 1
        return 429

    model = _VectorModel([_unit(0), _near(0, 1), _unit(2)])
    report = await probe.run_probe(
        embedding_model=model, t2_call=throttled, threshold=0.8, pattern_status="x"
    )
    assert calls == 1
    assert report.errors == ["t2:http_429"] and not report.passed


@pytest.mark.asyncio
async def test_embedding_error_reports_only_the_failure_class() -> None:
    class _Failing:
        dim = 384

        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("secret provider body")

    report = await probe.run_probe(
        embedding_model=_Failing(), t2_call=_ok, threshold=0.8, pattern_status="x"
    )
    assert report.errors == ["t1:RuntimeError"]


@pytest.mark.asyncio
async def test_t2_probe_sends_one_bounded_request_with_a_bearer_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        status = await probe.probe_t2(
            client=client,
            identity=StaticWorkloadIdentity(
                audience="https://cognitiveservices.azure.com/.default"
            ),
            endpoint="https://example.invalid/",
            deployment="t2.reasoner.primary",
        )
    assert status == 200 and len(seen) == 1
    assert seen[0].url.path == "/openai/deployments/t2.reasoner.primary/chat/completions"
    assert seen[0].headers["authorization"].startswith("Bearer ")


def test_pattern_library_status_never_exposes_the_dsn() -> None:
    assert probe.pattern_library_status(None, lambda dsn: 0) == "in_memory_empty_after_restart"
    assert probe.pattern_library_status("postgresql://secret@host/db", lambda dsn: 7) == (
        "durable_patterns=7"
    )


@pytest.mark.asyncio
async def test_refuses_without_live_flag() -> None:
    assert await probe._amain([]) == 2  # noqa: SLF001
