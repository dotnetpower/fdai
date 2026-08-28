"""Deterministic immutable Pod replacement correlation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    DeploymentReplicaObservation,
    KubernetesPodReplacementEvidenceResult,
    KubernetesPodReplacementStatus,
    PodLifecycleObservation,
    PodReplacementDeploymentObservation,
    PodTerminationObservation,
    evaluate_kubernetes_pod_replacement,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_CUTOFF = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
_WINDOW_START = _CUTOFF - timedelta(minutes=30)


def _metadata(
    at: datetime,
    *,
    conflicts: tuple[str, ...] = (),
    lane: StateFactLane = StateFactLane.OBSERVED,
    authority: StateFactAuthority = StateFactAuthority.PROVIDER,
) -> StateFactMetadata:
    return StateFactMetadata(
        lane=lane,
        authority=authority,
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


def _verified_link(at: datetime, *, suffix: str) -> LinkObservationMetadata:
    return LinkObservationMetadata(
        state_fact=_metadata(at),
        verification_method="independent-source",
        verified=True,
        verifier_identity="kubernetes-link-verifier",
        verifier_revision="verifier-v1",
        verification_receipt_ref=f"link-verification:{suffix}",
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
        "owner_link": _verified_link(_CUTOFF - timedelta(minutes=10), suffix="old-owner"),
        "root_controller_link": _verified_link(
            _CUTOFF - timedelta(minutes=10),
            suffix="old-root",
        ),
        "created_at": _WINDOW_START - timedelta(hours=1),
        "phase": "Failed",
        "ready": False,
        "container_count": 1,
        "ready_container_count": 0,
        "restart_count": 0,
        "waiting_reasons": (),
        "workload_revision": "revision-a",
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
        "owner_link": _verified_link(_CUTOFF, suffix="new-owner"),
        "root_controller_link": _verified_link(_CUTOFF, suffix="new-root"),
        "created_at": _CUTOFF - timedelta(minutes=4),
        "phase": "Running",
        "ready": True,
        "container_count": 1,
        "ready_container_count": 1,
        "restart_count": 0,
        "waiting_reasons": (),
        "workload_revision": "revision-a",
        "metadata": _metadata(_CUTOFF),
        "evidence_refs": ("pod-new",),
    }
    values.update(updates)
    return PodLifecycleObservation(**values)  # type: ignore[arg-type]


def _termination(**updates: object) -> PodTerminationObservation:
    values: dict[str, object] = {
        "pod_uid": "pod-uid-old",
        "cluster_id": "cluster-a",
        "namespace": "default",
        "event_type": "Failed",
        "reason": "OOMKilled",
        "exit_code": 137,
        "event_time": _CUTOFF - timedelta(minutes=5),
        "recorded_at": _CUTOFF - timedelta(minutes=5),
        "source_identity": "kubernetes-event-watch",
        "source_revision": "resource-version-20",
        "evidence_refs": ("termination-old",),
    }
    values.update(updates)
    return PodTerminationObservation(**values)  # type: ignore[arg-type]


def _replica_history(
    before: int,
    after: int,
) -> tuple[DeploymentReplicaObservation, ...]:
    return (
        DeploymentReplicaObservation(
            observed_at=_WINDOW_START,
            desired_replicas=before,
        ),
        DeploymentReplicaObservation(
            observed_at=_CUTOFF,
            desired_replicas=after,
        ),
    )


def _deployment(**updates: object) -> PodReplacementDeploymentObservation:
    values: dict[str, object] = {
        "deployment_id": "deployment/orders",
        "deployment_uid": "deployment-uid-a",
        "cluster_id": "cluster-a",
        "namespace": "default",
        "desired_replicas_before": 1,
        "desired_replicas_after": 1,
        "desired_replica_history": _replica_history(1, 1),
        "replica_history_complete": True,
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
    old_pod = _old_pod()
    result = _evaluate(
        old_pod=old_pod,
        candidates=(
            replace(
                _new_pod(),
                pod_id=old_pod.pod_id,
                pod_uid=old_pod.pod_uid,
                created_at=old_pod.created_at,
                restart_count=1,
            ),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.CONTAINER_RESTART
    assert result.replacement_supported is False


def test_same_uid_requires_creation_identity_and_restart_evidence() -> None:
    old_pod = _old_pod()
    missing_restart = _evaluate(
        old_pod=old_pod,
        candidates=(
            replace(
                _new_pod(),
                pod_id=old_pod.pod_id,
                pod_uid=old_pod.pod_uid,
                created_at=old_pod.created_at,
                restart_count=None,
            ),
        ),
    )
    changed_creation = _evaluate(
        old_pod=old_pod,
        candidates=(
            replace(
                _new_pod(),
                pod_id=old_pod.pod_id,
                pod_uid=old_pod.pod_uid,
                restart_count=1,
            ),
        ),
    )

    assert missing_restart.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert "restart_count_evidence_unavailable" in missing_restart.evidence_gaps
    assert changed_creation.status is KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
    assert "same_uid_creation_time_conflict" in changed_creation.evidence_gaps


def test_same_uid_restart_requires_monotonic_observation_time() -> None:
    old_pod = replace(_old_pod(), metadata=_metadata(_CUTOFF))
    result = _evaluate(
        old_pod=old_pod,
        candidates=(
            replace(
                _new_pod(),
                pod_id=old_pod.pod_id,
                pod_uid=old_pod.pod_uid,
                created_at=old_pod.created_at,
                restart_count=1,
                metadata=_metadata(_CUTOFF - timedelta(seconds=1)),
            ),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
    assert "restart_observation_order_conflict" in result.evidence_gaps


def test_new_replica_set_under_same_deployment_is_rollout_replacement() -> None:
    result = _evaluate(
        candidates=(
            replace(
                _new_pod(),
                owner_uid="replicaset-uid-b",
                workload_revision="revision-b",
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


def test_rollout_requires_a_workload_revision_change() -> None:
    result = _evaluate(
        candidates=(replace(_new_pod(), owner_uid="replicaset-uid-b"),),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert "rollout_revision_change_unproven" in result.evidence_gaps


def test_rollout_requires_scoped_termination_evidence() -> None:
    old_pod = _old_pod()
    new_pod = replace(
        _new_pod(),
        owner_uid="replicaset-uid-b",
        workload_revision="revision-b",
    )
    result = evaluate_kubernetes_pod_replacement(
        old_pod=old_pod,
        candidates=(new_pod,),
        termination=None,
        deployment=_deployment(),
        correlation_window_start=_WINDOW_START,
        cutoff=_CUTOFF,
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert result.recovery_verified is False
    assert "termination_observation_unavailable" in result.evidence_gaps


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
    assert result.candidate_pod_uids == ("pod-uid-new", "pod-uid-new-2")
    assert result.candidate_evidence_refs == ("pod-new",)


def test_missing_verified_owner_identity_fails_closed() -> None:
    result = _evaluate(old_pod=replace(_old_pod(), owner_uid=None))

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert "old_owner_uid_unavailable" in result.evidence_gaps


def test_both_ownership_hops_require_independent_verification() -> None:
    for old_pod, candidates, expected_gap in (
        (
            replace(_old_pod(), owner_link=None),
            (_new_pod(),),
            "old_pod_owner_link_unverified",
        ),
        (
            _old_pod(),
            (replace(_new_pod(), root_controller_link=None),),
            "new_pod_root_controller_link_unverified",
        ),
    ):
        result = _evaluate(old_pod=old_pod, candidates=candidates)
        assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
        assert result.replacement_supported is False
        assert expected_gap in result.evidence_gaps


def test_ownership_link_state_must_be_valid_at_the_cutoff() -> None:
    result = _evaluate(
        candidates=(
            replace(
                _new_pod(),
                owner_link=_verified_link(
                    _CUTOFF + timedelta(seconds=1),
                    suffix="future-owner",
                ),
            ),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
    assert result.replacement_supported is False
    assert "new_pod_owner_link_evidence_after_cutoff" in result.evidence_gaps


def test_missing_workload_revisions_fail_closed() -> None:
    result = _evaluate(
        old_pod=replace(_old_pod(), workload_revision=None),
        candidates=(replace(_new_pod(), workload_revision=None),),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert "old_workload_revision_unavailable" in result.evidence_gaps
    assert "new_workload_revision_unavailable" in result.evidence_gaps


def test_blank_workload_revision_is_rejected_at_the_boundary() -> None:
    with pytest.raises(ValueError, match="workload_revision MUST be bounded non-empty"):
        _new_pod(workload_revision=" ")


def test_termination_must_precede_creation_by_ordering_margin() -> None:
    result = _evaluate(
        termination=replace(
            _termination(),
            event_time=_new_pod().created_at,
            recorded_at=_new_pod().created_at,
        )
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert "termination_ordering_unproven" in result.evidence_gaps


def test_scale_change_does_not_support_abnormal_replacement() -> None:
    result = _evaluate(
        termination=replace(_termination(), event_type="Killing", reason="Completed", exit_code=0),
        deployment=replace(
            _deployment(),
            desired_replicas_before=2,
            desired_replicas_after=1,
            desired_replica_history=_replica_history(2, 1),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.abnormal_replacement_supported is False
    assert "abnormal_replacement_unproven" in result.evidence_gaps


def test_interval_scale_down_does_not_support_abnormal_replacement() -> None:
    result = _evaluate(
        deployment=replace(
            _deployment(),
            desired_replica_history=(
                DeploymentReplicaObservation(
                    observed_at=_WINDOW_START,
                    desired_replicas=1,
                ),
                DeploymentReplicaObservation(
                    observed_at=_CUTOFF - timedelta(minutes=6),
                    desired_replicas=0,
                ),
                DeploymentReplicaObservation(
                    observed_at=_CUTOFF,
                    desired_replicas=1,
                ),
            ),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.abnormal_replacement_supported is False
    assert "abnormal_replacement_unproven" in result.evidence_gaps


def test_replica_history_after_cutoff_cannot_support_replacement() -> None:
    result = _evaluate(
        deployment=replace(
            _deployment(),
            desired_replica_history=(
                DeploymentReplicaObservation(
                    observed_at=_WINDOW_START,
                    desired_replicas=1,
                ),
                DeploymentReplicaObservation(
                    observed_at=_CUTOFF + timedelta(seconds=1),
                    desired_replicas=1,
                ),
            ),
        ),
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
            desired_replica_history=_replica_history(2, 2),
            ready_replicas=1,
            available_replicas=1,
            unavailable_replicas=1,
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.POD_REPLACEMENT
    assert result.recovery_verified is False


def test_recovery_rejects_an_unrelated_deployment_uid() -> None:
    result = _evaluate(
        deployment=replace(_deployment(), deployment_uid="deployment-uid-other"),
    )

    assert result.status is KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
    assert result.replacement_supported is True
    assert result.abnormal_replacement_supported is False
    assert result.recovery_verified is False
    assert "deployment_uid_conflict" in result.evidence_gaps


def test_abnormal_replacement_requires_valid_deployment_evidence() -> None:
    invalid_deployments = (
        replace(
            _deployment(),
            desired_replicas_before=None,
            desired_replicas_after=None,
        ),
        replace(
            _deployment(),
            metadata=_metadata(_CUTOFF - timedelta(minutes=10)),
        ),
        replace(
            _deployment(),
            metadata=_metadata(_CUTOFF, conflicts=("replica_conflict",)),
        ),
    )

    for deployment in invalid_deployments:
        result = _evaluate(deployment=deployment)
        assert result.abnormal_replacement_supported is False


def test_termination_outside_the_window_cannot_support_replacement() -> None:
    result = _evaluate(
        termination=replace(
            _termination(),
            event_time=_WINDOW_START - timedelta(seconds=1),
            recorded_at=_WINDOW_START,
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert result.abnormal_replacement_supported is False
    assert "termination_event_outside_window" in result.evidence_gaps


def test_old_pod_creation_must_precede_termination() -> None:
    result = _evaluate(
        old_pod=replace(
            _old_pod(),
            created_at=_CUTOFF - timedelta(minutes=5) + timedelta(seconds=1),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
    assert result.replacement_supported is False
    assert result.abnormal_replacement_supported is False
    assert "old_pod_created_after_termination" in result.evidence_gaps


def test_historical_pod_requires_observed_authority() -> None:
    desired = _metadata(
        _CUTOFF - timedelta(minutes=10),
        lane=StateFactLane.DESIRED,
        authority=StateFactAuthority.APPROVED_POLICY,
    )
    result = _evaluate(old_pod=replace(_old_pod(), metadata=desired))

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert "historical_evidence_not_observed" in result.evidence_gaps
    assert "historical_evidence_authority_invalid" in result.evidence_gaps


def test_historical_evidence_must_follow_old_pod_creation() -> None:
    old_pod = _old_pod()
    result = _evaluate(
        old_pod=replace(
            old_pod,
            metadata=_metadata(_WINDOW_START - timedelta(hours=1, seconds=1)),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert "historical_evidence_before_pod_creation" in result.evidence_gaps


def test_statefulset_replacement_cannot_claim_deployment_recovery() -> None:
    result = _evaluate(
        old_pod=replace(_old_pod(), root_controller_kind="StatefulSet"),
        candidates=(replace(_new_pod(), root_controller_kind="StatefulSet"),),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.abnormal_replacement_supported is False
    assert result.recovery_verified is False
    assert "unsupported_controller_kind" in result.evidence_gaps


def test_zero_replica_deployment_cannot_verify_an_observed_pod() -> None:
    result = _evaluate(
        deployment=replace(
            _deployment(),
            desired_replicas_before=0,
            desired_replicas_after=0,
            desired_replica_history=_replica_history(0, 0),
            ready_replicas=0,
            available_replicas=0,
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.abnormal_replacement_supported is False
    assert result.recovery_verified is False
    assert "deployment_desired_replicas_zero" in result.evidence_gaps


def test_desired_state_cannot_prove_observed_deployment_recovery() -> None:
    desired = _metadata(
        _CUTOFF,
        lane=StateFactLane.DESIRED,
        authority=StateFactAuthority.APPROVED_POLICY,
    )
    result = _evaluate(deployment=replace(_deployment(), metadata=desired))

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.abnormal_replacement_supported is False
    assert result.recovery_verified is False
    assert "deployment_evidence_not_observed" in result.evidence_gaps
    assert "deployment_evidence_authority_invalid" in result.evidence_gaps


def test_recovery_evidence_must_follow_pod_creation() -> None:
    before_creation = _metadata(_CUTOFF - timedelta(minutes=4, seconds=1))
    pod_result = _evaluate(candidates=(replace(_new_pod(), metadata=before_creation),))
    deployment_result = _evaluate(
        deployment=replace(_deployment(), metadata=before_creation),
    )

    assert pod_result.recovery_verified is False
    assert "current_pod_evidence_before_creation" in pod_result.evidence_gaps
    assert deployment_result.recovery_verified is False
    assert "deployment_evidence_before_pod_creation" in deployment_result.evidence_gaps


def test_missing_current_pod_state_is_explicitly_incomplete() -> None:
    result = _evaluate(
        candidates=(
            replace(
                _new_pod(),
                phase=None,
                ready=None,
                container_count=None,
                ready_container_count=None,
            ),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.complete is False
    assert result.recovery_verified is False
    assert {
        "current_pod_phase_unavailable",
        "current_pod_ready_unavailable",
        "current_pod_container_count_unavailable",
        "current_pod_ready_container_count_unavailable",
    }.issubset(result.evidence_gaps)


def test_deployment_recovery_requires_cluster_and_namespace_match() -> None:
    for deployment, expected_gap in (
        (replace(_deployment(), cluster_id="cluster-other"), "deployment_cluster_conflict"),
        (replace(_deployment(), namespace="other"), "deployment_namespace_conflict"),
    ):
        result = _evaluate(deployment=deployment)
        assert result.status is KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
        assert result.recovery_verified is False
        assert expected_gap in result.evidence_gaps


def test_termination_requires_cluster_and_namespace_match() -> None:
    for termination, expected_gap in (
        (replace(_termination(), cluster_id="cluster-other"), "termination_cluster_conflict"),
        (replace(_termination(), namespace="other"), "termination_namespace_conflict"),
    ):
        result = _evaluate(termination=termination)
        assert result.status is KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
        assert result.abnormal_replacement_supported is False
        assert expected_gap in result.evidence_gaps


def test_termination_source_identity_and_revision_are_required() -> None:
    with pytest.raises(ValueError, match="source_identity MUST be bounded non-empty"):
        _termination(source_identity=" ")
    with pytest.raises(ValueError, match="source_revision MUST be bounded non-empty"):
        _termination(source_revision="")

    result = _evaluate(termination=replace(_termination(), source_revision=None))
    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.replacement_supported is False
    assert "termination_source_revision_unavailable" in result.evidence_gaps


def test_runtime_integer_fields_reject_fractional_values() -> None:
    with pytest.raises(ValueError, match="ready_replicas MUST be a non-negative integer"):
        _deployment(ready_replicas=0.5)
    with pytest.raises(ValueError, match="container_count MUST be a non-negative integer"):
        _new_pod(container_count=0.5)
    with pytest.raises(ValueError, match="exit_code MUST be a non-negative integer"):
        _termination(exit_code=1.5)
    with pytest.raises(ValueError, match="replica_history_complete MUST be a boolean"):
        _deployment(replica_history_complete="false")


def test_zero_container_pod_cannot_verify_recovery() -> None:
    result = _evaluate(
        candidates=(
            replace(
                _new_pod(),
                container_count=0,
                ready_container_count=0,
            ),
        ),
    )

    assert result.status is KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    assert result.recovery_verified is False
    assert "current_pod_container_count_zero" in result.evidence_gaps


def test_result_round_trip_preserves_replay_inputs() -> None:
    result = _evaluate()

    replayed = KubernetesPodReplacementEvidenceResult.model_validate(result.model_dump(mode="json"))

    assert replayed == result
    assert replayed.historical_evidence_refs == ("pod-old", "termination-old")
    assert replayed.current_evidence_refs == ("deployment-current", "pod-new")
