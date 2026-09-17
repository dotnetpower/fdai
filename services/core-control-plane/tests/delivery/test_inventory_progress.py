from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.inventory_progress import (
    INVENTORY_PROGRESS_GENESIS_DIGEST,
    CompositeInventoryProgressPublisher,
    InventoryProgressRecorder,
    InventoryProgressUnavailableError,
)
from fdai_service_contracts import (
    InventoryProgressFractionBasis,
    InventoryProgressRecord,
    InventoryProgressStage,
    InventoryProgressState,
)

NOW = datetime(2026, 9, 16, tzinfo=UTC)
GENERATION_DIGEST = "sha256:" + "a" * 64


@dataclass
class _Publisher:
    records: list[InventoryProgressRecord]

    async def append(self, record: InventoryProgressRecord) -> bool:
        self.records.append(record)
        return True


def _recorder(*publishers: _Publisher) -> InventoryProgressRecorder:
    return InventoryProgressRecorder(
        run_id="run.abcdef",
        attempt_id="attempt.1",
        scopes_total=1,
        provider_types_total=4,
        pages_expected=4,
        started_at=NOW,
        deadline_at=NOW + timedelta(minutes=5),
        publisher=CompositeInventoryProgressPublisher(*publishers),
        clock=lambda: NOW + timedelta(seconds=1),
    )


async def test_recorder_serializes_monotonic_hash_chained_progress() -> None:
    publisher = _Publisher([])
    recorder = _recorder(publisher)

    first = await recorder.advance(
        InventoryProgressStage.COUNT,
        resources_expected=20,
    )
    second = await recorder.advance(
        InventoryProgressStage.COLLECT,
        provider_types_completed=2,
        pages_completed=3,
        pages_expected=5,
        resources_observed=12,
        links_observed=4,
    )

    assert first.previous_digest == INVENTORY_PROGRESS_GENESIS_DIGEST
    assert second.previous_digest == first.record_digest
    assert second.sequence == 2
    assert second.pages_expected == 5
    assert second.fraction_basis is InventoryProgressFractionBasis.PAGES
    assert publisher.records == [first, second]


async def test_recorder_complete_requires_no_later_progress() -> None:
    publisher = _Publisher([])
    recorder = _recorder(publisher)

    await recorder.advance(InventoryProgressStage.COUNT)
    await recorder.advance(
        InventoryProgressStage.VERIFY,
        generation_digest=GENERATION_DIGEST,
    )
    completed = await recorder.complete()

    assert completed.state is InventoryProgressState.COMPLETE
    assert completed.fraction == 1.0
    assert completed.provider_types_completed == 0
    assert completed.provider_types_total == 4
    with pytest.raises(ValueError, match="terminal"):
        await recorder.advance(InventoryProgressStage.VERIFY)


async def test_recorder_is_poisoned_after_ambiguous_publisher_failure() -> None:
    class _FailOncePublisher:
        def __init__(self) -> None:
            self.records: list[InventoryProgressRecord] = []

        async def append(self, record: InventoryProgressRecord) -> bool:
            self.records.append(record)
            if len(self.records) == 1:
                raise RuntimeError("unavailable")
            return True

    publisher = _FailOncePublisher()
    recorder = InventoryProgressRecorder(
        run_id="run.abcdef",
        attempt_id="attempt.1",
        scopes_total=1,
        provider_types_total=0,
        pages_expected=0,
        started_at=NOW,
        deadline_at=NOW + timedelta(minutes=5),
        publisher=publisher,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    with pytest.raises(InventoryProgressUnavailableError, match="unavailable"):
        await recorder.advance(InventoryProgressStage.COUNT)
    with pytest.raises(InventoryProgressUnavailableError, match="ambiguous append"):
        await recorder.advance(InventoryProgressStage.COUNT)

    assert [record.sequence for record in publisher.records] == [1]


async def test_distinct_closer_resumes_exact_chain_at_verified_closure() -> None:
    collected = _Publisher([])
    latest = await _recorder(collected).advance(
        InventoryProgressStage.VERIFY,
        generation_digest=GENERATION_DIGEST,
    )
    finalized = _Publisher([])

    complete = await InventoryProgressRecorder.resume(
        latest,
        publisher=finalized,
        clock=lambda: NOW + timedelta(seconds=2),
    ).complete()

    assert complete.sequence == latest.sequence + 1
    assert complete.previous_digest == latest.record_digest
    assert complete.fraction == 1.0
    assert complete.fraction_basis is InventoryProgressFractionBasis.VERIFIED_CLOSURE


async def test_recorder_rejects_regression_and_sanitizes_failure() -> None:
    publisher = _Publisher([])
    recorder = _recorder(publisher)
    await recorder.advance(
        InventoryProgressStage.COLLECT,
        provider_types_completed=2,
    )

    with pytest.raises(ValueError, match="MUST NOT regress"):
        await recorder.advance(
            InventoryProgressStage.COLLECT,
            provider_types_completed=1,
        )
    failed = await recorder.fail("provider_unavailable")
    assert failed.stage is InventoryProgressStage.FAILED
    assert failed.reason_code == "provider_unavailable"


async def test_composite_publisher_requires_all_sinks_in_order() -> None:
    calls: list[str] = []

    class _OrderedPublisher:
        def __init__(self, name: str) -> None:
            self.name = name

        async def append(self, record: InventoryProgressRecord) -> bool:
            del record
            calls.append(self.name)
            return self.name == "second"

    publisher = _Publisher([])
    record = await _recorder(publisher).advance(InventoryProgressStage.COUNT)
    inserted = await CompositeInventoryProgressPublisher(
        _OrderedPublisher("first"),
        _OrderedPublisher("second"),
    ).append(record)

    assert inserted is True
    assert calls == ["first", "second"]
