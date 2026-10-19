"""Source binding and bounded refresh use the production readiness composition."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness import ReadinessDecision, StartupReadinessReport
from fdai.core.readiness.self_health import load_self_health_catalog
from fdai.delivery.startup_probe import StaticStartupProbe
from fdai.runtime import readiness as module
from fdai.runtime.readiness import (
    RuntimeReadinessState,
    StartupReadinessRuntime,
    build_startup_readiness_runtime,
)
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.self_health import SelfHealthSignalName, SelfHealthSignalStatus
from tests.decision_evidence import StubDecisionEvidenceAdmissionProvider

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _catalog():
    matrix = load_matrix_from_yaml(ROOT / "config/notifications-matrix.yaml")
    return load_self_health_catalog(
        ROOT / "config/self-health-signals.yaml",
        route_fallbacks={name: route.on_all_fail.value for name, route in matrix.routes.items()},
    )


class _Validator:
    def validate(self, instance):
        pass


class _Embedding:
    async def embed(self, text):
        return [0.1, 0.2]


async def test_builder_composes_real_readiness_and_supplied_listener_and_policy() -> None:
    store = InMemoryStateStore()
    runtime = build_startup_readiness_runtime(
        state_store=store,
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=_Validator(),  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=StaticStartupProbe(probe_id="policy.compile", evidence_key="compiled"),
        decision_evidence=StubDecisionEvidenceAdmissionProvider(lambda: datetime.now(UTC)),
        environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
        self_health_catalog=_catalog(),
        liveness=lambda: False,
        runtime_policy={"logging.level": "INFO"},
    )

    await runtime.evaluate()
    persisted = await store.read_state("runtime:operational-state")
    assert persisted is not None
    signals = {item["signal"]: item for item in persisted["snapshot"]["self_health"]["signals"]}
    assert signals["readiness_probe"]["status"] == "healthy"
    assert signals["liveness_probe"]["status"] == "alert"
    assert signals["kill_switch_state"]["reason"] == "source_missing"
    assert signals["event_lag"]["status"] == "unavailable"
    assert persisted["snapshot"]["execution_authority"] is False
    fields = {item["name"]: item for item in persisted["snapshot"]["fields"]}
    assert fields["configuration"]["status"] == "available"


async def test_signal_refresh_does_not_repeat_startup_probes(monkeypatch) -> None:
    clock = NOW
    stop = asyncio.Event()
    observations = []

    class Coordinator:
        calls = 0

        async def evaluate(self):
            self.calls += 1
            return StartupReadinessReport(
                generated_at=clock, decision=ReadinessDecision.READY, results=()
            )

    class Monitor:
        async def collect_and_persist(self, *, now):
            observations.append(now)

    async def wait_for(awaitable, *, timeout):
        nonlocal clock
        awaitable.close()
        clock += timedelta(seconds=timeout)
        if clock >= NOW + timedelta(seconds=95):
            stop.set()
            return
        raise TimeoutError

    monkeypatch.setattr(module, "_utc_now", lambda: clock)
    monkeypatch.setattr(module.asyncio, "wait_for", wait_for)
    coordinator = Coordinator()
    runtime = StartupReadinessRuntime(
        coordinator=coordinator,  # type: ignore[arg-type]
        state=RuntimeReadinessState(),
        refresh_interval_seconds=300,
        self_health_catalog=_catalog(),
        self_health_monitor=Monitor(),  # type: ignore[arg-type]
    )
    await runtime._refresh_self_health_until_stopped(stop)
    assert coordinator.calls == 0
    assert observations[0] == NOW + timedelta(seconds=30)
    assert (
        max(
            (right - left).total_seconds()
            for left, right in zip(observations, observations[1:], strict=False)
        )
        <= 30
    )
    assert all(point < NOW + timedelta(seconds=95) for point in observations)


async def test_slow_startup_probe_does_not_starve_self_health_or_leave_tasks() -> None:
    stop = asyncio.Event()
    probe_started = asyncio.Event()
    probe_cancelled = asyncio.Event()
    observed = asyncio.Event()
    catalog = _catalog()
    catalog = replace(
        catalog,
        policies={
            key: replace(policy, maximum_age_seconds=1) for key, policy in catalog.policies.items()
        },
    )

    class Coordinator:
        async def evaluate(self):
            probe_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                probe_cancelled.set()

    class Monitor:
        async def collect_and_persist(self, *, now):
            assert probe_started.is_set()
            observed.set()
            stop.set()

    runtime = StartupReadinessRuntime(
        coordinator=Coordinator(),  # type: ignore[arg-type]
        state=RuntimeReadinessState(),
        refresh_interval_seconds=0.001,
        self_health_catalog=catalog,
        self_health_monitor=Monitor(),  # type: ignore[arg-type]
    )
    await asyncio.wait_for(runtime.refresh_until_stopped(stop), timeout=2)
    assert observed.is_set()
    assert probe_cancelled.is_set()


async def test_concurrent_source_collection_is_serialized() -> None:
    active = 0
    maximum = 0

    class Monitor:
        async def collect_and_persist(self, *, now):
            nonlocal active, maximum
            active += 1
            maximum = max(active, maximum)
            await asyncio.sleep(0)
            active -= 1

    runtime = StartupReadinessRuntime(
        coordinator=object(),  # type: ignore[arg-type]
        state=RuntimeReadinessState(),
        refresh_interval_seconds=300,
        self_health_monitor=Monitor(),  # type: ignore[arg-type]
    )
    await asyncio.gather(runtime._collect_self_health(), runtime._collect_self_health())
    assert maximum == 1
    assert active == 0


@pytest.mark.parametrize("error", [OSError("private source"), AttributeError("broken exporter")])
async def test_signal_refresh_failure_closes_readiness(monkeypatch, error, caplog) -> None:
    clock = NOW
    stop = asyncio.Event()

    class Monitor:
        async def collect_and_persist(self, *, now):
            stop.set()
            raise error

    async def wait_for(awaitable, *, timeout):
        nonlocal clock
        awaitable.close()
        clock += timedelta(seconds=timeout)
        raise TimeoutError

    monkeypatch.setattr(module, "_utc_now", lambda: clock)
    monkeypatch.setattr(module.asyncio, "wait_for", wait_for)
    state = RuntimeReadinessState()
    state.update(
        StartupReadinessReport(generated_at=NOW, decision=ReadinessDecision.READY, results=())
    )
    runtime = StartupReadinessRuntime(
        coordinator=object(),  # type: ignore[arg-type]
        state=state,
        refresh_interval_seconds=300,
        self_health_catalog=_catalog(),
        self_health_monitor=Monitor(),  # type: ignore[arg-type]
    )
    if isinstance(error, AttributeError):
        with pytest.raises(AttributeError, match="broken exporter"):
            await runtime._refresh_self_health_until_stopped(stop)
    else:
        await runtime._refresh_self_health_until_stopped(stop)
        assert "private source" not in caplog.text
        assert "self_health_refresh_failed" in caplog.messages
    assert state.refresh_failed
    assert not state.is_ready(now=clock)


@pytest.mark.parametrize(
    "offset, reason", [(-61, "observation_stale"), (1, "observation_from_future")]
)
async def test_actual_source_observation_retains_catalog_freshness(offset, reason) -> None:
    from fdai.core.readiness.self_health_runtime import SelfHealthRuntimeMonitor
    from fdai.delivery.self_health_exporters import unavailable_self_health_registry
    from fdai.shared.providers.self_health import SelfHealthExportSample

    registry = unavailable_self_health_registry(_catalog())
    target_signal = SelfHealthSignalName.READINESS_PROBE

    class StaleExporter:
        metric = registry.catalog.policies[target_signal].metric
        exporter_id = "source:retained-readiness"

        @property
        def signal(self):
            return target_signal

        async def observe(self, *, now):
            return SelfHealthExportSample(
                signal=target_signal,
                value=Decimal(1),
                observed_at=NOW + timedelta(seconds=offset),
                source=self.exporter_id,
            )

    registry.signal_exporters[target_signal] = StaleExporter()
    snapshot = await SelfHealthRuntimeMonitor(
        registry=registry, store=InMemoryStateStore()
    ).collect_and_persist(now=NOW)
    result = next(item for item in snapshot.self_health.signals if item.signal is target_signal)
    assert result.status is SelfHealthSignalStatus.ALERT
    assert result.reason == reason
    assert result.fresh is False
