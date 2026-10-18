"""Normal embedding SDK calls produce binding-qualified per-adapter health, not probes."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness.self_health import load_self_health_catalog
from fdai.delivery.azure.llm import embeddings as module
from fdai.delivery.azure.llm.embeddings import (
    AzureOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModelConfig,
)
from fdai.delivery.azure.llm.provider_observations import EmbeddingProviderObservations
from fdai.delivery.startup_probe import StaticStartupProbe
from fdai.runtime.readiness import build_startup_readiness_runtime
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.self_health import (
    OperationalStateSnapshotV1,
    SelfHealthSignalName,
    SelfHealthSignalStatus,
)

NOW = datetime(2026, 10, 19, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[6]
CONFIG = AzureOpenAIEmbeddingModelConfig(
    endpoint="https://example.openai.azure.com",
    deployment="embedding-example",
    dim=2,
)


class Clock:
    now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    factory = EmbeddingProviderObservations
    monkeypatch.setattr(
        module,
        "EmbeddingProviderObservations",
        lambda **kwargs: factory(clock=clock, **kwargs),
    )
    return clock


def _model(client, *, config=CONFIG, identity=None, metering=None):
    return AzureOpenAIEmbeddingModel(
        identity=identity or LocalWorkloadIdentity(),
        http_client=client,
        config=config,
        metering=metering,
    )


def _exporter(model):
    return model.self_health_exporter(maximum_age_seconds=120)


async def _unavailable(exporter, *, reason, now=NOW):
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await exporter.observe(now=now)
    assert caught.value.reason == reason


async def test_unobserved_binding_does_not_probe_or_default_healthy(clock) -> None:
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = _exporter(_model(client))
        await _unavailable(source, reason="source_missing")
        assert calls == []


async def test_success_is_produced_by_normal_sdk_call_and_recollection_cannot_refresh(
    clock,
) -> None:
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        source = _exporter(model)
        assert await model.embed("normal invocation") == [0.1, 0.2]
        sample = await source.observe(now=NOW)
        assert sample.value == Decimal(1)
        assert sample.observed_at == NOW
        assert "t1.embedding" in sample.source
        assert "example" not in sample.source
        assert await source.observe(now=NOW + timedelta(seconds=120)) == sample
        await _unavailable(source, now=NOW + timedelta(seconds=121), reason="source_stale")
        await _unavailable(source, now=NOW - timedelta(seconds=1), reason="source_from_future")
        assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 429, 503])
async def test_http_failures_are_observed_without_adding_retries(clock, status) -> None:
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "private provider detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        with pytest.raises(httpx.HTTPStatusError):
            await model.embed("normal invocation")
        sample = await _exporter(model).observe(now=NOW)
        assert sample.value == Decimal(0)
        assert len(calls) == 1
        assert "private provider detail" not in repr(sample)


async def test_transport_failure_preserves_original_exception_and_failed_observation(clock) -> None:
    async def handler(request):
        raise httpx.ReadTimeout("private transport detail", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        with pytest.raises(httpx.ReadTimeout, match="private transport detail"):
            await model.embed("normal invocation")
        assert (await _exporter(model).observe(now=NOW)).value == Decimal(0)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": [{"embedding": "not-a-vector"}]},
        {"data": [{"embedding": [0.1]}]},
        {"data": [{"embedding": [True, 0.2]}]},
        {"data": [{"embedding": ["invalid", 0.2]}]},
    ],
)
async def test_invalid_provider_contract_never_becomes_api_success(clock, payload) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        model = _model(client)
        with pytest.raises(RuntimeError):
            await model.embed("normal invocation")
        assert (await _exporter(model).observe(now=NOW)).value == Decimal(0)


async def test_non_json_provider_response_is_failed_not_success(clock) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"not json"))
    ) as client:
        model = _model(client)
        with pytest.raises(ValueError):
            await model.embed("normal invocation")
        assert (await _exporter(model).observe(now=NOW)).value == Decimal(0)


async def test_unattempted_auth_failure_is_unknown_not_cached_success(clock) -> None:
    class Identity(LocalWorkloadIdentity):
        fail = False

        async def get_token(self, audience):
            if self.fail:
                raise RuntimeError("identity unavailable")
            return await super().get_token(audience)

    identity = Identity()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client, identity=identity)
        await model.embed("first")
        identity.fail = True
        with pytest.raises(RuntimeError, match="identity unavailable"):
            await model.embed("second")
        await _unavailable(_exporter(model), reason="source_incomplete")
        assert len(calls) == 1


@pytest.mark.parametrize("failure_first", [False, True])
async def test_concurrent_calls_keep_source_unknown_until_every_call_settles(
    clock, failure_first
) -> None:
    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    calls = 0

    async def handler(request):
        nonlocal calls
        index = calls
        calls += 1
        entered[index].set()
        await release[index].wait()
        return httpx.Response(
            503 if index == 0 else 200,
            json={"data": [{"embedding": [0.1, 0.2]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        first = asyncio.create_task(model.embed("first"))
        second = asyncio.create_task(model.embed("second"))
        await asyncio.gather(*(event.wait() for event in entered))
        source = _exporter(model)
        await _unavailable(source, reason="source_incomplete")
        if failure_first:
            release[0].set()
            with pytest.raises(httpx.HTTPStatusError):
                await first
            await _unavailable(source, reason="source_incomplete")
            release[1].set()
            await second
        else:
            release[1].set()
            await second
            await _unavailable(source, reason="source_incomplete")
            release[0].set()
            with pytest.raises(httpx.HTTPStatusError):
                await first
        assert (await source.observe(now=NOW)).value == Decimal(0)
        assert calls == 2


async def test_concurrent_success_cannot_heal_an_unknown_member_of_its_cohort(clock) -> None:
    entered = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        index = calls
        calls += 1
        if index < 2:
            entered[index].set()
            await release.wait()
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        first = asyncio.create_task(model.embed("first"))
        second = asyncio.create_task(model.embed("second"))
        await asyncio.gather(*(event.wait() for event in entered))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        await second
        await _unavailable(_exporter(model), reason="source_incomplete")
        await model.embed("new fully observed cohort")
        assert (await _exporter(model).observe(now=NOW)).value == Decimal(1)


async def test_cancelled_invocation_does_not_publish_success(clock) -> None:
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        task = asyncio.create_task(model.embed("normal invocation"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await _unavailable(_exporter(model), reason="source_incomplete")


async def test_local_post_call_failure_is_not_provider_failure_or_success(clock) -> None:
    class Metering:
        async def emit_safe(self, usage):
            raise RuntimeError("local sink failure")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "data": [{"embedding": [0.1, 0.2]}],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )
        )
    ) as client:
        model = _model(client, metering=Metering())
        with pytest.raises(RuntimeError, match="local sink failure"):
            await model.embed("normal invocation")
        await _unavailable(_exporter(model), reason="source_incomplete")


async def test_changed_binding_and_other_instance_never_inherit_results(clock) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        )
    ) as client:
        old = _model(client)
        await old.embed("normal invocation")
        current = _model(client, config=replace(CONFIG, deployment="new-binding"))
        replica = _model(client)
        for model in (current, replica):
            await _unavailable(_exporter(model), reason="source_missing")
            assert _exporter(model).exporter_id != _exporter(old).exporter_id


async def test_closed_client_is_unavailable_even_with_recent_success(clock) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        )
    )
    model = _model(client)
    await model.embed("normal invocation")
    await client.aclose()
    await _unavailable(_exporter(model), reason="source_unreachable")


async def test_sdk_producer_to_runtime_collector_to_reader_contract_without_probes(clock) -> None:
    matrix = load_matrix_from_yaml(ROOT / "config/notifications-matrix.yaml")
    catalog = load_self_health_catalog(
        ROOT / "config/self-health-signals.yaml",
        route_fallbacks={name: route.on_all_fail.value for name, route in matrix.routes.items()},
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    class Validator:
        def validate(self, instance):
            pass

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        store = InMemoryStateStore()
        runtime = build_startup_readiness_runtime(
            state_store=store,
            event_bus=LocalEventBus(),
            transition_event_bus=LocalEventBus(),
            event_validator=Validator(),  # type: ignore[arg-type]
            identity=LocalWorkloadIdentity(),
            embedding_model=model,
            policy_compile_probe=StaticStartupProbe(
                probe_id="policy.compile", evidence_key="compiled"
            ),
            environment={},
            self_health_catalog=catalog,
            adapter_health_source=model.self_health_exporter(
                maximum_age_seconds=catalog.policies[
                    SelfHealthSignalName.ADAPTER_HEALTHCHECK
                ].maximum_age_seconds
            ),
        )
        assert runtime.self_health_monitor is not None
        before = await runtime.self_health_monitor.collect_and_persist(now=NOW)
        adapter = next(
            row
            for row in before.self_health.signals
            if row.signal is SelfHealthSignalName.ADAPTER_HEALTHCHECK
        )
        assert adapter.status is SelfHealthSignalStatus.UNAVAILABLE
        assert calls == []
        await model.embed("ordinary request")
        snapshot = await runtime.self_health_monitor.collect_and_persist(now=NOW)
        adapter = next(
            row
            for row in snapshot.self_health.signals
            if row.signal is SelfHealthSignalName.ADAPTER_HEALTHCHECK
        )
        assert adapter.status is SelfHealthSignalStatus.HEALTHY
        assert adapter.observed_at == NOW
        assert adapter.execution_authority is False
        for name in (
            SelfHealthSignalName.VERIFIER_FAILURE_RATE,
            SelfHealthSignalName.MIXED_MODEL_DISAGREEMENT_RATE,
        ):
            assert (
                next(row for row in snapshot.self_health.signals if row.signal is name).status
                is SelfHealthSignalStatus.UNAVAILABLE
            )
        persisted = await store.read_state("runtime:operational-state")
        assert persisted is not None
        assert OperationalStateSnapshotV1.model_validate(persisted["snapshot"]) == snapshot
        assert snapshot.execution_authority is False
        assert len(calls) == 1
        assert await store.verify_chain()
        stale = await runtime.self_health_monitor.collect_and_persist(
            now=NOW + timedelta(seconds=121)
        )
        adapter = next(
            row
            for row in stale.self_health.signals
            if row.signal is SelfHealthSignalName.ADAPTER_HEALTHCHECK
        )
        assert adapter.status is SelfHealthSignalStatus.UNAVAILABLE
        assert adapter.reason == "source_stale"
        persisted = await store.read_state("runtime:operational-state")
        assert OperationalStateSnapshotV1.model_validate(persisted["snapshot"]) == stale
        assert len(calls) == 1
