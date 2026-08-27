"""Deterministic immutable Pod replacement correlation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    KubernetesPodReplacementEvidenceResult,
    KubernetesPodReplacementStatus,
    PodLifecycleObservation,
    PodReplacementDeploymentObservation,
    PodTerminationObservation,
    evaluate_kubernetes_pod_replacement,
)
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_CUTOFF = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
_WINDOW_START = _CUTOFF - timedelta(minutes=30)


def _metadata(at: datetime, *, conflicts: tuple[str, ...] = ()) -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="kubernetes-api-inventory",
        source_revision="resource-version-10",
        effective_at=at,
        recorded_at=at,
        evidence_cutoff=at,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        conflicts=conflicts,
        evidence_refs=(f"kubernetes:{at.isoformat()}",),
    )


def _old_pod(**updates: object) -> PodLifecycleObservation:
    values: dict[str, object] = {
        "pod_id": "pod/old",
        "pod_uid": "pod-uid-old",
        "cluster_id": "cluster-a",
        "namespace": "default",
        "owner_uid": "replicaset-uid-a",
        "root_controller_uid": "deployment-uid-a",
        "root_controller_kind": "Deployment",
        "created_at": _WINDOW_START - timedelta(hours=1),
        "phase": "Failed",
        "ready": False,
        "container_count": 1,
        "ready_container_count": 0,
        "waiting_reasons": (),
        "workload_revision": None,
        "metadata": _metadata(_CUTOFF - timedelta(minutes=10)),
        "evidence_refs": ("pod-old",),
    }
    values.update(updates)
    return PodLifecycleObservation(**values)  # type: ignore[arg-type]


def _new_pod(**updates: object) -> PodLifecycleObservation:
    values: dict[str, object] = {
        "pod_id": "pod/new",
        "pod_uid": "pod-uid-new",
        "cluster_id": "cluster-a",
        "namespace": "default",
        "owner_uid": "replicaset-uid-a",
        "root_controller_uid": "deployment-uid-a",
        "root_controller_kind": "Deployment",
        "created_at": _CUTOFF - timedelta(minutes=4),
        "phase": "Running",
        "ready": True,
        "container_count": 1,
        "ready_container_count": 1,
        "waiting_reasons": (),
        "workload_revision": None,
        "metadata": _metadata(_CUTOFF),
        "evidence_refs": ("pod-new",),
    }
    values.update(updates)
    return PodLifecycleObservation(**values)  # type: ignore[arg-type]


def _termination(**updates: object) -> PodTerminationObservation:
    values: dict[str, object] = {
        "pod_uid": "pod-uid-old",
        "event_type": "Failed",
        "reason": "OOMKilled",
        "exit_code": 137,
        "event_time": _CUTOFF - timedelta(minutes=5),
        "recorded_at": _CUTOFF - timedelta(minutes=5),
        "source_identity": "kubernetes-event-watch",
        "evidence_refs": ("termination-old",),
    }
    values.update(updates)
    return PodTerminationObservation(**values)  # type: ignore[arg-type]


def _deployment(**updates: object) -> PodReplacementDeploymentObservation:
    values: dict[str, object] = {
        "deployment_id": "deployment/orders",
        "desired_replicas_before": 1,
        "desired_replicas_after": 1,
        "ready_replicas": 1,
        "available_replicas": 1,
        "unavailable_replicas": 0,
        "metadata": _metadata(_CUTOFF),
        "evidence_refs": ("deployment-current",),
    }
    values.update(updates)
    return PodReplacementDeploymentObservation(**values)  # type: ignore[arg-type]


def _evaluate(
    *,
    old_pod: PodLifecycleObservation | None = None,
    candidates: tuple[PodLifecycleObservation, ...] | None = None,
    termination: PodTerminationObservation | None = None,
    deployment: PodReplacementDeploymentObservation | None = None,
) -> KubernetesPodReplacementEvidenceResult:
    return evaluate_kubernetes_pod_replacement(
        old_pod=old_pod or _old_pod(),
        candidates=candidates or (_new_pod(),),
        termination=termination or _termination(),
        deployment=deployment or _deployment(),
        correlation_window_start=_WINDOW_START,
        cutoff=_CUTOFF,
    )


def test_abnormal_distinct_uid_replacement_is_correlated_and_recovered() -> None:
    result = _evaluate()

    assert result.status is KubernetesPodReplacementStatus.POD_REPLACEMENT
    assert result.complete is True
    assert result.replacement_supported is True
    assert result.abnormal_replacement_supported is True
    assert result.recovery_verified is True
    assert result.old_pod_uid == "pod-uid-old"
    assert result.new_pod_uid == "pod-uid-new"
    assert result.cause_claim_supported is False
    assert result.execution_authority is False


def test_same_uid_is_classified_as_container_restart() -> None:
    result = _evaluate(candidates=(replace(_new_pod(), pod_uid="pod-uid-old"),))

    assert result.status is KubernetesPodReplacementStatus.CONTAINER_RESTART
    assert result.replacement_supported is False


def test_new_replica_set_under_same_deployment_is_rollout_replacement() -> None:
    result = _evaluate(
        candidates=(
            replace(
                _new_pod(),
                owner_uid="replicaset-uid-b",
                created_at=_CUTOFF - timedelta(minutes=6),
            ),
        ),
        termination=replace(
            _termination(),
            event_time=_CUTOFF - timedelta(minutes=5),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.ROLLOUT_REPLACEMENT
    assert result.replacement_supported is True
    assert result.abnormal_replacement_supported is False


def test_unrelated_pod_is_not_admitted_as_replacement() -> None:
    result = _evaluate(
        candidates=(replace(_new_pod(), root_controller_uid="deployment-uid-other"),),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert result.evidence_gaps == ("no_replacement_candidate",)


def test_multiple_matching_candidates_fail_closed() -> None:
    result = _evaluate(
        candidates=(
            _new_pod(),
            replace(_new_pod(), pod_id="pod/new-2", pod_uid="pod-uid-new-2"),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_gaps == ("ambiguous_replacement_candidates",)


def test_missing_verified_owner_identity_fails_closed() -> None:
    result = _evaluate(old_pod=replace(_old_pod(), owner_uid=None))

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert "old_owner_uid_unavailable" in result.evidence_gaps


def test_termination_must_precede_creation_by_ordering_margin() -> None:
    result = _evaluate(
        termination=replace(
            _termination(),
            event_time=_new_pod().created_at,
        )
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert "termination_ordering_unproven" in result.evidence_gaps


def test_scale_change_does_not_support_abnormal_replacement() -> None:
    result = _evaluate(
        termination=replace(_termination(), event_type="Killing", reason="Completed", exit_code=0),
        deployment=replace(_deployment(), desired_replicas_before=2, desired_replicas_after=1),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.abnormal_replacement_supported is False
    assert "abnormal_replacement_unproven" in result.evidence_gaps


def test_same_name_statefulset_recreation_requires_same_root_uid() -> None:
    result = _evaluate(
        old_pod=replace(
            _old_pod(),
            pod_id="pod/orders-0",
            root_controller_uid="statefulset-uid-old",
            root_controller_kind="StatefulSet",
        ),
        candidates=(
            replace(
                _new_pod(),
                pod_id="pod/orders-0",
                root_controller_uid="statefulset-uid-new",
                root_controller_kind="StatefulSet",
            ),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_gaps == ("no_replacement_candidate",)


def test_historical_observation_uses_window_not_current_freshness() -> None:
    result = _evaluate()

    assert "historical_evidence_stale" not in result.evidence_gaps
    assert result.status is KubernetesPodReplacementStatus.POD_REPLACEMENT


def test_stale_current_pod_and_deployment_cannot_verify_recovery() -> None:
    stale = replace(
        _metadata(_CUTOFF - timedelta(minutes=10)),
        evidence_cutoff=_CUTOFF - timedelta(minutes=10),
    )
    result = _evaluate(
        candidates=(replace(_new_pod(), metadata=stale),),
        deployment=replace(_deployment(), metadata=stale),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.recovery_verified is False
    assert "current_pod_evidence_stale" in result.evidence_gaps
    assert "deployment_evidence_stale" in result.evidence_gaps


def test_recovery_requires_ready_containers_and_matching_deployment_replicas() -> None:
    result = _evaluate(
        candidates=(
            replace(
                _new_pod(),
                ready=False,
                ready_container_count=0,
                waiting_reasons=("CrashLoopBackOff",),
            ),
        ),
        deployment=replace(
            _deployment(),
            desired_replicas_before=2,
            desired_replicas_after=2,
            ready_replicas=1,
            available_replicas=1,
            unavailable_replicas=1,
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.POD_REPLACEMENT
    assert result.recovery_verified is False


def test_result_round_trip_preserves_replay_inputs() -> None:
    result = _evaluate()

    replayed = KubernetesPodReplacementEvidenceResult.model_validate(result.model_dump(mode="json"))

    assert replayed == result
    assert replayed.historical_evidence_refs == ("pod-old", "termination-old")
    assert replayed.current_evidence_refs == ("deployment-current", "pod-new")
