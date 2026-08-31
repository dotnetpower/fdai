from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.delivery.analyzer_receipt_store import (
    ANALYZER_RECEIPT_STATE_PREFIX,
    StateStoreAnalyzerReceiptStore,
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
