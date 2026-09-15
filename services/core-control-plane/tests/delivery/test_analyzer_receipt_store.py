from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.analyzer_receipt_store import (
    ANALYZER_RECEIPT_STATE_PREFIX,
    ANALYZER_RUN_RECEIPT_STATE_PREFIX,
    StateStoreAnalyzerReceiptStore,
    StateStoreAnalyzerRunReceiptStore,
)
from fdai.delivery.analyzer_tick import (
    AnalyzerEvidenceState,
    AnalyzerFindingReceipt,
    AnalyzerPublicationStatus,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 8, 31, 7, 0, tzinfo=UTC)


def _receipt(
    key: str,
    publication: AnalyzerPublicationStatus,
) -> AnalyzerFindingReceipt:
    return AnalyzerFindingReceipt(
        idempotency_key=key,
        resource_ref="cluster/example/pod/orders",
        resource_kind="kubernetes_pod",
        signal="pod_replacement",
        occurred_at=NOW,
        recorded_at=NOW,
        current_state="running",
        detection_latency_seconds=4.0,
        evidence_complete=True,
        evidence_state=AnalyzerEvidenceState.COMPLETE,
        publication=publication,
        recovery_closed=True,
        evidence_refs=("pod-old", "pod-new"),
    )


async def test_store_retains_publication_and_duplicate_as_distinct_bounded_receipts() -> None:
    state = InMemoryStateStore()
    store = StateStoreAnalyzerReceiptStore(state, retain_newest=2)

    await store.record(_receipt("analyzer:key-1", AnalyzerPublicationStatus.PUBLISHED))
    await store.record(_receipt("analyzer:key-1", AnalyzerPublicationStatus.DUPLICATE_SUPPRESSED))
    await store.record(_receipt("analyzer:key-2", AnalyzerPublicationStatus.PUBLISHED))

    records = await state.read_states(ANALYZER_RECEIPT_STATE_PREFIX, limit=10)

    assert len(records) == 2
    assert {record["idempotency_key"] for record in records} == {
        "analyzer:key-1",
        "analyzer:key-2",
    }
    assert records[0]["cause_claim_supported"] is False
    assert records[0]["execution_authority"] is False


async def test_store_rejects_rewriting_an_immutable_receipt_identity() -> None:
    state = InMemoryStateStore()
    store = StateStoreAnalyzerReceiptStore(state)
    receipt = _receipt("analyzer:key-1", AnalyzerPublicationStatus.PUBLISHED)
    await store.record(receipt)

    with pytest.raises(ValueError, match="identity collision"):
        await store.record(replace(receipt, current_state="terminated"))


async def test_store_keeps_the_first_observation_of_a_repeated_outcome() -> None:
    state = InMemoryStateStore()
    store = StateStoreAnalyzerReceiptStore(state)
    first = _receipt("analyzer:key-1", AnalyzerPublicationStatus.DUPLICATE_SUPPRESSED)

    await store.record(first)
    await store.record(
        replace(
            first,
            recorded_at=NOW + timedelta(seconds=120),
            detection_latency_seconds=124.0,
        )
    )

    records = await state.read_states(ANALYZER_RECEIPT_STATE_PREFIX, limit=10)

    assert len(records) == 1
    assert records[0]["recorded_at"] == NOW.isoformat()
    assert records[0]["detection_latency_seconds"] == 4.0


async def test_store_still_rejects_a_conflicting_repeat_with_later_timing() -> None:
    state = InMemoryStateStore()
    store = StateStoreAnalyzerReceiptStore(state)
    receipt = _receipt("analyzer:key-1", AnalyzerPublicationStatus.PUBLISHED)
    await store.record(receipt)

    with pytest.raises(ValueError, match="identity collision"):
        await store.record(
            replace(
                receipt,
                current_state="terminated",
                recorded_at=NOW + timedelta(seconds=60),
                detection_latency_seconds=64.0,
            )
        )


async def test_run_store_retains_complete_tick_reports_without_authority() -> None:
    state = InMemoryStateStore()
    store = StateStoreAnalyzerRunReceiptStore(state, retain_newest=2)

    for index in range(3):
        await store.record(
            run_id=f"run-{index}",
            recorded_at=NOW + timedelta(seconds=index),
            report={
                "targets": 2,
                "target_resolution": {
                    "configured": 1,
                    "discovered": 1,
                    "inventory_consulted": True,
                    "skipped_reasons": [],
                    "truncated": False,
                },
            },
        )

    records = await state.read_states(ANALYZER_RUN_RECEIPT_STATE_PREFIX, limit=10)

    assert len(records) == 2
    assert {record["run_id"] for record in records} == {"run-1", "run-2"}
    assert {record["schema_version"] for record in records} == {"1.3.0"}
    assert all(record["execution_authority"] is False for record in records)
    assert all(len(str(record["report_digest"])) == 64 for record in records)


async def test_run_store_retains_changed_retry_as_another_content_addressed_attempt() -> None:
    state = InMemoryStateStore()
    store = StateStoreAnalyzerRunReceiptStore(state)
    await store.record(run_id="run-1", recorded_at=NOW, report={"targets": 1})
    await store.record(
        run_id="run-1",
        recorded_at=NOW + timedelta(minutes=1),
        report={"targets": 2},
    )

    records = await state.read_states(ANALYZER_RUN_RECEIPT_STATE_PREFIX, limit=10)

    assert len(records) == 2
    assert {record["run_id"] for record in records} == {"run-1"}
    assert len({record["attempt_id"] for record in records}) == 2


async def test_run_store_keeps_first_time_for_an_idempotent_retry() -> None:
    state = InMemoryStateStore()
    store = StateStoreAnalyzerRunReceiptStore(state)
    await store.record(run_id="run-1", recorded_at=NOW, report={"targets": 1})
    await store.record(
        run_id="run-1",
        recorded_at=NOW + timedelta(minutes=1),
        report={"targets": 1},
    )

    records = await state.read_states(ANALYZER_RUN_RECEIPT_STATE_PREFIX, limit=10)

    assert len(records) == 1
    assert records[0]["recorded_at"] == NOW.isoformat()
    assert records[0]["attempt_id"] == records[0]["report_digest"]


async def test_run_store_retains_identical_reports_from_distinct_ticks() -> None:
    state = InMemoryStateStore()
    store = StateStoreAnalyzerRunReceiptStore(state)
    await store.record(
        run_id="run-1",
        tick_id="0",
        recorded_at=NOW,
        report={"targets": 1},
    )
    await store.record(
        run_id="run-1",
        tick_id="1",
        recorded_at=NOW + timedelta(minutes=1),
        report={"targets": 1},
    )

    records = await state.read_states(ANALYZER_RUN_RECEIPT_STATE_PREFIX, limit=10)

    assert len(records) == 2
    assert {record["tick_id"] for record in records} == {"0", "1"}
