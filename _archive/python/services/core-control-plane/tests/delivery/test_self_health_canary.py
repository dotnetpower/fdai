"""Real canary-producer records feed only the age signal, not overall canary success."""

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.control_loop import _canary
from fdai.core.control_loop.models import ControlLoopOutcome
from fdai.core.readiness.self_health_runtime import SelfHealthRuntimeMonitor
from fdai.delivery.canary_cli import build_canary_event
from fdai.delivery.self_health_canary import ConsumedCanaryAgeExporter
from fdai.delivery.self_health_sources import runtime_self_health_registry
from fdai.shared.providers.audit_hash import GENESIS_HASH, next_hash
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.self_health import (
    OperationalStateFieldName,
    OperationalStateFieldStatus,
    SelfHealthSignalName,
    SelfHealthSignalStatus,
)

from tests.delivery.test_self_health_sources import _catalog

NOW = datetime(2026, 10, 19, tzinfo=UTC)


async def _produce_canary(
    monkeypatch: pytest.MonkeyPatch, store: StateStore, *, at: datetime, slot: str
) -> None:
    event = build_canary_event(slot=slot, now=at - timedelta(milliseconds=5))

    async def emit(**kwargs: Any) -> None:
        return None

    host = SimpleNamespace(
        _event_ingest=SimpleNamespace(ingest=lambda raw: event),
        _correlate_incident_id=lambda event: None,
        _emit_stage=emit,
        _audit_store=store,
    )
    with monkeypatch.context() as patch:
        patch.setattr(_canary, "datetime", SimpleNamespace(now=lambda *, tz: at))
        result = await _canary.process_canary(host, event)
    assert result.outcome is ControlLoopOutcome.CANARY_RECORDED


class _ReaderStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.row: dict[str, Any] | None = None

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        await super().append_audit_entry(entry)
        previous = self.row["entry_hash"] if self.row is not None else GENESIS_HASH
        self.row = {
            **{
                key: entry[key]
                for key in ("event_id", "correlation_id", "actor", "action_kind", "mode")
            },
            "seq": 1 if self.row is None else self.row["seq"] + 1,
            "entry": deepcopy(dict(entry)),
            "previous_hash": previous,
            "entry_hash": next_hash(previous, entry),
        }

    async def read_latest_consumed_canary(self) -> Mapping[str, Any] | None:
        return deepcopy(self.row)


async def _observed_store(monkeypatch: pytest.MonkeyPatch) -> _ReaderStore:
    store = _ReaderStore()
    await _produce_canary(monkeypatch, store, at=NOW, slot="age-source")
    return store


@pytest.mark.parametrize(
    "microseconds,expected,status",
    [
        (0, "0", SelfHealthSignalStatus.HEALTHY),
        (599_999_999, "599.999999", SelfHealthSignalStatus.HEALTHY),
        (600_000_000, "600", SelfHealthSignalStatus.HEALTHY),
        (600_000_001, "600.000001", SelfHealthSignalStatus.ALERT),
    ],
)
async def test_actual_source_registry_preserves_exact_age_threshold(
    monkeypatch: pytest.MonkeyPatch,
    microseconds: int,
    expected: str,
    status: SelfHealthSignalStatus,
) -> None:
    store = await _observed_store(monkeypatch)
    registry = runtime_self_health_registry(
        catalog=_catalog(), store=store, readiness=lambda at: True
    )
    at = NOW + timedelta(microseconds=microseconds)
    snapshot = await SelfHealthRuntimeMonitor(registry=registry, store=store).collect_and_persist(
        now=at
    )
    signals = {signal.signal: signal for signal in snapshot.self_health.signals}
    age = signals[SelfHealthSignalName.TIME_SINCE_LAST_SUCCESSFUL_CANARY]
    assert age.value == Decimal(expected) and age.status is status and age.observed_at == at
    assert signals[SelfHealthSignalName.CANARY_RESULT].status is SelfHealthSignalStatus.UNAVAILABLE
    assert (
        next(
            field for field in snapshot.fields if field.name is OperationalStateFieldName.CANARY
        ).status
        is OperationalStateFieldStatus.UNAVAILABLE
    )


async def test_old_success_ages_instead_of_becoming_a_new_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _observed_store(monkeypatch)
    before = deepcopy(store.row)
    source = ConsumedCanaryAgeExporter(store, "fdai.canary.age_seconds")
    first = await source.observe(now=NOW + timedelta(seconds=599))
    later = await source.observe(now=NOW + timedelta(seconds=601))
    assert first.value == Decimal(599) and later.value == Decimal(601)
    assert store.row == before
    days_later = await source.observe(now=NOW + timedelta(days=2, microseconds=123))
    assert days_later.value == Decimal("172800.000123")


