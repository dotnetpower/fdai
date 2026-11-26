"""The Pod lifecycle projection keeps four answers apart and fails closed.

Each test states a situation an operator can actually be in and asserts the
projection does not answer a question it was not asked: a healthy read does not
erase history, an absent read does not become health, and an uncertain delivery
is a gap rather than a silence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryStatus,
)
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    KubernetesPodReplacementStatus,
)
from fdai.core.readiness.detection_lifecycle import (
    DETECTION_LIFECYCLE_STATE_PREFIX,
    DetectionEvidenceGap,
    DetectionPublicationState,
    PodLifecycleCurrentState,
    PodLifecycleDetectionRecord,
    PodLifecycleDetectionSnapshot,
    PodLifecycleRecoveryState,
    pod_lifecycle_detection_state_key,
    reduce_pod_lifecycle_detection,
    retain_pod_lifecycle_records,
)
from fdai.delivery.analyzer_tick import AnalyzerPublicationStatus

_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
_REF = "cluster-a/default/orders"


def _record(
    *,
    key: str,
    signal: KubernetesPodReplacementStatus = KubernetesPodReplacementStatus.CONTAINER_RESTART,
    recorded_at: datetime = _NOW,
    evidence_complete: bool = True,
    recovery_closed: bool | None = False,
    recovery_status: KubernetesPodRecoveryStatus | None = (
        KubernetesPodRecoveryStatus.NOT_RECOVERED
    ),
    publication: DetectionPublicationState = DetectionPublicationState.PUBLISHED,
    assessed_by: str | None = "core.ontology_platform.kubernetes_pod_lifecycle",
    resource_ref: str = _REF,
    evidence_gaps: tuple[str, ...] = (),
) -> PodLifecycleDetectionRecord:
    return PodLifecycleDetectionRecord(
        resource_ref=resource_ref,
        idempotency_key=key,
        signal=signal,
        occurred_at=recorded_at - timedelta(seconds=12),
        recorded_at=recorded_at,
        detection_latency_seconds=12.0,
        evidence_complete=evidence_complete,
        recovery_closed=recovery_closed,
        recovery_status=recovery_status,
        publication=publication,
        assessed_by=assessed_by,
        evidence_refs=("pod-old", "termination-old"),
        evidence_gaps=evidence_gaps,
    )


def test_every_delivery_outcome_is_nameable_in_the_projection() -> None:
    """A new delivery outcome MUST NOT reach an operator unnamed."""

    assert {state.value for state in DetectionPublicationState} == {
        status.value for status in AnalyzerPublicationStatus
    }


def test_no_record_reports_unknown_with_a_missing_evidence_gap() -> None:
    snapshot = reduce_pod_lifecycle_detection((), resource_ref=_REF, generated_at=_NOW)

    assert snapshot.current_state is PodLifecycleCurrentState.UNKNOWN
    assert snapshot.recovery_state is PodLifecycleRecoveryState.UNKNOWN
    assert snapshot.evidence_gaps == (DetectionEvidenceGap.MISSING_EVIDENCE,)
    assert snapshot.failure_count == 0
    assert snapshot.cause_claim_supported is False
    assert snapshot.execution_authority is False


def test_expired_evidence_reports_unknown_instead_of_the_last_answer() -> None:
    stale = _record(key="restart-1", recorded_at=_NOW - timedelta(hours=2))

    snapshot = reduce_pod_lifecycle_detection(
        (stale,),
        resource_ref=_REF,
        generated_at=_NOW,
        freshness_budget=timedelta(minutes=15),
    )

    assert snapshot.current_state is PodLifecycleCurrentState.UNKNOWN
    assert snapshot.current_signal is None
    assert snapshot.evidence_gaps == (DetectionEvidenceGap.STALE_EVIDENCE,)
    assert snapshot.failure_count == 1


def test_a_complete_unrecovered_restart_reports_failing_and_not_verified() -> None:
    snapshot = reduce_pod_lifecycle_detection(
        (_record(key="restart-1"),),
        resource_ref=_REF,
        generated_at=_NOW,
    )

    assert snapshot.current_state is PodLifecycleCurrentState.FAILING
    assert snapshot.current_signal is KubernetesPodReplacementStatus.CONTAINER_RESTART
    assert snapshot.recovery_state is PodLifecycleRecoveryState.NOT_VERIFIED
    assert snapshot.recovery_verified_at is None
    assert snapshot.evidence_gaps == ()


def test_recovery_is_reported_only_when_an_independent_observation_closed_it() -> None:
    snapshot = reduce_pod_lifecycle_detection(
        (
            _record(
                key="replacement-1",
                signal=KubernetesPodReplacementStatus.POD_REPLACEMENT,
                recovery_closed=True,
                recovery_status=KubernetesPodRecoveryStatus.RECOVERED,
            ),
        ),
        resource_ref=_REF,
        generated_at=_NOW,
    )

    assert snapshot.current_state is PodLifecycleCurrentState.RECOVERED
    assert snapshot.recovery_state is PodLifecycleRecoveryState.VERIFIED
    assert snapshot.recovery_verified_at == _NOW


def test_recovery_does_not_erase_the_failure_that_preceded_it() -> None:
    earlier = _record(key="restart-1", recorded_at=_NOW - timedelta(minutes=5))
    recovered = _record(
        key="restart-2",
        recovery_closed=True,
        recovery_status=KubernetesPodRecoveryStatus.RECOVERED,
    )

    snapshot = reduce_pod_lifecycle_detection(
        (earlier, recovered),
        resource_ref=_REF,
        generated_at=_NOW,
    )

    assert snapshot.current_state is PodLifecycleCurrentState.RECOVERED
    assert snapshot.failure_count == 2
    assert [failure.idempotency_key for failure in snapshot.failures] == [
        "restart-2",
        "restart-1",
    ]


def test_incomplete_evidence_is_a_gap_rather_than_a_healthy_read() -> None:
    snapshot = reduce_pod_lifecycle_detection(
        (
            _record(
                key="restart-1",
                evidence_complete=False,
                recovery_closed=False,
                recovery_status=KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE,
                evidence_gaps=("restart_history_retention_gap",),
            ),
        ),
        resource_ref=_REF,
        generated_at=_NOW,
    )

    assert snapshot.current_state is PodLifecycleCurrentState.UNKNOWN
    assert snapshot.recovery_state is PodLifecycleRecoveryState.UNKNOWN
    assert snapshot.evidence_gaps == (DetectionEvidenceGap.INCOMPLETE_EVIDENCE,)
    assert snapshot.evidence_gap_details == ("restart_history_retention_gap",)


@pytest.mark.parametrize(
    ("signal", "recovery_status"),
    [
        (
            KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE,
            KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE,
        ),
        (
            KubernetesPodReplacementStatus.CONTAINER_RESTART,
            KubernetesPodRecoveryStatus.CONFLICTING_EVIDENCE,
        ),
    ],
)
def test_conflicting_sources_never_collapse_into_one_verdict(
    signal: KubernetesPodReplacementStatus,
    recovery_status: KubernetesPodRecoveryStatus,
) -> None:
    snapshot = reduce_pod_lifecycle_detection(
        (
            _record(
                key="conflict-1",
                signal=signal,
                evidence_complete=False,
                recovery_closed=False,
                recovery_status=recovery_status,
            ),
        ),
        resource_ref=_REF,
        generated_at=_NOW,
    )

    assert snapshot.current_state is PodLifecycleCurrentState.UNKNOWN
    assert snapshot.evidence_gaps == (DetectionEvidenceGap.CONFLICTING_EVIDENCE,)


def test_an_uncertain_delivery_is_reported_as_a_gap() -> None:
    snapshot = reduce_pod_lifecycle_detection(
        (_record(key="restart-1", publication=DetectionPublicationState.UNCERTAIN),),
        resource_ref=_REF,
        generated_at=_NOW,
    )

    assert DetectionEvidenceGap.DELIVERY_UNCERTAIN in snapshot.evidence_gaps
    assert snapshot.delivery_counts[DetectionPublicationState.UNCERTAIN] == 1
    assert snapshot.current_state is PodLifecycleCurrentState.FAILING


def test_a_failed_delivery_is_reported_separately_from_an_uncertain_one() -> None:
    snapshot = reduce_pod_lifecycle_detection(
        (_record(key="restart-1", publication=DetectionPublicationState.FAILED),),
        resource_ref=_REF,
        generated_at=_NOW,
    )

    assert snapshot.evidence_gaps == (DetectionEvidenceGap.DELIVERY_FAILED,)


def test_an_unassessed_finding_is_named_rather_than_projected() -> None:
    snapshot = reduce_pod_lifecycle_detection(
        (_record(key="restart-1", assessed_by=None, recovery_closed=None, recovery_status=None),),
        resource_ref=_REF,
        generated_at=_NOW,
    )

    assert snapshot.evidence_gaps == (DetectionEvidenceGap.UNASSESSED_FINDING,)
    assert snapshot.current_state is PodLifecycleCurrentState.UNKNOWN


def test_a_repeated_window_key_counts_once_and_keeps_the_newest_outcome() -> None:
    suppressed = _record(
        key="restart-1",
        recorded_at=_NOW,
        publication=DetectionPublicationState.DUPLICATE_SUPPRESSED,
    )
    published = _record(
        key="restart-1",
        recorded_at=_NOW - timedelta(minutes=1),
        publication=DetectionPublicationState.PUBLISHED,
    )

    retained = retain_pod_lifecycle_records((published, suppressed), resource_ref=_REF)

    assert len(retained) == 1
    assert retained[0].publication is DetectionPublicationState.DUPLICATE_SUPPRESSED


def test_retention_keeps_the_newest_records_within_its_bound() -> None:
    records = tuple(
        _record(key=f"restart-{index}", recorded_at=_NOW - timedelta(minutes=index))
        for index in range(6)
    )

    retained = retain_pod_lifecycle_records(records, resource_ref=_REF, retention=3)

    assert [record.idempotency_key for record in retained] == [
        "restart-0",
        "restart-1",
        "restart-2",
    ]


def test_another_target_is_never_folded_into_this_projection() -> None:
    retained = retain_pod_lifecycle_records(
        (_record(key="restart-1", resource_ref="cluster-a/default/other"),),
        resource_ref=_REF,
    )

    assert retained == ()


def test_a_snapshot_may_not_claim_a_cause_or_authority() -> None:
    snapshot = reduce_pod_lifecycle_detection((), resource_ref=_REF, generated_at=_NOW)
    payload = snapshot.model_dump(mode="json")

    for field in ("cause_claim_supported", "execution_authority"):
        with pytest.raises(ValueError, match="MUST NOT claim cause or authority"):
            PodLifecycleDetectionSnapshot.model_validate({**payload, field: True})


def test_a_naive_projection_time_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        reduce_pod_lifecycle_detection(
            (),
            resource_ref=_REF,
            generated_at=datetime(2026, 8, 31, 12, 0),  # noqa: DTZ001 - the refusal is the test
        )


def test_the_state_key_is_stable_and_namespaced() -> None:
    key = pod_lifecycle_detection_state_key(_REF)

    assert key.startswith(DETECTION_LIFECYCLE_STATE_PREFIX)
    assert key == pod_lifecycle_detection_state_key(_REF)
    assert key != pod_lifecycle_detection_state_key(f"{_REF}-other")


def test_a_reconciliation_replaces_the_uncertain_outcome_it_settles() -> None:
    """The same instant is a re-observation, not a second failure."""

    uncertain = _record(key="restart-1", publication=DetectionPublicationState.UNCERTAIN)
    reconciled = _record(key="restart-1", publication=DetectionPublicationState.PUBLISHED)

    retained = retain_pod_lifecycle_records((uncertain, reconciled), resource_ref=_REF)

    assert len(retained) == 1
    assert retained[0].publication is DetectionPublicationState.PUBLISHED
