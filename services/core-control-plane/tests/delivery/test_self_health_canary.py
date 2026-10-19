"""Canonical audit producer to self-health bindings, with no database or broker calls."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.control_loop import _canary
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness.self_health import load_self_health_catalog
from fdai.core.readiness.self_health_runtime import SelfHealthRuntimeMonitor
from fdai.delivery.canary_cli import build_canary_event
from fdai.delivery.persistence.postgres import PostgresStateStore
from fdai.delivery.self_health_canary import ConsumedCanarySource
from fdai.delivery.self_health_sources import runtime_self_health_registry
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.self_health import (
    OperationalStateFieldName as Field,
)
from fdai_service_contracts.self_health import (
    SelfHealthSignalName as Signal,
)
from psycopg import OperationalError

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 10, 19, tzinfo=UTC)


def _catalog():
    matrix = load_matrix_from_yaml(ROOT / "config/notifications-matrix.yaml")
    return load_self_health_catalog(
        ROOT / "config/self-health-signals.yaml",
        route_fallbacks={key: route.on_all_fail.value for key, route in matrix.routes.items()},
    )


def _monitor(store):
    return SelfHealthRuntimeMonitor(
        registry=runtime_self_health_registry(
            catalog=_catalog(), store=store, readiness=lambda _: True, liveness=lambda: True
        ),
        store=store,
    )


async def _consume(store, monkeypatch, *, recorded_at=NOW, slot="example-slot"):
    class Clock:
        @staticmethod
        def now(tz):
            return recorded_at

    monkeypatch.setattr(_canary, "datetime", Clock)
    event = build_canary_event(slot=slot, now=recorded_at - timedelta(seconds=1))
    host = SimpleNamespace(
        _event_ingest=SimpleNamespace(ingest=lambda raw: raw),
        _correlate_incident_id=lambda event: None,
        _emit_stage=AsyncMock(),
        _audit_store=store,
    )
    await _canary.process_canary(host, event)
    return (await store.read_audit_entries(limit=512))[0][-1]


def _states(snapshot):
    return {item.signal: item for item in snapshot.self_health.signals}


async def test_actual_consumed_audit_supplies_two_signals_and_one_field(monkeypatch):
    store = InMemoryStateStore()
    await _consume(store, monkeypatch)
    snapshot = await _monitor(store).collect_and_persist(now=NOW)
    signals = _states(snapshot)
    assert signals[Signal.CANARY_RESULT].value == Decimal(1)
    assert signals[Signal.CANARY_RESULT].observed_at == NOW
    assert signals[Signal.TIME_SINCE_LAST_SUCCESSFUL_CANARY].value == Decimal(0)
    assert signals[Signal.TIME_SINCE_LAST_SUCCESSFUL_CANARY].fresh
    field = next(item for item in snapshot.fields if item.name is Field.CANARY)
    assert field.status == "available"
    assert field.source == "audit-log:canary:last-success-age"
    assert "example-slot" not in snapshot.model_dump_json()
    assert snapshot.execution_authority is False
    assert await store.verify_chain()


async def test_uninitialized_is_unknown_and_healthy_canary_does_not_hide_missing_sources(
    monkeypatch,
):
    store = InMemoryStateStore()
    first = await _monitor(store).collect_and_persist(now=NOW)
    assert _states(first)[Signal.CANARY_RESULT].reason == "source_missing"
    assert _states(first)[Signal.TIME_SINCE_LAST_SUCCESSFUL_CANARY].value is None
    await _consume(store, monkeypatch)
    second = await _monitor(store).collect_and_persist(now=NOW)
    signals = _states(second)
    assert signals[Signal.CANARY_RESULT].status == "healthy"
    for name in (
        Signal.ADAPTER_HEALTHCHECK,
        Signal.EVENT_LAG,
        Signal.DLQ_DEPTH,
        Signal.COLD_START_RATE,
        Signal.VERIFIER_FAILURE_RATE,
        Signal.MIXED_MODEL_DISAGREEMENT_RATE,
        Signal.ROLLBACK_RATE,
        Signal.OVERRIDE_RATE,
        Signal.DISCOVERY_LOOP_PASS_RATE,
    ):
        assert signals[name].status == "unavailable"
    assert len(signals) == 15
    assert len(second.fields) == 8


async def test_publication_and_startup_round_trip_are_not_consumption(monkeypatch):
    store = InMemoryStateStore()
    event = build_canary_event(slot="published-only", now=NOW)
    await store.append_audit_entry(
        {
            "action_kind": "startup_readiness.transition",
            "outcome": "success",
            "correlation_id": event.correlation_id,
        }
    )
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await ConsumedCanarySource(store).read(now=NOW)
    assert caught.value.reason == "source_missing"


async def test_latest_sequence_not_oldest_or_largest_timestamp(monkeypatch):
    store = InMemoryStateStore()
    await _consume(store, monkeypatch, recorded_at=NOW, slot="earlier-sequence")
    earlier_time = NOW - timedelta(seconds=20)
    last = await _consume(store, monkeypatch, recorded_at=earlier_time, slot="later-sequence")
    receipt = await ConsumedCanarySource(store).read(now=NOW)
    assert receipt.recorded_at == earlier_time
    assert last["recorded_at"] == receipt.recorded_at.isoformat()


async def test_recollection_never_rejuvenates_result_but_age_keeps_increasing(monkeypatch):
    store = InMemoryStateStore()
    await _consume(store, monkeypatch)
    monitor = _monitor(store)
    first = await monitor.collect_and_persist(now=NOW + timedelta(seconds=600))
    last = await monitor.collect_and_persist(now=NOW + timedelta(seconds=601))
    assert _states(first)[Signal.CANARY_RESULT].fresh
    result = _states(last)[Signal.CANARY_RESULT]
    assert result.observed_at == NOW
    assert result.status == "alert"
    assert result.reason == "observation_stale"
    assert not result.fresh
    age = _states(last)[Signal.TIME_SINCE_LAST_SUCCESSFUL_CANARY]
    assert age.value == Decimal(601)
    assert age.observed_at == last.generated_at
    assert age.fresh and age.alert
    before = next(item for item in first.fields if item.name is Field.CANARY)
    after = next(item for item in last.fields if item.name is Field.CANARY)
    assert before.value_digest != after.value_digest


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("actor", "other-producer"),
        ("event_id", "00000000-0000-0000-0000-000000000000"),
        ("correlation_id", "not-canary"),
        ("idempotency_key", "canary:other-slot"),
        ("mode", "enforce"),
        ("tier", "t0"),
        ("decision", "execute"),
        ("outcome", "failed"),
        ("latency_ms", True),
        ("latency_ms", -1),
        ("latency_ms", 1001),
        ("latency_ms", "1000"),
        ("recorded_at", None),
        ("recorded_at", "2026-10-19T00:00:00"),
        ("detected_at", "2026-10-19T00:00:01+00:00"),
        ("detected_at", "invalid-timestamp"),
    ],
)
async def test_invalid_latest_row_never_falls_back_to_old_success(monkeypatch, key, value):
    store = InMemoryStateStore()
    row = dict(await _consume(store, monkeypatch))
    row[key] = value
    await store.append_audit_entry(row)
    snapshot = await _monitor(store).collect_and_persist(now=NOW)
    for name in (Signal.CANARY_RESULT, Signal.TIME_SINCE_LAST_SUCCESSFUL_CANARY):
        assert _states(snapshot)[name].reason == "source_malformed"
        assert _states(snapshot)[name].status == "unavailable"
    assert next(item for item in snapshot.fields if item.name is Field.CANARY).value_digest is None


async def test_future_dated_consumption_is_unknown_not_negative_age(monkeypatch):
    store = InMemoryStateStore()
    await _consume(store, monkeypatch, recorded_at=NOW + timedelta(seconds=1))
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await ConsumedCanarySource(store).read(now=NOW)
    assert caught.value.reason == "source_from_future"


@pytest.mark.parametrize("error", [OSError("private detail"), OperationalError("private detail")])
async def test_source_failure_is_sanitized_and_read_once_per_collection(error):
    class Store(InMemoryStateStore):
        calls = 0

        async def read_audit_entries(self, *, limit):
            self.calls += 1
            raise error

    store = Store()
    snapshot = await _monitor(store).collect_and_persist(now=NOW)
    assert store.calls == 1
    assert _states(snapshot)[Signal.CANARY_RESULT].reason == "source_unreachable"
    assert "private detail" not in snapshot.model_dump_json()


async def test_complete_history_required_for_oldest_first_fallback(monkeypatch):
    store = InMemoryStateStore()
    await _consume(store, monkeypatch)
    for _ in range(512):
        await store.append_audit_entry({"action_kind": "other"})
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await ConsumedCanarySource(store).read(now=NOW)
    assert caught.value.reason == "source_incomplete"


async def test_source_restart_and_replica_share_durable_receipt_not_process_counters(monkeypatch):
    store = InMemoryStateStore()
    row = await _consume(store, monkeypatch)
    first = await ConsumedCanarySource(store).read(now=NOW)
    restarted = ConsumedCanarySource(store)
    replica = ConsumedCanarySource(store)
    later = NOW + timedelta(seconds=30)
    assert await restarted.read(now=later) == await replica.read(now=later) == first
    assert first.recorded_at.isoformat() == row["recorded_at"]
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await ConsumedCanarySource(InMemoryStateStore()).read(now=later)
    assert caught.value.reason == "source_missing"


async def test_one_coherent_detached_read_and_next_collection_reobserves(monkeypatch):
    class Store(InMemoryStateStore):
        reads = 0

        async def read_audit_entries(self, *, limit):
            self.reads += 1
            return await super().read_audit_entries(limit=limit)

    store = Store()
    await _consume(store, monkeypatch)
    store.reads = 0
    monitor = _monitor(store)
    await monitor.collect_and_persist(now=NOW)
    assert store.reads == 1
    await _consume(store, monkeypatch, recorded_at=NOW + timedelta(seconds=20), slot="next-slot")
    store.reads = 0
    refreshed = await monitor.collect_and_persist(now=NOW + timedelta(seconds=30))
    assert store.reads == 1
    assert _states(refreshed)[Signal.TIME_SINCE_LAST_SUCCESSFUL_CANARY].value == Decimal(10)


async def test_cancelled_read_releases_lock_and_recovers_on_next_collection(monkeypatch):
    class Store(InMemoryStateStore):
        blocked = True

        async def read_audit_entries(self, *, limit):
            if self.blocked:
                await asyncio.Event().wait()
            return await super().read_audit_entries(limit=limit)

    store = Store()
    store.blocked = False
    await _consume(store, monkeypatch)
    store.blocked = True
    source = ConsumedCanarySource(store)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(source.read(now=NOW), timeout=0.01)
    store.blocked = False
    receipt = await asyncio.wait_for(source.read(now=NOW + timedelta(seconds=1)), timeout=1)
    assert receipt.recorded_at == NOW


@pytest.mark.parametrize("state", ["valid", "missing", "malformed", "empty"])
async def test_postgres_latest_reader_is_bounded_read_only_and_uses_source_sequence(
    monkeypatch, state
):
    audit = InMemoryStateStore()
    entry = await _consume(audit, monkeypatch)
    row = {
        "valid": {"entry": entry},
        "missing": None,
        "malformed": {"entry": None},
        "empty": {},
    }[state]
    connection = SimpleNamespace(execute=AsyncMock(), transaction=None)
    cursor = SimpleNamespace(fetchone=AsyncMock(return_value=row))
    connection.execute.return_value = cursor

    @asynccontextmanager
    async def transaction():
        yield

    @asynccontextmanager
    async def connect():
        yield connection

    connection.transaction = transaction
    store = object.__new__(PostgresStateStore)
    store._connection = connect
    store._set_statement_timeout = AsyncMock()
    source = ConsumedCanarySource(store)
    if state == "valid":
        assert (await source.read(now=NOW)).recorded_at == NOW
    else:
        with pytest.raises(SelfHealthExporterUnavailableError) as caught:
            await source.read(now=NOW)
        assert caught.value.reason == (
            "source_missing" if state == "missing" else "source_malformed"
        )
    calls = connection.execute.call_args_list
    assert calls[0].args == ("SET TRANSACTION READ ONLY",)
    sql, parameters = calls[1].args
    assert "WHERE action_kind = %s" in sql
    assert "ORDER BY seq DESC LIMIT 1" in sql
    assert parameters == ("control_loop.canary",)
    store._set_statement_timeout.assert_awaited_once_with(connection)


async def test_monitor_timeout_has_no_healthy_default_or_background_read():
    class Store(InMemoryStateStore):
        active = 0
        calls = 0

        async def read_audit_entries(self, *, limit):
            self.calls += 1
            self.active += 1
            try:
                await asyncio.Event().wait()
            finally:
                self.active -= 1

    store = Store()
    monitor = _monitor(store)
    monitor._timeout_seconds = 0.01
    snapshot = await monitor.collect_and_persist(now=NOW)
    assert store.active == 0
    assert store.calls == 1
    for name in (Signal.CANARY_RESULT, Signal.TIME_SINCE_LAST_SUCCESSFUL_CANARY):
        assert _states(snapshot)[name].reason in {"exporter_timeout", "source_incomplete"}
        assert _states(snapshot)[name].status == "unavailable"
    assert next(item for item in snapshot.fields if item.name is Field.CANARY).status == (
        "unavailable"
    )


async def test_absent_history_reader_is_explicitly_incomplete():
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await ConsumedCanarySource(SimpleNamespace()).read(now=NOW)
    assert caught.value.reason == "source_incomplete"
