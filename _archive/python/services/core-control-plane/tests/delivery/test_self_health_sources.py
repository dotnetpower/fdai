"""Real-source self-health composition, without external runtime observations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness import ReadinessDecision, StartupReadinessReport
from fdai.core.readiness.self_health import load_self_health_catalog
from fdai.core.readiness.self_health_runtime import SelfHealthRuntimeMonitor
from fdai.delivery import self_health_sources as sources
from fdai.runtime.health import RuntimeHealthServer
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.resilience.kill_switch import KILL_SWITCH_STATE_KEY
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.self_health import (
    OperationalStateFieldName as FieldName,
)
from fdai_service_contracts.self_health import (
    OperationalStateFieldStatus as FieldStatus,
)
from fdai_service_contracts.self_health import (
    SelfHealthSignalName as Signal,
)
from fdai_service_contracts.self_health import (
    SelfHealthSignalStatus as SignalStatus,
)
from psycopg import OperationalError

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _catalog():
    matrix = load_matrix_from_yaml(ROOT / "config/notifications-matrix.yaml")
    return load_self_health_catalog(
        ROOT / "config/self-health-signals.yaml",
        route_fallbacks={key: route.on_all_fail.value for key, route in matrix.routes.items()},
    )


def _registry(store, *, readiness=None, liveness=None, runtime_policy=None):
    state = readiness or RuntimeReadinessState()
    return sources.runtime_self_health_registry(
        catalog=_catalog(),
        store=store,
        readiness=lambda now: state.is_ready(now=now),
        liveness=liveness,
        runtime_policy=runtime_policy,
    )


@pytest.fixture(autouse=True)
def _installed_version(monkeypatch):
    monkeypatch.setattr(sources, "version", lambda name: "0.1.0")


async def test_only_composed_sources_replace_unavailable_bindings() -> None:
    store = InMemoryStateStore()
    snapshot = await SelfHealthRuntimeMonitor(
        registry=_registry(store), store=store
    ).collect_and_persist(now=NOW)
    signals = {item.signal: item for item in snapshot.self_health.signals}
    fields = {item.name: item for item in snapshot.fields}
    assert len(signals) == 15
    assert len(fields) == 8
    assert signals[Signal.READINESS_PROBE].value == Decimal(0)
    assert signals[Signal.READINESS_PROBE].status is SignalStatus.ALERT
    assert signals[Signal.LIVENESS_PROBE].status is SignalStatus.UNAVAILABLE
    assert signals[Signal.KILL_SWITCH_STATE].reason == "source_missing"
    assert fields[FieldName.KILL_SWITCH].reason == "source_missing"
    assert fields[FieldName.CONFIGURATION].status is FieldStatus.UNAVAILABLE
    assert fields[FieldName.VERSION].status is FieldStatus.AVAILABLE
    for signal in set(Signal) - {Signal.READINESS_PROBE, Signal.KILL_SWITCH_STATE}:
        assert signals[signal].status is SignalStatus.UNAVAILABLE
    assert snapshot.execution_authority is False
    assert await store.verify_chain()


@pytest.mark.parametrize("engaged", [True, False])
async def test_kill_switch_exports_actual_current_state_without_mutation(engaged) -> None:
    store = InMemoryStateStore()
    record = {"engaged": engaged, "revision": 7}
    await store.write_state(KILL_SWITCH_STATE_KEY, record)
    snapshot = await SelfHealthRuntimeMonitor(
        registry=_registry(store), store=store
    ).collect_and_persist(now=NOW)
    signal = next(
        item for item in snapshot.self_health.signals if item.signal is Signal.KILL_SWITCH_STATE
    )
    field = next(item for item in snapshot.fields if item.name is FieldName.KILL_SWITCH)
    assert signal.value == Decimal(int(engaged))
    assert signal.alert is engaged
    assert field.value_digest == canonical_digest({"engaged": engaged})
    assert field.observed_at == NOW
    assert await store.read_state(KILL_SWITCH_STATE_KEY) == record


@pytest.mark.parametrize("value", [None, 0, 1, "false", {}, []])
async def test_malformed_switch_is_never_a_healthy_false(value) -> None:
    store = InMemoryStateStore()
    await store.write_state(KILL_SWITCH_STATE_KEY, {"engaged": value})
    source = sources.KillSwitchSelfHealthSource(store)
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await source.read()
    assert caught.value.reason == "source_malformed"


@pytest.mark.parametrize("error", [OSError("private detail"), OperationalError("private detail")])
async def test_unreachable_source_has_sanitized_reason(error) -> None:
    class UnreachableStore(InMemoryStateStore):
        async def read_state(self, key):
            raise error

    source = sources.KillSwitchSelfHealthSource(UnreachableStore())
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await source.read()
    assert caught.value.reason == "source_unreachable"
    assert "private detail" not in str(caught.value)


async def test_kill_switch_transition_is_reobserved_not_cached() -> None:
    store = InMemoryStateStore()
    exporter = _registry(store).signal_exporters[Signal.KILL_SWITCH_STATE]
    await store.write_state(KILL_SWITCH_STATE_KEY, {"engaged": False})
    assert (await exporter.observe(now=NOW)).value == Decimal(0)
    await store.write_state(KILL_SWITCH_STATE_KEY, {"engaged": True})
    assert (await exporter.observe(now=NOW + timedelta(seconds=30))).value == Decimal(1)


async def test_unreachable_switch_remains_unavailable_in_persisted_projection() -> None:
    class UnreachableSwitchStore(InMemoryStateStore):
        async def read_state(self, key):
            if key == KILL_SWITCH_STATE_KEY:
                raise OSError("private source detail")
            return await super().read_state(key)

    store = UnreachableSwitchStore()
    snapshot = await SelfHealthRuntimeMonitor(
        registry=_registry(store), store=store
    ).collect_and_persist(now=NOW)
    signal = next(
        item for item in snapshot.self_health.signals if item.signal is Signal.KILL_SWITCH_STATE
    )
    field = next(item for item in snapshot.fields if item.name is FieldName.KILL_SWITCH)
    assert signal.status is SignalStatus.UNAVAILABLE
    assert signal.reason == "source_unreachable"
    assert signal.fresh is False
    assert field.status is FieldStatus.UNAVAILABLE
    assert field.reason == "source_unreachable"
    assert "private source detail" not in snapshot.model_dump_json()


async def test_liveness_tracks_actual_listener_lifecycle() -> None:
    server = RuntimeHealthServer(port=1, host="127.0.0.1")
    exporter = _registry(InMemoryStateStore(), liveness=server.is_live).signal_exporters[
        Signal.LIVENESS_PROBE
    ]
    assert (await exporter.observe(now=NOW)).value == Decimal(0)
    server._server = await asyncio.start_server(server._handle, server.host, 0)
    try:
        assert (await exporter.observe(now=NOW)).value == Decimal(1)
    finally:
        await server.close()
    assert (await exporter.observe(now=NOW)).value == Decimal(0)


async def test_readiness_tracks_guarded_state_and_failed_refresh() -> None:
    state = RuntimeReadinessState()
    exporter = _registry(InMemoryStateStore(), readiness=state).signal_exporters[
        Signal.READINESS_PROBE
    ]
    assert (await exporter.observe(now=NOW)).value == Decimal(0)
    state.update(
        StartupReadinessReport(generated_at=NOW, decision=ReadinessDecision.READY, results=())
    )
    assert (await exporter.observe(now=NOW)).value == Decimal(1)
    state.mark_refresh_failed()
    assert (await exporter.observe(now=NOW)).value == Decimal(0)


async def test_configuration_identifies_consumed_values_not_later_mutation() -> None:
    policy = {"logging.level": "INFO", "discovery.enabled": False}
    registry = _registry(InMemoryStateStore(), runtime_policy=policy)
    policy["discovery.enabled"] = True
    field = await registry.state_exporters[FieldName.CONFIGURATION].observe(now=NOW)
    assert field.value_digest == canonical_digest(
        {"logging.level": "INFO", "discovery.enabled": False}
    )
    assert field.source == "runtime:policy-consumed-at-bootstrap"


async def test_version_is_installed_distribution_not_environment() -> None:
    field = await sources.InstalledCoreVersionExporter().observe(now=NOW)
    assert field.value_digest == canonical_digest(
        {"distribution": "fdai-core-control-plane", "version": "0.1.0"}
    )


async def test_missing_distribution_is_unavailable(monkeypatch) -> None:
    def missing(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(sources, "version", missing)
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await sources.InstalledCoreVersionExporter().observe(now=NOW)
    assert caught.value.reason == "source_missing"


@pytest.mark.parametrize("value", ["", " 0.1.0"])
async def test_malformed_distribution_is_unavailable(monkeypatch, value) -> None:
    monkeypatch.setattr(sources, "version", lambda name: value)
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await sources.InstalledCoreVersionExporter().observe(now=NOW)
    assert caught.value.reason == "source_malformed"


def test_unavailable_reason_rejects_arbitrary_source_text() -> None:
    with pytest.raises(ValueError, match="bounded source code"):
        SelfHealthExporterUnavailableError(reason="private detail")