@pytest.mark.parametrize("unsupported", [False, True])
async def test_missing_reader_or_receipt_never_means_zero_age(unsupported: bool) -> None:
    store = InMemoryStateStore() if unsupported else _ReaderStore()
    source = ConsumedCanaryAgeExporter(store, "fdai.canary.age_seconds")
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == ("source_incomplete" if unsupported else "source_missing")


@pytest.mark.parametrize(
    "field,value",
    [
        ("seq", True),
        ("seq", 0),
        ("entry", []),
        ("actor", "other-owner"),
        ("correlation_id", "other-correlation"),
        ("previous_hash", "invalid"),
        ("entry_hash", "0" * 64),
    ],
)
async def test_corrupt_selected_row_cannot_fall_back_to_old_healthy_evidence(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    store = await _observed_store(monkeypatch)
    assert store.row is not None
    store.row[field] = value
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await ConsumedCanaryAgeExporter(store, "fdai.canary.age_seconds").observe(now=NOW)
    assert failure.value.reason == "source_malformed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("outcome", "failed"),
        ("tier", "other"),
        ("mode", "invalid"),
        ("idempotency_key", "other"),
        ("event_id", "invalid"),
        ("recorded_at", "invalid"),
        ("recorded_at", 123),
        ("recorded_at", "x" * 65),
        ("recorded_at", NOW.replace(tzinfo=None).isoformat()),
        ("latency_ms", True),
        ("latency_ms", 999),
    ],
)
async def test_resealed_invalid_canary_facts_remain_unavailable(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    store = await _observed_store(monkeypatch)
    assert store.row is not None
    store.row["entry"][field] = value
    if field in {"mode", "event_id"}:
        store.row[field] = value
    store.row["entry_hash"] = next_hash(store.row["previous_hash"], store.row["entry"])
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await ConsumedCanaryAgeExporter(store, "fdai.canary.age_seconds").observe(now=NOW)
    assert failure.value.reason == "source_malformed"


async def test_future_canary_is_not_refreshed_into_a_current_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _observed_store(monkeypatch)
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await ConsumedCanaryAgeExporter(store, "fdai.canary.age_seconds").observe(
            now=NOW - timedelta(microseconds=1)
        )
    assert failure.value.reason == "source_from_future"


async def test_source_failure_is_bounded_and_cancellation_propagates() -> None:
    class Failed(_ReaderStore):
        async def read_latest_consumed_canary(self) -> Mapping[str, Any] | None:
            raise OSError("private provider detail")

    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await ConsumedCanaryAgeExporter(Failed(), "fdai.canary.age_seconds").observe(now=NOW)
    assert failure.value.reason == "source_unreachable" and str(failure.value) == ""

    started = asyncio.Event()

    class Blocked(_ReaderStore):
        async def read_latest_consumed_canary(self) -> Mapping[str, Any] | None:
            started.set()
            await asyncio.Event().wait()
            return None

    task = asyncio.create_task(
        ConsumedCanaryAgeExporter(Blocked(), "fdai.canary.age_seconds").observe(now=NOW)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_naive_measurement_clock_is_not_accepted() -> None:
    with pytest.raises(ValueError, match="aware timestamp"):
        await ConsumedCanaryAgeExporter(_ReaderStore(), "fdai.canary.age_seconds").observe(
            now=NOW.replace(tzinfo=None)
        )


async def test_age_threshold_is_exact_under_a_low_precision_caller_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _observed_store(monkeypatch)
    registry = runtime_self_health_registry(
        catalog=_catalog(), store=store, readiness=lambda at: True
    )
    with localcontext() as context:
        context.prec = 3
        sample = await ConsumedCanaryAgeExporter(store, "fdai.canary.age_seconds").observe(
            now=NOW + timedelta(seconds=600, microseconds=1)
        )
        snapshot = await SelfHealthRuntimeMonitor(
            registry=registry, store=store
        ).collect_and_persist(now=NOW + timedelta(seconds=600, microseconds=1))
    assert sample.value == Decimal("600.000001")
    age = next(
        signal
        for signal in snapshot.self_health.signals
        if signal.signal is SelfHealthSignalName.TIME_SINCE_LAST_SUCCESSFUL_CANARY
    )
    assert age.status is SelfHealthSignalStatus.ALERT
