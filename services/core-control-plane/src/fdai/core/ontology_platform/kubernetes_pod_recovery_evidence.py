"""Deterministically assess one Pod restart and current recovery observation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai.shared.contracts.models import ContractBase
from fdai.shared.providers.state_evidence import StateFactMetadata

_MAX_ID_LENGTH = 512
_MAX_WAITING_REASONS = 32


class KubernetesPodRecoveryStatus(StrEnum):
    """Calibrated disposition of one exact Pod restart observation."""

    RECOVERED = "restart_observed_recovered"
    NOT_RECOVERED = "restart_observed_not_recovered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


@dataclass(frozen=True, slots=True)
class PodRecoveryObservation:
    """Bounded provider state for one exact Kubernetes Pod."""

    pod_id: str
    phase: str | None
    ready: bool | None
    container_count: int | None
    ready_container_count: int | None
    restart_count: int | None
    waiting_reasons: tuple[str, ...]
    metadata: StateFactMetadata

    def __post_init__(self) -> None:
        if not self.pod_id.strip() or len(self.pod_id) > _MAX_ID_LENGTH:
            raise ValueError("pod_id MUST be bounded non-empty text")
        for field_name, value in (
            ("container_count", self.container_count),
            ("ready_container_count", self.ready_container_count),
            ("restart_count", self.restart_count),
        ):
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError(f"{field_name} MUST be a non-negative integer or null")
        if (
            self.container_count is not None
            and self.ready_container_count is not None
            and self.ready_container_count > self.container_count
        ):
            raise ValueError("ready_container_count MUST NOT exceed container_count")
        if len(self.waiting_reasons) > _MAX_WAITING_REASONS:
            raise ValueError("waiting_reasons exceeds its bound")
        if len(self.waiting_reasons) != len(set(self.waiting_reasons)):
            raise ValueError("waiting_reasons MUST be unique")
        if any(not reason.strip() for reason in self.waiting_reasons):
            raise ValueError("waiting_reasons MUST contain non-empty text")


@dataclass(frozen=True, slots=True)
class PodRestartHistoryObservation:
    """One bounded restart-count delta window for the same immutable Pod."""

    pod_id: str
    start: datetime
    end: datetime
    restart_delta: int | None
    complete: bool
    missing_reason: str | None
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.pod_id.strip() or len(self.pod_id) > _MAX_ID_LENGTH:
            raise ValueError("restart history pod_id MUST be bounded non-empty text")
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("restart history MUST have an aware positive interval")
        if self.restart_delta is not None and (
            isinstance(self.restart_delta, bool) or self.restart_delta < 0
        ):
            raise ValueError("restart_delta MUST be a non-negative integer or null")
        if self.complete != (self.missing_reason is None):
            raise ValueError("restart history completeness and missing reason are inconsistent")
        if self.complete != (self.restart_delta is not None):
            raise ValueError("complete restart history MUST carry one delta")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("restart history MUST cite evidence")


@dataclass(frozen=True, slots=True)
class PodOwnerDeploymentObservation:
    """Bounded current replica state for the exact Pod owner Deployment."""

    deployment_id: str
    desired_replicas: int | None
    ready_replicas: int | None
    available_replicas: int | None
    unavailable_replicas: int | None
    metadata: StateFactMetadata

    def __post_init__(self) -> None:
        if not self.deployment_id.strip() or len(self.deployment_id) > _MAX_ID_LENGTH:
            raise ValueError("deployment_id MUST be bounded non-empty text")
        for field_name, value in (
            ("desired_replicas", self.desired_replicas),
            ("ready_replicas", self.ready_replicas),
            ("available_replicas", self.available_replicas),
            ("unavailable_replicas", self.unavailable_replicas),
        ):
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError(f"{field_name} MUST be a non-negative integer or null")


class KubernetesPodRecoveryEvidenceResult(ContractBase):
    """One no-cause, no-authority Pod restart and recovery assessment."""

    pod_id: str
    status: KubernetesPodRecoveryStatus
    complete: bool
    restart_observed: bool
    recovery_verified: bool
    phase: str | None
    ready: bool | None
    container_count: int | None
    ready_container_count: int | None
    restart_count: int | None
    restart_history_complete: bool
    restart_observed_in_window: bool
    restart_delta: int | None
    restart_window_start: datetime
    restart_window_end: datetime
    owner_deployment_id: str
    desired_replicas: int | None
    ready_replicas: int | None
    available_replicas: int | None
    unavailable_replicas: int | None
    deployment_recovery_verified: bool
    waiting_reasons: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    cause_claim_supported: Literal[False] = False
    execution_authority: Literal[False] = False
    # A distinct lane for a conclusively verified distinct-UID replacement.
    # ``status``/``complete``/``recovery_verified`` answer only whether THIS
    # Pod's own restart was observed and recovered; they MUST NOT be
    # repurposed to mean "a different Pod replaced it". This field carries
    # that separate replacement narrative without touching restart status.
    replacement_recovery_verified: bool = False


def evaluate_kubernetes_pod_recovery(
    *,
    pod: PodRecoveryObservation,
    restart_history: PodRestartHistoryObservation,
    owner_deployment: PodOwnerDeploymentObservation,
    cutoff: datetime,
    graph_complete: bool,
    ownership_complete: bool,
) -> KubernetesPodRecoveryEvidenceResult:
    """Reduce exact Pod state without inferring a restart event or its cause."""

    if cutoff.tzinfo is None:
        raise ValueError("Pod recovery cutoff MUST be timezone-aware")
    if restart_history.pod_id != pod.pod_id:
        raise ValueError("Pod restart history identity does not match the current Pod")
    if restart_history.end != cutoff:
        raise ValueError("Pod restart history MUST end at the recovery cutoff")
    gaps: list[str] = []
    conflicts: list[str] = []
    if not graph_complete:
        gaps.append("pod_graph_incomplete")
    if not ownership_complete:
        gaps.append("pod_ownership_incomplete")
    metadata_gaps, metadata_conflicts = _metadata_findings(pod.metadata, cutoff=cutoff)
    gaps.extend(metadata_gaps)
    conflicts.extend(metadata_conflicts)
    deployment_gaps, deployment_conflicts = _metadata_findings(
        owner_deployment.metadata,
        cutoff=cutoff,
        subject="deployment",
    )
    gaps.extend(deployment_gaps)
    conflicts.extend(deployment_conflicts)
    for field_name, value in (
        ("phase", pod.phase),
        ("ready", pod.ready),
        ("container_count", pod.container_count),
        ("ready_container_count", pod.ready_container_count),
        ("restart_count", pod.restart_count),
    ):
        if value is None:
            gaps.append(f"{field_name}_unavailable")
    for field_name, value in (
        ("desired_replicas", owner_deployment.desired_replicas),
        ("ready_replicas", owner_deployment.ready_replicas),
        ("available_replicas", owner_deployment.available_replicas),
        ("unavailable_replicas", owner_deployment.unavailable_replicas),
    ):
        if value is None:
            gaps.append(f"deployment_{field_name}_unavailable")
    if pod.ready is True and pod.phase != "Running":
        conflicts.append("ready_pod_not_running")

    if not restart_history.complete:
        gaps.append(f"restart_history_{restart_history.missing_reason or 'incomplete'}")
    restart_observed_in_window = (
        restart_history.complete
        and restart_history.restart_delta is not None
        and restart_history.restart_delta > 0
    )
    if restart_history.complete and not restart_observed_in_window:
        gaps.append("restart_not_observed_in_window")
    if pod.restart_count == 0 and restart_observed_in_window:
        conflicts.append("restart_history_conflicts_with_current_count")
    desired = owner_deployment.desired_replicas
    if desired is not None:
        for field_name, value in (
            ("ready_replicas", owner_deployment.ready_replicas),
            ("available_replicas", owner_deployment.available_replicas),
            ("unavailable_replicas", owner_deployment.unavailable_replicas),
        ):
            if value is not None and value > desired:
                conflicts.append(f"deployment_{field_name}_exceed_desired")
        if desired == 0:
            conflicts.append("pod_present_for_zero_replica_deployment")
    restart_observed = restart_observed_in_window
    current_ready = (
        pod.phase == "Running"
        and pod.ready is True
        and pod.container_count is not None
        and pod.ready_container_count == pod.container_count
        and not pod.waiting_reasons
    )
    deployment_recovery_verified = (
        desired is not None
        and desired > 0
        and owner_deployment.ready_replicas == desired
        and owner_deployment.available_replicas == desired
        and owner_deployment.unavailable_replicas == 0
    )
    if pod.restart_count == 0:
        gaps.append("restart_not_observed_in_current_pod")

    canonical_conflicts = tuple(dict.fromkeys(conflicts))
    canonical_gaps = tuple(dict.fromkeys((*gaps, *canonical_conflicts)))
    if canonical_conflicts:
        status = KubernetesPodRecoveryStatus.CONFLICTING_EVIDENCE
    elif canonical_gaps:
        status = KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE
    elif current_ready and deployment_recovery_verified:
        status = KubernetesPodRecoveryStatus.RECOVERED
    else:
        status = KubernetesPodRecoveryStatus.NOT_RECOVERED
    complete = status in {
        KubernetesPodRecoveryStatus.RECOVERED,
        KubernetesPodRecoveryStatus.NOT_RECOVERED,
    }
    return KubernetesPodRecoveryEvidenceResult(
        pod_id=pod.pod_id,
        status=status,
        complete=complete,
        restart_observed=restart_observed,
        recovery_verified=status is KubernetesPodRecoveryStatus.RECOVERED,
        phase=pod.phase,
        ready=pod.ready,
        container_count=pod.container_count,
        ready_container_count=pod.ready_container_count,
        restart_count=pod.restart_count,
        restart_history_complete=restart_history.complete,
        restart_observed_in_window=restart_observed_in_window,
        restart_delta=restart_history.restart_delta,
        restart_window_start=restart_history.start,
        restart_window_end=restart_history.end,
        owner_deployment_id=owner_deployment.deployment_id,
        desired_replicas=owner_deployment.desired_replicas,
        ready_replicas=owner_deployment.ready_replicas,
        available_replicas=owner_deployment.available_replicas,
        unavailable_replicas=owner_deployment.unavailable_replicas,
        deployment_recovery_verified=deployment_recovery_verified,
        waiting_reasons=pod.waiting_reasons,
        evidence_gaps=canonical_gaps,
        evidence_refs=tuple(
            sorted(
                set(
                    (
                        *pod.metadata.evidence_refs,
                        *restart_history.evidence_refs,
                        *owner_deployment.metadata.evidence_refs,
                    )
                )
            )
        ),
    )


def _metadata_findings(
    metadata: StateFactMetadata,
    *,
    cutoff: datetime,
    subject: str = "pod",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    normalized_cutoff = cutoff.astimezone(UTC)
    evidence_cutoff = metadata.evidence_cutoff.astimezone(UTC)
    gaps: list[str] = []
    conflicts = [f"{subject}_state_evidence_conflict:{item}" for item in metadata.conflicts]
    if evidence_cutoff > normalized_cutoff:
        gaps.append(f"{subject}_evidence_after_cutoff")
    elif (normalized_cutoff - evidence_cutoff).total_seconds() > metadata.freshness_ceiling_seconds:
        gaps.append(f"{subject}_state_evidence_stale")
    if metadata.completeness < 1.0:
        gaps.append(f"{subject}_state_evidence_incomplete")
    if metadata.synthetic:
        gaps.append(f"{subject}_state_evidence_synthetic")
    return tuple(gaps), tuple(conflicts)


__all__ = [
    "KubernetesPodRecoveryEvidenceResult",
    "KubernetesPodRecoveryStatus",
    "PodOwnerDeploymentObservation",
    "PodRecoveryObservation",
    "PodRestartHistoryObservation",
    "evaluate_kubernetes_pod_recovery",
]
