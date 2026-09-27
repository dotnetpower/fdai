from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.forecast_history import (
    ForecastHistoryBinding,
    StateTransitionForecastHistoryCollector,
)
from fdai.core.detection.forecast_history_ingress import ProducingForecastHistoryCollector
from fdai.core.detection.forecast_history_producer import ForecastHistoryProducer
from fdai.core.detection.forecast_history_source import (
    ForecastHistoryProducerBinding,
    ForecastSourceCheckpoint,
    ForecastSourceRead,
    ForecastSourceRecord,
)
from fdai.core.ontology_platform.state_transitions import (
    StateTransitionAuthority,
    StateTransitionBatch,
    StateTransitionLane,
    StateTransitionRead,
)
from fdai.shared.providers.forecast_context import (
    ForecastContextRequest,
    ForecastContextUnavailableError,
)

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
START, END = NOW - timedelta(hours=1), NOW - timedelta(minutes=10)
SCOPE, TARGET = "a" * 64, "resource-example"
KINDS = ("actions", "changes", "excluded_windows", "resource_lifecycle")
STATES = {
    "actions": (["dispatched"], [], {"succeeded": "dispatched", "failed": "dispatched"}),
    "changes": (
        ["changed", "modified"],
        [],
        {"full:upsert": "changed", "tombstone:delete": "changed"},
    ),
    "excluded_windows": (
        ["excluded", "included"],
        ["excluded"],
        {"open": "excluded", "closed": "included"},
    ),
    "resource_lifecycle": (
        ["deleted", "present"],
        ["deleted"],
        {"present": "present", "deleted": "deleted"},
    ),
}


def request(*, as_of: datetime = NOW, shift: timedelta = timedelta()) -> ForecastContextRequest:
    return ForecastContextRequest(
        access_scope_digest=SCOPE,
        target_digest=hashlib.sha256(TARGET.encode()).hexdigest(),
        horizon_started_at=START + shift,
        horizon_ended_at=END + shift,
        as_of=as_of,
    )


def history(kind: str) -> ForecastHistoryBinding:
    to_states, active, _mapping = STATES[kind]
    return ForecastHistoryBinding(
        kind=kind,  # type: ignore[arg-type]
        access_scope_digest=SCOPE,
        target_ref=TARGET,
        state_type=f"forecast.{kind}",
        to_states=tuple(to_states),
        active_states=tuple(active),
        source_identity=f"source:{kind}",
        source_revision="revision-1",
        freshness_seconds=600,
        lookback_seconds=3600,
    )


def binding(kind: str, **mapping: str) -> ForecastHistoryProducerBinding:
    return ForecastHistoryProducerBinding(
        kind=kind,  # type: ignore[arg-type]
        access_scope_digest=SCOPE,
        target_ref=TARGET,
        source_scope_ref="scope-example",
        subject_type="Resource",
        state_mapping=mapping or STATES[kind][2],
    )


def record(event: str, state: str, minutes: int, **values: object) -> ForecastSourceRecord:
    at = START + timedelta(minutes=minutes)
    fields: dict[str, object] = {
        "source_event_id": event,
        "source_revision": "rev-" + event,
        "source_state": state,
        "subject_ref": TARGET,
        "effective_at": at,
        "recorded_at": at,
        "evidence_ref": "evidence:" + event,
    }
    fields.update(values)
    return ForecastSourceRecord(**fields)  # type: ignore[arg-type]


