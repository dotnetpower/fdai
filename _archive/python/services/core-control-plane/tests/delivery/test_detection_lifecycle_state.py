"""The tick persists what it detected, or it fails.

An operator surface reads tracked state, not a process that already exited.
These tests hold the recorder to three promises: history survives a later
healthy tick, an unreadable or unwritable projection stops the tick instead of
freezing a stale answer, and a receipt this projection cannot speak about is
skipped rather than guessed at.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.investigation.kubernetes_pod import KIND_KUBERNETES_POD
from fdai.core.readiness.detection_lifecycle import (
    DETECTION_LIFECYCLE_SCHEMA_VERSION,
    PodLifecycleCurrentState,
    PodLifecycleRecoveryState,
    pod_lifecycle_detection_state_key,
)
from fdai.delivery.analyzer_tick import (
    AnalyzerFindingReceipt,
    AnalyzerPublicationStatus,
    AnalyzerTickReport,
)
from fdai.delivery.detection_lifecycle_state import (
    DetectionLifecycleRecorder,
    DetectionLifecycleRecordError,
    pod_lifecycle_record,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
_REF = "cluster-a/default/orders"


def _receipt(
    *,
    key: str,
    signal: str = "container_restart",
    resource_kind: str = KIND_KUBERNETES_POD,
    recovery_closed: bool | None = False,
    recovery_status: str | None = "restart_observed_not_recovered",
    evidence_complete: bool = True,
    publication: AnalyzerPublicationStatus = AnalyzerPublicationStatus.PUBLISHED,
    occurred_at: datetime = _NOW - timedelta(seconds=12),
    resource_ref: str = _REF,
) -> AnalyzerFindingReceipt:
    return AnalyzerFindingReceipt(
        idempotency_key=key,
        signal=signal,
        resource_ref=resource_ref,
        resource_kind=resource_kind,
        occurred_at=occurred_at,
        detection_latency_seconds=12.0,
        evidence_complete=evidence_complete,
        publication=publication,
        recovery_closed=recovery_closed,
        recovery_status=recovery_status,
        evidence_refs=("pod-old",),
        assessed_by="core.ontology_platform.kubernetes_pod_lifecycle",
        evidence_gaps=(),
    )


class _FailingStore(InMemoryStateStore):
    """Fail one state-store operation the way an outage would."""

    def __init__(self, *, on_read: bool = False, on_write: bool = False) -> None:
        super().__init__()
        self._on_read = on_read
        self._on_write = on_write

    async def read_state(self, key: str) -> Any:
        if self._on_read:
            raise TimeoutError("state read timed out")
        return await super().read_state(key)

    async def write_state(self, key: str, value: Any) -> None:
        if self._on_write:
            raise TimeoutError("state write timed out")
        await super().write_state(key, value)


async def test_a_pod_receipt_is_persisted_as_a_readable_projection() -> None:
    store = InMemoryStateStore()
    recorder = DetectionLifecycleRecorder(store)

    snapshots = await recorder.record_receipts([_receipt(key="restart-1")], at=_NOW)

    assert [snapshot.resource_ref for snapshot in snapshots] == [_REF]
    assert snapshots[0].current_state is PodLifecycleCurrentState.FAILING
    stored = await store.read_state(pod_lifecycle_detection_state_key(_REF))
    assert stored is not None
    assert stored["schema_version"] == DETECTION_LIFECYCLE_SCHEMA_VERSION
    assert await recorder.read_snapshot(_REF) == snapshots[0]


async def test_a_later_healthy_tick_adds_to_history_instead_of_erasing_it() -> None:
    recorder = DetectionLifecycleRecorder(InMemoryStateStore())
    await recorder.record_receipts([_receipt(key="restart-1")], at=_NOW)

    recovered = await recorder.record_receipts(
        [
            _receipt(
                key="restart-2",
                recovery_closed=True,
                recovery_status="restart_observed_recovered",
            )
        ],
        at=_NOW + timedelta(minutes=1),
    )

    assert recovered[0].current_state is PodLifecycleCurrentState.RECOVERED
    assert recovered[0].recovery_state is PodLifecycleRecoveryState.VERIFIED
    assert recovered[0].failure_count == 2
    assert recovered[0].retained_record_count == 2


async def test_a_repeated_window_is_reconciled_instead_of_counted_twice() -> None:
    recorder = DetectionLifecycleRecorder(InMemoryStateStore())
    await recorder.record_receipts([_receipt(key="restart-1")], at=_NOW)

    repeated = await recorder.record_receipts(
        [_receipt(key="restart-1", publication=AnalyzerPublicationStatus.DUPLICATE_SUPPRESSED)],
        at=_NOW + timedelta(minutes=1),
    )

    assert repeated[0].retained_record_count == 1
    assert repeated[0].failure_count == 1
    counts = {state.value: count for state, count in repeated[0].delivery_counts.items()}
    assert counts["duplicate_suppressed"] == 1
    assert counts["published"] == 0


async def test_retention_stays_bounded_across_ticks() -> None:
    recorder = DetectionLifecycleRecorder(InMemoryStateStore(), retention=2)

    for index in range(4):
        snapshot = (
            await recorder.record_receipts(
                [_receipt(key=f"restart-{index}")],
                at=_NOW + timedelta(minutes=index),
            )
        )[0]

    assert snapshot.retained_record_count == 2
    assert [failure.idempotency_key for failure in snapshot.failures] == [
        "restart-3",
        "restart-2",
    ]


async def test_a_receipt_for_another_kind_is_not_projected_as_a_pod() -> None:
    recorder = DetectionLifecycleRecorder(InMemoryStateStore())

    snapshots = await recorder.record_receipts(
        [_receipt(key="threshold-1", resource_kind="azure_metric", signal="threshold_breach")],
        at=_NOW,
    )

    assert snapshots == ()


async def test_a_non_lifecycle_signal_is_skipped_rather_than_coerced() -> None:
    assert (
        pod_lifecycle_record(_receipt(key="odd-1", signal="threshold_breach"), recorded_at=_NOW)
        is None
    )


async def test_an_unknown_recovery_status_fails_closed() -> None:
    with pytest.raises(DetectionLifecycleRecordError, match="unknown Pod recovery status"):
        pod_lifecycle_record(
            _receipt(key="restart-1", recovery_status="probably_fine"),
            recorded_at=_NOW,
        )


async def test_a_write_failure_fails_the_tick() -> None:
    recorder = DetectionLifecycleRecorder(_FailingStore(on_write=True))

    with pytest.raises(DetectionLifecycleRecordError, match="was not persisted"):
        await recorder.record_receipts([_receipt(key="restart-1")], at=_NOW)


async def test_an_unreadable_history_is_never_silently_replaced() -> None:
    recorder = DetectionLifecycleRecorder(_FailingStore(on_read=True))

    with pytest.raises(DetectionLifecycleRecordError, match="could not be read"):
        await recorder.record_receipts([_receipt(key="restart-1")], at=_NOW)


async def test_an_unsupported_stored_schema_is_refused() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        pod_lifecycle_detection_state_key(_REF),
        {"schema_version": 99, "resource_ref": _REF, "snapshot": {}, "records": []},
    )
    recorder = DetectionLifecycleRecorder(store)

    with pytest.raises(DetectionLifecycleRecordError, match="unsupported schema"):
        await recorder.record_receipts([_receipt(key="restart-1")], at=_NOW)


async def test_a_tick_report_persists_every_pod_target_it_observed() -> None:
    recorder = DetectionLifecycleRecorder(InMemoryStateStore())
    report = AnalyzerTickReport(
        targets=2,
        findings=2,
        published=2,
        receipts=(
            _receipt(key="restart-1"),
            _receipt(key="replacement-1", resource_ref="cluster-a/default/payments"),
        ),
    )

    snapshots = await recorder.record_report(report, at=_NOW)

    assert [snapshot.resource_ref for snapshot in snapshots] == [
        "cluster-a/default/orders",
        "cluster-a/default/payments",
    ]


async def test_a_tick_without_pod_receipts_leaves_the_projection_untouched() -> None:
    """Silence is not an observation, so it MUST NOT rewrite the last one.

    The stored projection keeps its own ``generated_at`` and freshness budget;
    withdrawing a state that outlived that budget is the reading surface's job,
    which ``test_detection_lifecycle_projection`` covers.
    """

    recorder = DetectionLifecycleRecorder(
        InMemoryStateStore(),
        freshness_budget=timedelta(minutes=15),
    )
    first = (await recorder.record_receipts([_receipt(key="restart-1")], at=_NOW))[0]

    assert await recorder.record_receipts([], at=_NOW + timedelta(hours=3)) == ()
    assert await recorder.read_snapshot(_REF) == first
