"""Deterministic Kubernetes Pod restart and recovery assessment tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryStatus,
    PodOwnerDeploymentObservation,
    PodRecoveryObservation,
    PodRestartHistoryObservation,
    evaluate_kubernetes_pod_recovery,
)
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_CUTOFF = datetime(2026, 8, 25, 15, 0, tzinfo=UTC)


def _metadata(*, conflicts: tuple[str, ...] = ()) -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="kubernetes-api-inventory",
        source_revision="generation-1",
        effective_at=_CUTOFF,
        recorded_at=_CUTOFF,
        evidence_cutoff=_CUTOFF,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        conflicts=conflicts,
        evidence_refs=("kubernetes:pod:example",),
    )


def _pod(**updates: object) -> PodRecoveryObservation:
    values: dict[str, object] = {
        "pod_id": "cluster:example/kubernetes/pod/example",
        "phase": "Running",
        "ready": True,
        "container_count": 1,
        "ready_container_count": 1,
        "restart_count": 2,
        "waiting_reasons": (),
        "metadata": _metadata(),
    }
    values.update(updates)
    return PodRecoveryObservation(**values)  # type: ignore[arg-type]


def _history(**updates: object) -> PodRestartHistoryObservation:
    values: dict[str, object] = {
        "pod_id": "cluster:example/kubernetes/pod/example",
        "start": _CUTOFF - timedelta(minutes=30),
        "end": _CUTOFF,
        "restart_delta": 1,
        "complete": True,
        "missing_reason": None,
        "evidence_refs": ("metric:pod-restart:example",),
    }
    values.update(updates)
    return PodRestartHistoryObservation(**values)  # type: ignore[arg-type]


def _deployment(**updates: object) -> PodOwnerDeploymentObservation:
    values: dict[str, object] = {
        "deployment_id": "cluster:example/kubernetes/deployment/order-api",
        "desired_replicas": 1,
        "ready_replicas": 1,
        "available_replicas": 1,
        "unavailable_replicas": 0,
        "metadata": _metadata(),
    }
    values.update(updates)
    return PodOwnerDeploymentObservation(**values)  # type: ignore[arg-type]


def test_observed_restart_with_ready_running_pod_reports_recovered() -> None:
    result = evaluate_kubernetes_pod_recovery(
        pod=_pod(),
        restart_history=_history(),
        owner_deployment=_deployment(),
        cutoff=_CUTOFF,
        graph_complete=True,
        ownership_complete=True,
    )

    assert result.status is KubernetesPodRecoveryStatus.RECOVERED
    assert result.complete is True
    assert result.restart_observed is True
    assert result.restart_observed_in_window is True
    assert result.recovery_verified is True
    assert result.evidence_gaps == ()
    assert result.cause_claim_supported is False
    assert result.execution_authority is False


def test_observed_restart_with_unready_pod_reports_not_recovered() -> None:
    result = evaluate_kubernetes_pod_recovery(
        pod=_pod(
            phase="Pending",
            ready=False,
            ready_container_count=0,
            waiting_reasons=("CrashLoopBackOff",),
        ),
        restart_history=_history(),
        owner_deployment=_deployment(),
        cutoff=_CUTOFF,
        graph_complete=True,
        ownership_complete=True,
    )

    assert result.status is KubernetesPodRecoveryStatus.NOT_RECOVERED
    assert result.complete is True
    assert result.restart_observed is True
    assert result.recovery_verified is False


def test_zero_current_restart_count_does_not_prove_no_prior_restart() -> None:
    result = evaluate_kubernetes_pod_recovery(
        pod=_pod(restart_count=0),
        restart_history=_history(restart_delta=0),
        owner_deployment=_deployment(),
        cutoff=_CUTOFF,
        graph_complete=True,
        ownership_complete=True,
    )

    assert result.status is KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
    assert result.complete is False
    assert result.restart_observed is False
    assert result.recovery_verified is False
    assert result.evidence_gaps == (
        "restart_not_observed_in_window",
        "restart_not_observed_in_current_pod",
    )


def test_old_cumulative_restart_count_does_not_prove_recent_restart() -> None:
    result = evaluate_kubernetes_pod_recovery(
        pod=_pod(restart_count=2),
        restart_history=_history(restart_delta=0),
        owner_deployment=_deployment(),
        cutoff=_CUTOFF,
        graph_complete=True,
        ownership_complete=True,
    )

    assert result.status is KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
    assert result.restart_observed is False
    assert result.recovery_verified is False
    assert result.evidence_gaps == ("restart_not_observed_in_window",)


def test_stale_or_conflicting_state_cannot_verify_recovery() -> None:
    stale = replace(
        _metadata(conflicts=("ready",)),
        effective_at=_CUTOFF - timedelta(minutes=10),
        evidence_cutoff=_CUTOFF - timedelta(minutes=10),
    )

    result = evaluate_kubernetes_pod_recovery(
        pod=_pod(metadata=stale),
        restart_history=_history(),
        owner_deployment=_deployment(),
        cutoff=_CUTOFF,
        graph_complete=True,
        ownership_complete=True,
    )

    assert result.status is KubernetesPodRecoveryStatus.CONFLICTING_EVIDENCE
    assert result.complete is False
    assert result.recovery_verified is False
    assert "pod_state_evidence_stale" in result.evidence_gaps
    assert "pod_state_evidence_conflict:ready" in result.evidence_gaps


def test_incomplete_restart_history_cannot_verify_recovery() -> None:
    result = evaluate_kubernetes_pod_recovery(
        pod=_pod(),
        restart_history=_history(
            restart_delta=None,
            complete=False,
            missing_reason="provider_gap",
        ),
        owner_deployment=_deployment(),
        cutoff=_CUTOFF,
        graph_complete=True,
        ownership_complete=True,
    )

    assert result.status is KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
    assert result.recovery_verified is False
    assert "restart_history_provider_gap" in result.evidence_gaps


def test_ready_pod_with_replica_shortfall_is_not_recovered() -> None:
    result = evaluate_kubernetes_pod_recovery(
        pod=_pod(),
        restart_history=_history(),
        owner_deployment=_deployment(
            desired_replicas=3,
            ready_replicas=1,
            available_replicas=1,
            unavailable_replicas=2,
        ),
        cutoff=_CUTOFF,
        graph_complete=True,
        ownership_complete=True,
    )

    assert result.status is KubernetesPodRecoveryStatus.NOT_RECOVERED
    assert result.recovery_verified is False
    assert result.deployment_recovery_verified is False


def test_conflicting_owner_replica_counts_fail_closed() -> None:
    result = evaluate_kubernetes_pod_recovery(
        pod=_pod(),
        restart_history=_history(),
        owner_deployment=_deployment(desired_replicas=1, ready_replicas=2),
        cutoff=_CUTOFF,
        graph_complete=True,
        ownership_complete=True,
    )

    assert result.status is KubernetesPodRecoveryStatus.CONFLICTING_EVIDENCE
    assert result.recovery_verified is False
    assert "deployment_ready_replicas_exceed_desired" in result.evidence_gaps