class Source:
    def __init__(
        self,
        kind: str,
        records: tuple[ForecastSourceRecord, ...] = (),
        *,
        limitation: str | None = None,
        initial: str | None = None,
        exhausted: bool = True,
        identity: str | None = None,
        start_offset: timedelta = timedelta(),
        known_offset: timedelta = timedelta(),
        error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.kind, self.records, self.limitation, self.initial = kind, records, limitation, initial
        self.exhausted, self.identity, self.start_offset, self.error = (
            exhausted,
            identity,
            start_offset,
            error,
        )
        self.known_offset, self.delay = known_offset, delay
        self.calls = 0

    async def read(
        self, *, subject_ref: str, start_at: datetime, end_at: datetime, known_at: datetime
    ) -> ForecastSourceRead:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return ForecastSourceRead(
            records=self.records,
            checkpoint=ForecastSourceCheckpoint(
                source_identity=self.identity or f"source:{self.kind}",
                source_revision="revision-1",
                subject_ref=subject_ref,
                coverage_start_at=start_at + self.start_offset,
                coverage_end_at=end_at,
                known_at=known_at - self.known_offset,
                watermark="fence-1",
                evidence_ref=f"checkpoint:{self.kind}",
                complete=self.limitation is None,
                limitation=self.limitation,
                initial_state=self.initial,
                initial_state_ref=f"initial:{self.initial}" if self.initial else None,
            ),
            exhausted=self.exhausted,
        )


class MemoryStore:
    """Mirror the PostgreSQL store's unique keys, replay, and latest-coverage reads."""

    def __init__(self) -> None:
        self.batches: dict[str, StateTransitionBatch] = {}
        self.keys: set[str] = set()

    async def append(self, batch: StateTransitionBatch) -> bool:
        if batch.batch_id in self.batches:
            if self.batches[batch.batch_id] != batch:
                raise ValueError("replay changed content")
            return False
        if any(item.idempotency_key in self.keys for item in batch.transitions):
            raise ValueError("state transition idempotency key changed content")
        self.batches[batch.batch_id] = batch
        self.keys.update(item.idempotency_key for item in batch.transitions)
        return True

    async def read(
        self, *, subject_refs, state_types, to_states, start_at, end_at, known_at, limit
    ):  # type: ignore[no-untyped-def]
        items = sorted(
            (
                item
                for batch in self.batches.values()
                for item in batch.transitions
                if item.subject_ref in subject_refs
                and item.state_type in state_types
                and (to_states is None or item.to_state in to_states)
                and start_at <= item.effective_at <= end_at
                and item.recorded_at <= known_at
            ),
            key=lambda item: (item.effective_at, item.recorded_at, item.transition_id),
        )
        latest = {}
        for item in sorted(
            (c for b in self.batches.values() for c in b.coverage),
            key=lambda c: (c.recorded_at, c.coverage_id),
        ):
            if (
                item.subject_ref in subject_refs
                and item.state_type in state_types
                and item.coverage_start_at <= start_at
                and item.coverage_end_at >= end_at
                and item.recorded_at <= known_at
            ):
                latest[(item.subject_ref, item.state_type)] = item
        reasons = {c.limitation or "coverage_incomplete" for c in latest.values() if not c.complete}
        if len(latest) != len(subject_refs) * len(state_types):
            reasons.add("coverage_missing")
        if len(items) > limit:
            reasons.add("result_limit")
        limitation = "+".join(sorted(reasons)) or None
        return StateTransitionRead(
            tuple(items[:limit]), tuple(latest.values()), limitation is None, limitation
        )


def producer(
    store: MemoryStore, source: Source, kind: str | None = None, **mapping: str
) -> ForecastHistoryProducer:
    kind = kind or source.kind
    return ForecastHistoryProducer(
        binding=binding(kind, **mapping), history=history(kind), source=source, store=store
    )


def sources(**overrides: Source) -> dict[str, Source]:
    defaults = {
        "actions": Source("actions", (record("run-1", "succeeded", 10),)),
        "changes": Source(
            "changes",
            (record("change-1", "full:upsert", 5), record("change-2", "tombstone:delete", 25)),
        ),
        "excluded_windows": Source("excluded_windows", initial="closed"),
        "resource_lifecycle": Source(
            "resource_lifecycle",
            (record("gone", "deleted", 20), record("back", "present", 30)),
            initial="present",
        ),
    }
    defaults.update(overrides)
    return defaults


async def produce_all(store: MemoryStore, bound: dict[str, Source], req: ForecastContextRequest):  # type: ignore[no-untyped-def]
    return {kind: await producer(store, bound[kind]).produce(req) for kind in KINDS}


def collector(store: MemoryStore) -> StateTransitionForecastHistoryCollector:
    return StateTransitionForecastHistoryCollector(
        store=store,
        bindings=tuple(history(kind) for kind in KINDS),  # type: ignore[arg-type]
    )


async def test_positive_checkpoints_produce_history_the_unchanged_collector_accepts() -> None:
    store = MemoryStore()
    receipts = await produce_all(store, sources(), request())
    assert all(item.complete and item.appended for item in receipts.values())
    assert {kind: item.transition_count for kind, item in receipts.items()} == {
        "actions": 1,
        "changes": 2,
        "excluded_windows": 1,
        "resource_lifecycle": 3,
    }
    assert all(
        not item.scoring_eligible and not item.execution_authority for item in receipts.values()
    )
    transitions = [t for batch in store.batches.values() for t in batch.transitions]
    assert {(t.lane, t.authority, t.execution_authority) for t in transitions} == {
        (StateTransitionLane.DERIVED, StateTransitionAuthority.DETERMINISTIC_FUNCTION, False)
    }
    slices = await collector(store).collect(request())
    assert len(slices["actions"]["intervention_refs"]) == 1
    assert len(slices["changes"]["intervention_refs"]) == 2
    assert slices["resource_lifecycle"]["resource_deleted"] is True
    assert slices["excluded_windows"]["excluded_window"] is False


@pytest.mark.parametrize("complete", [True, False])
async def test_empty_read_is_complete_only_with_a_positive_checkpoint(complete: bool) -> None:
    store = MemoryStore()
    empty = Source("changes", limitation=None if complete else "start_checkpoint_unverified")
    receipts = await produce_all(store, sources(changes=empty), request())
    assert receipts["changes"].transition_count == 0
    assert receipts["changes"].complete is complete
    if complete:
        assert (await collector(store).collect(request()))["changes"]["intervention_refs"] == ()
    else:
        assert receipts["changes"].limitation == "start_checkpoint_unverified"
        with pytest.raises(ForecastContextUnavailableError, match="unverified or stale"):
            await collector(store).collect(request())


@pytest.mark.parametrize(
    ("source", "token"),
    [
        (
            Source("changes", (record("c", "full:upsert", 5, pending=True),)),
            "pending_source_record",
        ),
        (
            Source("changes", (record("c", "full:upsert", 5), record("c", "tombstone:delete", 6))),
            "conflicting_source_record",
        ),
        (Source("changes", (record("c", "partial:upsert", 5),)), "unmapped_source_state"),
        (Source("changes", (record("c", "full:upsert", -5),)), "record_out_of_scope"),
        (Source("changes", exhausted=False), "result_limit"),
        (Source("changes", identity="source:other"), "source_identity_mismatch"),
        (Source("changes", start_offset=timedelta(seconds=1)), "coverage_window_short"),
        (Source("changes", error=OSError("source lost")), "source_unavailable"),
        (Source("changes", limitation="Not A Token"), "source_limitation_invalid"),
        (Source("changes", known_offset=timedelta(seconds=1)), "source_knowledge_stale"),
        (Source("changes", known_offset=-timedelta(seconds=1)), "coverage_time_invalid"),
    ],
)
async def test_source_defects_hold_coverage_with_retained_limitation(
    source: Source, token: str
) -> None:
    store = MemoryStore()
    receipt = await producer(store, source).produce(request())
    assert receipt.appended and not receipt.complete and receipt.transition_count == 0
    assert token in (receipt.limitation or "").split("+")
    assert not store.keys
    await produce_all(store, sources(changes=source), request())
    with pytest.raises(ForecastContextUnavailableError):
        await collector(store).collect(request())


async def test_exact_duplicates_collapse_and_restart_never_duplicates_transitions() -> None:
    store = MemoryStore()
    duplicate = record("c", "full:upsert", 5)
    source = Source("changes", (duplicate, duplicate))
    first = await producer(store, source).produce(request())
    assert first.complete and first.transition_count == 1
    replay = await producer(store, source).produce(request())
    assert replay.complete and replay.transition_count == 0
    assert replay.coverage_id == first.coverage_id
    later = await producer(store, source).produce(request(as_of=NOW + timedelta(minutes=1)))
    assert later.appended and later.complete and later.transition_count == 0
    assert len(store.keys) == 1


async def test_changed_mapping_for_a_retained_record_holds_coverage() -> None:
    store = MemoryStore()
    source = Source("changes", (record("c", "full:upsert", 5),))
    assert (await producer(store, source).produce(request())).complete
    changed = await producer(store, source, **{"full:upsert": "modified"}).produce(
        request(as_of=NOW + timedelta(minutes=1))
    )
    assert changed.limitation == "conflicting_retained_record" and changed.transition_count == 0


async def test_stateful_initial_state_is_never_inferred_from_an_empty_read() -> None:
    store = MemoryStore()
    receipt = await producer(store, Source("resource_lifecycle")).produce(request())
    assert receipt.limitation == "initial_state_unknown" and receipt.transition_count == 0
    unmapped = await producer(store, Source("resource_lifecycle", initial="unknown")).produce(
        request(as_of=NOW + timedelta(minutes=1))
    )
    assert unmapped.limitation == "unmapped_source_state"


def lifecycle(initial: str, *records: ForecastSourceRecord) -> dict[str, Source]:
    return sources(resource_lifecycle=Source("resource_lifecycle", records, initial=initial))


async def test_late_deletion_is_appended_while_earlier_knowledge_is_retained() -> None:
    store = MemoryStore()
    await produce_all(store, lifecycle("present"), request())
    assert (await collector(store).collect(request()))["resource_lifecycle"][
        "resource_deleted"
    ] is False
    late = record("gone", "deleted", 20, recorded_at=NOW + timedelta(minutes=2))
    corrected = request(as_of=NOW + timedelta(minutes=3))
    receipts = await produce_all(store, lifecycle("present", late), corrected)
    assert receipts["resource_lifecycle"].transition_count == 1
    assert (await collector(store).collect(corrected))["resource_lifecycle"][
        "resource_deleted"
    ] is True
    assert (await collector(store).collect(request()))["resource_lifecycle"][
        "resource_deleted"
    ] is False


async def test_stale_restatement_that_conflicts_with_a_late_deletion_holds_scoring() -> None:
    store = MemoryStore()
    later = request(as_of=NOW + timedelta(minutes=95), shift=timedelta(minutes=100))
    await produce_all(store, lifecycle("present"), later)
    late = record("gone", "deleted", 20, recorded_at=NOW + timedelta(minutes=100))
    await produce_all(
        store, lifecycle("present", late), request(as_of=NOW + timedelta(minutes=105))
    )
    refreshed = replace(later, as_of=NOW + timedelta(minutes=110))
    receipts = await produce_all(store, lifecycle("deleted"), refreshed)
    assert receipts["resource_lifecycle"].limitation == "conflicting_retained_record"
    assert receipts["resource_lifecycle"].transition_count == 0
    with pytest.raises(ForecastContextUnavailableError, match="unverified or stale"):
        await collector(store).collect(refreshed)


async def test_incomplete_checkpoints_never_persist_transitions() -> None:
    store = MemoryStore()
    unverified = Source(
        "resource_lifecycle",
        (record("gone", "deleted", 20), record("back", "present", 30)),
        initial="present",
        limitation="reconciliation_checkpoint_unverified",
    )
    receipts = await produce_all(
        store,
        sources(
            resource_lifecycle=unverified,
            changes=Source(
                "changes",
                (record("c", "full:upsert", 5),),
                limitation="start_checkpoint_unverified",
            ),
        ),
        request(),
    )
    for kind in ("changes", "resource_lifecycle"):
        assert receipts[kind].transition_count == 0 and not receipts[kind].complete
    stored = {t.state_type for batch in store.batches.values() for t in batch.transitions}
    assert stored == {"forecast.actions", "forecast.excluded_windows"}


async def test_withdrawn_stateful_record_holds_instead_of_completing() -> None:
    store = MemoryStore()
    gone, back = record("gone", "deleted", 20), record("back", "present", 30)
    first = await produce_all(store, lifecycle("present", gone, back), request())
    assert first["resource_lifecycle"].complete
    withdrawn = request(as_of=NOW + timedelta(minutes=1))
    receipts = await produce_all(store, lifecycle("present", gone), withdrawn)
    assert receipts["resource_lifecycle"].limitation == "retained_record_withdrawn"
    assert receipts["resource_lifecycle"].transition_count == 0
    with pytest.raises(ForecastContextUnavailableError, match="unverified or stale"):
        await collector(store).collect(withdrawn)


@pytest.mark.parametrize(
    ("revised", "token"),
    [
        (
            (record("open", "open", 10), record("close", "open", 30, source_revision="r2")),
            "retained_record_withdrawn",
        ),
        (
            (record("open", "open", 10, source_revision="r2"), record("close", "closed", 30)),
            "retained_record_withdrawn",
        ),
        (
            (
                record("open", "open", 10),
                record("open", "open", 10, source_revision="r2"),
                record("close", "closed", 30),
            ),
            "conflicting_source_record",
        ),
    ],
)
async def test_revised_stateful_records_hold_even_when_the_state_is_unchanged(
    revised: tuple[ForecastSourceRecord, ...], token: str
) -> None:
    store = MemoryStore()
    original = (record("open", "open", 10), record("close", "closed", 30))
    window = Source("excluded_windows", original, initial="closed")
    assert (await produce_all(store, sources(excluded_windows=window), request()))[
        "excluded_windows"
    ].complete
    later = request(as_of=NOW + timedelta(minutes=1))
    source = Source("excluded_windows", revised, initial="closed")
    receipt = (await produce_all(store, sources(excluded_windows=source), later))[
        "excluded_windows"
    ]
    assert receipt.limitation == token and receipt.transition_count == 0
    with pytest.raises(ForecastContextUnavailableError):
        await collector(store).collect(later)


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
@pytest.mark.parametrize("states", [("present", "deleted"), ("deleted", "present")])
async def test_one_instant_with_two_states_conflicts_regardless_of_order(
    order: tuple[str, str], states: tuple[str, str]
) -> None:
    records = tuple(record(event, state, 20) for event, state in zip(order, states, strict=True))
    store = MemoryStore()
    for candidate in (records, tuple(reversed(records))):
        source = Source("resource_lifecycle", candidate, initial="present")
        receipt = await producer(store, source).produce(request())
        assert receipt.limitation == "conflicting_source_record"


async def test_overlapping_windows_share_one_grid_restatement() -> None:
    store = MemoryStore()
    await produce_all(store, lifecycle("present"), request())
    shifted = request(as_of=NOW + timedelta(minutes=5), shift=timedelta(minutes=5))
    receipts = await produce_all(store, lifecycle("present"), shifted)
    assert receipts["resource_lifecycle"].complete
    assert receipts["resource_lifecycle"].transition_count == 0
    anchors = [
        t
        for batch in store.batches.values()
        for t in batch.transitions
        if t.state_type == "forecast.resource_lifecycle"
    ]
    assert [(t.from_state, t.effective_at) for t in anchors] == [("checkpoint", START)]
    assert (await collector(store).collect(shifted))["resource_lifecycle"][
        "resource_deleted"
    ] is False


async def test_hanging_source_still_records_unavailable_coverage_within_its_budget() -> None:
    store = MemoryStore()
    hanging = ForecastHistoryProducer(
        binding=binding("changes"),
        history=history("changes"),
        source=Source("changes", delay=10),
        store=store,
        source_timeout_seconds=0.05,
    )
    healthy = producer(store, Source("actions", (record("run-1", "succeeded", 10),)))

    class Reader:
        async def collect(self, request: ForecastContextRequest) -> dict[str, object]:
            return {}

    wrapper = ProducingForecastHistoryCollector(
        collector=Reader(), producers=(hanging, healthy), timeout_seconds=1
    )
    await asyncio.wait_for(wrapper.collect(request()), timeout=2)
    coverage = {c.state_type: c for b in store.batches.values() for c in b.coverage}
    assert coverage["forecast.changes"].limitation == "source_unavailable"
    assert coverage["forecast.actions"].complete


def test_reserved_states_cannot_be_reviewed_mappings() -> None:
    with pytest.raises(ValueError, match="reserved checkpoint"):
        ForecastHistoryBinding.model_validate(
            {**history("resource_lifecycle").model_dump(), "to_states": ["checkpoint", "deleted"]}
        )
    with pytest.raises(ValueError, match="reserved state"):
        binding("actions", succeeded="idle")
    with pytest.raises(ValueError, match="outside the reviewed states"):
        producer(MemoryStore(), Source("actions"), succeeded="unreviewed")


async def test_producing_collector_bounds_failures_and_always_defers_to_the_collector() -> None:
    class Failing(ForecastHistoryProducer):
        async def produce(self, request: ForecastContextRequest):  # type: ignore[no-untyped-def, override]
            raise RuntimeError("store unavailable")

    class Slow(ForecastHistoryProducer):
        async def produce(self, request: ForecastContextRequest):  # type: ignore[no-untyped-def, override]
            await asyncio.sleep(1)

    class Reader:
        calls = 0

        async def collect(self, request: ForecastContextRequest) -> dict[str, object]:
            Reader.calls += 1
            return {}

    store = MemoryStore()
    failing = Failing(
        binding=binding("actions"),
        history=history("actions"),
        source=Source("actions"),
        store=store,
    )
    slow = Slow(
        binding=binding("changes"),
        history=history("changes"),
        source=Source("changes"),
        store=store,
    )
    wrapper = ProducingForecastHistoryCollector(
        collector=Reader(), producers=(failing, slow), timeout_seconds=0.05
    )
    assert wrapper.bound_kinds() == frozenset({"actions", "changes"})
    assert await wrapper.collect(request()) == {} and Reader.calls == 1
    other = replace(request(), target_digest="b" * 64)
    assert await wrapper.collect(other) == {} and Reader.calls == 2
    with pytest.raises(ValueError, match="duplicated"):
        ProducingForecastHistoryCollector(collector=Reader(), producers=(failing, failing))
    with pytest.raises(ValueError, match="timeout"):
        ProducingForecastHistoryCollector(collector=Reader(), producers=(), timeout_seconds=0)
