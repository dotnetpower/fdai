"""Deferred holdout is a durable retry, not a silently acknowledged rejection."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.measurement.pattern_growth import (
    OutcomeRecord,
    TemporalHoldoutConfig,
    TemporalHoldoutValidator,
)
from fdai.core.measurement.pending_growth import PendingPatternGrowth
from fdai.core.measurement.runners import DeferredPatternBuild, PatternGrowthIntakeRunner
from fdai.core.tiers.t1_lightweight.tier import LearnedAction
from fdai.delivery.measurement.holdout import (
    HoldoutVerifiedPatternBuilder,
    StateStoreTemporalHoldoutEvidenceSource,
)
from fdai.delivery.measurement.postgres_growth import (
    PostgresVerifiedOutcomeSource,
    PostgresVerifiedPatternBuilder,
    _advance_watermark,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 10, 16, tzinfo=UTC)
_PENDING = "measurement:pattern_growth:pending:v1"
_WATERMARK = "measurement:pattern_growth:watermark"


async def test_slow_pending_backlog_reserves_budget_for_fresh_pages_on_every_run() -> None:
    store = InMemoryStateStore()
    pending = PendingPatternGrowth(store)
    audit = {
        "actor": "fixture",
        "action_kind": "measurement.pattern_growth.test_deferred",
        "mode": "shadow",
        "recorded_at": _NOW.isoformat(),
    }
    for index in (1, 2):
        await pending.defer(
            OutcomeRecord(f"old-{index}", "ops.scale-out", _NOW, True, True, False),
            audit,
        )

    class SlowBuilder:
        async def build(self, record: OutcomeRecord) -> DeferredPatternBuild:
            await asyncio.sleep(0.075 if record.action_id.startswith("old-") else 0.01)
            return DeferredPatternBuild("holdout_waiting")

    source = _Source(store, [])
    runner = PatternGrowthIntakeRunner(
        outcome_source=source,
        pattern_builder=SlowBuilder(),
        writer=_Writer(),
        audit_store=store,
        clock=lambda: _NOW,
        item_timeout_s=0.2,
        run_timeout_s=0.2,
    )
    for index in range(1, 4):
        source.entries.append(_entry(f"fresh-{index}"))
        report = await runner.run_once()
        watermark = await store.read_state(_WATERMARK)
        assert watermark is not None and watermark["seq"] == index
        assert report.pending_budget_exhausted
        assert any(record.action_id == f"fresh-{index}" for record in await pending.records())


async def test_stalled_pending_writer_does_not_consume_fresh_intake_budget() -> None:
    store = InMemoryStateStore()
    pending = PendingPatternGrowth(store)
    await pending.defer(
        OutcomeRecord("old-1", "ops.scale-out", _NOW, True, True, False),
        {
            "actor": "fixture",
            "action_kind": "measurement.pattern_growth.test_deferred",
            "mode": "shadow",
            "recorded_at": _NOW.isoformat(),
        },
    )

    class Builder:
        async def build(self, record: OutcomeRecord) -> tuple[Sequence[float], LearnedAction]:
            return (0.1,) * 384, LearnedAction(
                signature=record.action_id,
                rule_id="rule-1",
                action_type=record.action_type_id,
                params={},
                incident_id=record.action_id,
                success_rate=0,
                reuse_count=0,
            )

    class Writer:
        async def upsert_pattern(self, *, vector: Sequence[float], action: LearnedAction) -> None:
            if action.incident_id == "old-1":
                await asyncio.Event().wait()

    source = _Source(store, [_entry("fresh-1")])
    report = await PatternGrowthIntakeRunner(
        outcome_source=source,
        pattern_builder=Builder(),
        writer=Writer(),
        audit_store=store,
        clock=lambda: _NOW,
        item_timeout_s=0.2,
        run_timeout_s=0.2,
    ).run_once()
    watermark = await store.read_state(_WATERMARK)
    assert watermark is not None and watermark["seq"] == 1
    assert report.pending_budget_exhausted
    assert report.ingested_signatures == ("fresh-1",)
    assert await pending.records()


async def test_timed_out_pending_item_rotates_with_a_frozen_clock() -> None:
    store = InMemoryStateStore()
    pending = PendingPatternGrowth(store)
    for action_id in ("stalled", "ready"):
        await pending.defer(
            OutcomeRecord(action_id, "ops.scale-out", _NOW, True, True, False),
            {
                "actor": "fixture",
                "action_kind": "measurement.pattern_growth.test_deferred",
                "mode": "shadow",
                "recorded_at": _NOW.isoformat(),
            },
        )
    attempts: list[str] = []

    class Builder:
        async def build(self, record: OutcomeRecord) -> DeferredPatternBuild:
            attempts.append(record.action_id)
            if record.action_id == "stalled":
                await asyncio.Event().wait()
            return DeferredPatternBuild("holdout_waiting")

    runner = PatternGrowthIntakeRunner(
        outcome_source=_Source(store, []),
        pattern_builder=Builder(),
        writer=_Writer(),
        audit_store=store,
        clock=lambda: _NOW,
        item_timeout_s=0.2,
        run_timeout_s=0.05,
    )
    await runner.run_once()
    assert attempts == ["stalled"]
    await runner.run_once()
    assert attempts[1] == "ready"


async def test_owned_unacknowledged_row_does_not_block_fresh_handoff() -> None:
    store = InMemoryStateStore()
    pending = PendingPatternGrowth(store)
    source = _Source(store, [_entry("owned"), _entry("fresh")])
    records = [record async for record in source.outcomes()]
    await store.write_state(_WATERMARK, {"seq": 0, "revision": 2})
    for record in (OutcomeRecord("oldest", "ops.scale-out", _NOW, True, True, False), records[0]):
        await pending.defer(
            record,
            {
                "actor": "fixture",
                "action_kind": "measurement.pattern_growth.test_deferred",
                "mode": "shadow",
                "recorded_at": _NOW.isoformat(),
            },
        )
    attempts: list[str] = []

    class Builder:
        async def build(self, record: OutcomeRecord) -> DeferredPatternBuild:
            attempts.append(record.action_id)
            if record.action_id != "fresh":
                await asyncio.Event().wait()
            return DeferredPatternBuild("holdout_waiting")

    report = await PatternGrowthIntakeRunner(
        outcome_source=source,
        pattern_builder=Builder(),
        writer=_Writer(),
        audit_store=store,
        clock=lambda: _NOW,
        item_timeout_s=0.2,
        run_timeout_s=0.1,
    ).run_once()
    watermark = await store.read_state(_WATERMARK)
    assert watermark is not None and watermark["seq"] == 2
    assert attempts == ["oldest", "fresh"]
    assert report.pending_budget_exhausted
    assert {record.action_id for record in await pending.records()} == {"oldest", "owned", "fresh"}


def _entry(action_id: str = "action-1") -> dict[str, Any]:
    return {
        "action_id": action_id,
        "action_type_id": "ops.scale-out",
        "observed_at": (_NOW - timedelta(days=1)).isoformat(),
        "recorded_at": _NOW.isoformat(),
        "execution_mode": "enforce",
        "decision": "auto",
        "verification_passed": True,
        "rollback_succeeded": False,
        "rule_id": "rule-1",
        "params": {"replicas": 2},
        "incident_id": "incident-1",
        "embedding_projection": "generic capacity mismatch",
    }


class _Source(PostgresVerifiedOutcomeSource):
    def __init__(self, store: InMemoryStateStore, entries: list[dict[str, Any]]) -> None:
        super().__init__(dsn="unused-local-fake", state_store=store)
        self.entries = entries

    async def _rows(self, after_seq: int) -> list[Mapping[str, Any]]:
        return [
            {"seq": i, "entry": entry, "created_at": _NOW}
            for i, entry in enumerate(self.entries, 1)
            if i > after_seq
        ]


class _Embedding:
    dim = 384

    async def embed(self, text: str) -> tuple[float, ...]:
        return (0.1,) * 384


class _Builder(PostgresVerifiedPatternBuilder):
    def __init__(self, source: _Source) -> None:
        super().__init__(dsn="unused-local-fake", embedding_model=_Embedding())
        self.source = source

    async def _entry(self, action_id: str) -> Mapping[str, Any] | None:
        return next(
            (entry for entry in reversed(self.source.entries) if entry["action_id"] == action_id),
            None,
        )


class _Writer:
    def __init__(self) -> None:
        self.writes: list[LearnedAction] = []
        self.fail = False

    async def upsert_pattern(self, *, vector: Sequence[float], action: LearnedAction) -> None:
        self.writes.append(action)
        if self.fail:
            raise RuntimeError("writer unavailable")


def _runner(
    store: InMemoryStateStore,
    source: _Source,
    writer: _Writer,
    **kwargs: Any,
) -> PatternGrowthIntakeRunner:
    return PatternGrowthIntakeRunner(
        outcome_source=source,
        pattern_builder=HoldoutVerifiedPatternBuilder(
            delegate=_Builder(source),
            evidence_source=StateStoreTemporalHoldoutEvidenceSource(store),
            validator=TemporalHoldoutValidator(config=TemporalHoldoutConfig(min_samples=1)),
            audit_store=store,
            clock=lambda: _NOW,
        ),
        audit_store=store,
        writer=writer,
        clock=lambda: _NOW,
        **kwargs,
    )


async def _release(store: InMemoryStateStore, source: _Source) -> None:
    records = await _runner_record(source)
    built = await _Builder(source).build(records[0])
    assert built is not None
    signature = built[1].signature
    await store.write_state(
        f"measurement:pattern_holdout:{signature}",
        {
            "pattern_id": signature,
            "complete": True,
            "samples": [
                {
                    "pattern_id": signature,
                    "observed_at": (_NOW - timedelta(hours=1)).isoformat(),
                    "was_correct": True,
                }
            ],
        },
    )


async def _runner_record(source: _Source) -> list[OutcomeRecord]:
    return [record async for record in source.outcomes()]


async def test_holdout_deferred_before_ack_then_released_after_restart() -> None:
    store = InMemoryStateStore()
    source = _Source(store, [_entry()])
    writer = _Writer()
    report = await _runner(store, source, writer).run_once()
    assert report.deferred_count == 1
    assert report.build_failures == report.accepted_count == report.rejected_count == 0
    assert writer.writes == []
    assert (await store.read_state(_WATERMARK))["seq"] == 1  # type: ignore[index]
    assert len((await store.read_state(_PENDING))["work"]) == 1  # type: ignore[index]
    fresh_source = _Source(InMemoryStateStore(), source.entries)
    await _release(store, fresh_source)

    released = await _runner(store, source, writer).run_once()
    assert released.accepted_count == 1
    assert released.deferred_count == 0
    assert (await store.read_state(_PENDING))["work"] == {}  # type: ignore[index]
    assert writer.writes[0].success_rate == writer.writes[0].reuse_count == 0
    assert (await _runner(store, source, writer).run_once()).total_outcomes == 0


async def test_pending_source_correction_is_revalidated_and_never_written() -> None:
    store = InMemoryStateStore()
    source = _Source(store, [_entry()])
    writer = _Writer()
    await _runner(store, source, writer).run_once()
    source.entries.append({**_entry(), "rollback_succeeded": True})
    report = await _runner(store, source, writer).run_once()
    assert report.accepted_count == 0
    assert report.build_failures == 1
    assert report.rejected_count == 1
    assert writer.writes == []
    assert (await store.read_state(_PENDING))["work"] == {}  # type: ignore[index]


async def test_pending_survives_writer_failure_and_replays() -> None:
    store = InMemoryStateStore()
    source = _Source(store, [_entry()])
    writer = _Writer()
    await _runner(store, source, writer).run_once()
    await _release(store, _Source(InMemoryStateStore(), source.entries))
    writer.fail = True
    with pytest.raises(RuntimeError, match="writer unavailable"):
        await _runner(store, source, writer).run_once()
    assert (await store.read_state(_PENDING))["work"]  # type: ignore[index]
    writer.fail = False
    assert (await _runner(store, source, writer).run_once()).accepted_count == 1


async def test_committed_pattern_with_failed_audit_is_replayed_without_source_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    source = _Source(store, [_entry()])
    writer = _Writer()
    await _release(store, _Source(InMemoryStateStore(), source.entries))
    append = store._append_audit_locked

    def fail_intake(entry: Mapping[str, Any]) -> None:
        if (
            entry["action_kind"] == "measurement.pattern_growth.intake"
            and entry.get("ingested") is True
        ):
            raise RuntimeError("intake audit unavailable")
        append(entry)

    with monkeypatch.context() as patch:
        patch.setattr(store, "_append_audit_locked", fail_intake)
        with pytest.raises(RuntimeError, match="intake audit unavailable"):
            await _runner(store, source, writer).run_once()
    assert len(writer.writes) == 1
    watermark = await store.read_state(_WATERMARK)
    assert watermark is None
    assert (await _runner(store, source, writer).run_once()).accepted_count == 1
    assert len(writer.writes) == 2


async def test_pending_capacity_backpressures_source_acknowledgement() -> None:
    store = InMemoryStateStore()
    source = _Source(store, [_entry("action-1"), _entry("action-2")])
    with pytest.raises(RuntimeError, match="capacity reached"):
        await _runner(store, source, _Writer(), pending_capacity=1).run_once()
    watermark = await store.read_state(_WATERMARK)
    assert watermark is not None and watermark["seq"] == 1
    assert len((await store.read_state(_PENDING))["work"]) == 1  # type: ignore[index]


async def test_failed_pending_transaction_leaves_source_unacknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    source = _Source(store, [_entry()])

    async def conflict(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(store, "compare_and_set_state_with_audit", conflict)
    monkeypatch.setattr(store, "write_state_with_audit_if_absent", conflict)
    with pytest.raises(RuntimeError, match="revision conflict"):
        await _runner(store, source, _Writer()).run_once()
    assert await store.read_state(_WATERMARK) is None
    assert await store.read_state(_PENDING) is None


async def test_expired_pending_is_audited_as_unknown_not_success_or_failure() -> None:
    store = InMemoryStateStore()
    source = _Source(store, [_entry()])
    writer = _Writer()
    await _runner(store, source, writer).run_once()
    report = await _runner(
        store,
        source,
        writer,
        pending_max_age=timedelta(hours=1),
    ).run_once()
    assert report.expired_count == 1
    assert report.accepted_count == report.rejected_count == report.build_failures == 0
    assert writer.writes == []
    assert (await store.read_state(_PENDING))["work"] == {}  # type: ignore[index]
    assert tuple(store.audit_entries)[-2]["entry"]["reason"] == "evidence_deadline_expired"


async def test_build_deadline_defers_before_source_ack() -> None:
    store = InMemoryStateStore()
    source = _Source(store, [_entry()])

    class SlowBuilder:
        async def build(self, record: OutcomeRecord) -> DeferredPatternBuild:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    report = await PatternGrowthIntakeRunner(
        outcome_source=source,
        pattern_builder=SlowBuilder(),
        writer=_Writer(),
        audit_store=store,
        clock=lambda: _NOW,
        item_timeout_s=0.01,
    ).run_once()
    assert report.deferred_count == 1
    assert (await store.read_state(_WATERMARK))["seq"] == 1  # type: ignore[index]
    pending = await store.read_state(_PENDING)
    assert pending is not None and len(pending["work"]) == 1
    assert tuple(store.audit_entries)[-2]["entry"]["reason"] == "pattern_processing"


async def test_run_deadline_preserves_source_and_pending_on_slow_writer() -> None:
    store = InMemoryStateStore()
    source = _Source(store, [_entry()])
    await _runner(store, source, _Writer()).run_once()
    await _release(store, _Source(InMemoryStateStore(), source.entries))

    class SlowWriter(_Writer):
        async def upsert_pattern(
            self,
            *,
            vector: Sequence[float],
            action: LearnedAction,
        ) -> None:
            await asyncio.Event().wait()

    try:
        report = await _runner(store, source, SlowWriter(), run_timeout_s=0.01).run_once()
    except TimeoutError:
        # If both deadlines expire in one scheduler turn, the outer deadline owns cancellation.
        assert (await store.read_state(_WATERMARK))["seq"] == 1  # type: ignore[index]
    else:
        assert report.pending_budget_exhausted
        assert report.accepted_count == 0
    assert (await store.read_state(_PENDING))["work"]  # type: ignore[index]


async def test_whole_run_deadline_still_bounds_a_stalled_fresh_source() -> None:
    store = InMemoryStateStore()

    class StalledSource(_Source):
        async def _rows(self, after_seq: int) -> list[Mapping[str, Any]]:
            await asyncio.Event().wait()
            return []

    with pytest.raises(TimeoutError):
        await _runner(store, StalledSource(store, []), _Writer(), run_timeout_s=0.01).run_once()
    assert await store.read_state(_WATERMARK) is None


async def test_watermark_never_rewinds_under_late_completion() -> None:
    store = InMemoryStateStore()
    await _advance_watermark(store, _WATERMARK, 5)
    await _advance_watermark(store, _WATERMARK, 2)
    assert await store.read_state(_WATERMARK) == {"seq": 5, "revision": 1}


@pytest.mark.parametrize("deadline", [0, -1, float("inf"), float("nan")])
@pytest.mark.parametrize("setting", ["item_timeout_s", "run_timeout_s"])
def test_growth_rejects_unbounded_deadlines(setting: str, deadline: float) -> None:
    store = InMemoryStateStore()
    with pytest.raises(ValueError, match="finite and positive"):
        _runner(store, _Source(store, []), _Writer(), **{setting: deadline})
