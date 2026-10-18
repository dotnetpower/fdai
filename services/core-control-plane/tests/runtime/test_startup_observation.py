"""Actual process startup observations remain distinct from rates and fleet health."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness.self_health import load_self_health_catalog
from fdai.delivery.startup_probe import StaticStartupProbe
from fdai.runtime.bootstrap_lifecycle import bind_health_readiness
from fdai.runtime.bootstrap_resources import RuntimeResources
from fdai.runtime.health import RuntimeHealthServer
from fdai.runtime.readiness import build_startup_readiness_runtime
from fdai.runtime.startup_observation import RuntimeStartupDurationSource
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.self_health import SelfHealthSignalName, SelfHealthSignalStatus
from tests.decision_evidence import StubDecisionEvidenceAdmissionProvider

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 10, 18, tzinfo=UTC)


class Clock:
    elapsed = 100.0
    wall = NOW

    def monotonic(self) -> float:
        return self.elapsed

    def utc_now(self) -> datetime:
        return self.wall


def _source(clock: Clock) -> RuntimeStartupDurationSource:
    return RuntimeStartupDurationSource(monotonic=clock.monotonic, utc_now=clock.utc_now)


@pytest.mark.parametrize("bound", [False, True])
async def test_missing_first_ready_observation_is_not_zero_or_healthy(bound: bool) -> None:
    source = _source(Clock())
    if bound:
        source.bind_readiness(lambda: False)
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await source.observe(now=NOW)
    assert caught.value.reason == "source_missing"


async def test_elapsed_time_uses_monotonic_clock_and_freezes_first_observation() -> None:
    clock = Clock()
    source = _source(clock)
    clock.elapsed += 12.5
    clock.wall -= timedelta(hours=1)
    source.bind_readiness(lambda: True)
    first = await source.observe(now=NOW)
    assert first.value == Decimal("12.5")
    assert first.observed_at == NOW - timedelta(hours=1)
    clock.elapsed += 120
    clock.wall += timedelta(hours=2)
    source.bind_readiness(lambda: True)
    assert await source.observe(now=clock.wall) == first


async def test_guarded_readiness_records_the_first_actual_ready_check() -> None:
    clock = Clock()
    source = _source(clock)
    ready = False
    source.bind_readiness(lambda: ready)
    clock.elapsed += 7
    ready = True
    assert source.is_ready() is True
    first = await source.observe(now=NOW)
    assert first.value == Decimal(7)
    ready = False
    assert source.is_ready() is False
    assert await source.observe(now=NOW + timedelta(seconds=30)) == first


async def test_collector_can_observe_ready_without_http_polling() -> None:
    clock = Clock()
    source = _source(clock)
    ready = False
    source.bind_readiness(lambda: ready)
    ready = True
    clock.elapsed += 8
    sample = await source.observe(now=NOW + timedelta(seconds=8))
    assert sample.value == Decimal(8)
    assert sample.observed_at == NOW + timedelta(seconds=8)


@pytest.mark.parametrize("ready_before_close", [False, True])
async def test_shutdown_cannot_return_a_healthy_retained_sample(ready_before_close: bool) -> None:
    source = _source(Clock())
    source.bind_readiness(lambda: ready_before_close)
    source.close()
    assert source.is_ready() is False
    with pytest.raises(SelfHealthExporterUnavailableError):
        await source.observe(now=NOW)


async def test_two_process_sources_never_share_start_time_or_samples() -> None:
    first_clock = Clock()
    second_clock = Clock()
    first = _source(first_clock)
    second = _source(second_clock)
    first_clock.elapsed += 4
    second_clock.elapsed += 15
    first.bind_readiness(lambda: True)
    second.bind_readiness(lambda: True)
    assert (await first.observe(now=NOW)).value == Decimal(4)
    assert (await second.observe(now=NOW)).value == Decimal(15)
    assert first.exporter_id != second.exporter_id


async def test_resources_close_the_owned_source() -> None:
    source = _source(Clock())
    source.bind_readiness(lambda: True)
    resources = RuntimeResources(startup_duration_source=source)
    await resources.close()
    with pytest.raises(SelfHealthExporterUnavailableError):
        await source.observe(now=NOW)


def test_new_source_preserves_existing_resource_positional_arguments() -> None:
    diagnostics = object()
    resources = RuntimeResources(None, diagnostics)  # type: ignore[arg-type]
    assert resources.development_diagnostics is diagnostics
    assert resources.startup_duration_source is None


def _catalog():
    matrix = load_matrix_from_yaml(ROOT / "config/notifications-matrix.yaml")
    return load_self_health_catalog(
        ROOT / "config/self-health-signals.yaml",
        route_fallbacks={name: route.on_all_fail.value for name, route in matrix.routes.items()},
    )


class Validator:
    def validate(self, instance: object) -> None:
        del instance


class Embedding:
    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2]


@pytest.mark.parametrize("http_listener", [False, True])
async def test_startup_to_collector_to_persisted_projection_preserves_scope_and_age(
    http_listener: bool,
) -> None:
    clock = Clock()
    source = _source(clock)
    store = InMemoryStateStore()
    runtime = build_startup_readiness_runtime(
        state_store=store,
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=Validator(),  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=Embedding(),
        policy_compile_probe=StaticStartupProbe(probe_id="policy.compile", evidence_key="compiled"),
        environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
        self_health_catalog=_catalog(),
        startup_duration_source=source,
        decision_evidence=StubDecisionEvidenceAdmissionProvider(lambda: datetime.now(UTC)),
    )
    await runtime.evaluate()
    assert runtime.self_health_monitor is not None
    pending = await runtime.self_health_monitor.collect_and_persist(now=NOW)
    pending_signal = next(row for row in pending.self_health.signals if row.signal is source.signal)
    assert pending_signal.status is SelfHealthSignalStatus.UNAVAILABLE
    clock.elapsed += 12
    server = RuntimeHealthServer(port=1) if http_listener else None
    bind_health_readiness(server, control_loop=object(), startup_readiness=runtime)  # type: ignore[arg-type]
    if server is not None:
        assert server.readiness() is True
    snapshot = await runtime.self_health_monitor.collect_and_persist(now=NOW)
    observed = next(row for row in snapshot.self_health.signals if row.signal is source.signal)
    rate = next(
        row
        for row in snapshot.self_health.signals
        if row.signal is SelfHealthSignalName.COLD_START_RATE
    )
    assert observed.value == Decimal(12)
    assert observed.reason == "threshold_breached"
    assert observed.observed_at == NOW
    assert rate.status is SelfHealthSignalStatus.UNAVAILABLE
    assert snapshot.execution_authority is False
    assert snapshot.self_health.execution_authority is False
    persisted = await store.read_state("runtime:operational-state")
    assert persisted is not None
    assert persisted["snapshot"]["snapshot_digest"] == snapshot.snapshot_digest
    stale = await runtime.self_health_monitor.collect_and_persist(now=NOW + timedelta(seconds=301))
    retained = next(row for row in stale.self_health.signals if row.signal is source.signal)
    assert retained.observed_at == NOW
    assert retained.reason == "observation_stale"
    assert retained.fresh is False
    assert await store.verify_chain()


def test_missing_control_loop_does_not_complete_startup() -> None:
    source = _source(Clock())
    from types import SimpleNamespace

    runtime = SimpleNamespace(
        startup_duration_source=source,
        state=SimpleNamespace(is_ready=lambda: True),
    )
    bind_health_readiness(None, control_loop=None, startup_readiness=runtime)  # type: ignore[arg-type]
    assert source.is_ready() is False
