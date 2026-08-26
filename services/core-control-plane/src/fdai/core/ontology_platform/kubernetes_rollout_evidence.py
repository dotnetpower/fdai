"""Deterministically assess Kubernetes rollout evidence without claiming cause."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from fdai.shared.contracts.models import ContractBase
from fdai.shared.providers.state_evidence import StateFactMetadata

_MAX_ID_LENGTH = 512
_MAX_REASON_LENGTH = 128
_MAX_WAITING_REASONS = 32


class KubernetesRolloutStatus(StrEnum):
    """Calibrated disposition of one exact Deployment rollout observation."""

    HEALTHY = "healthy"
    STALLED = "stalled"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


@dataclass(frozen=True, slots=True)
class DeploymentRolloutObservation:
    """Bounded provider observation for one exact Kubernetes Deployment."""

    deployment_id: str
    desired_replicas: int | None
    updated_replicas: int | None
    ready_replicas: int | None
    available_replicas: int | None
    unavailable_replicas: int | None
    progressing_status: str | None
    progressing_reason: str | None
    metadata: StateFactMetadata

    def __post_init__(self) -> None:
        _validate_id(self.deployment_id, field="deployment_id")
        for field_name, value in (
            ("desired_replicas", self.desired_replicas),
            ("updated_replicas", self.updated_replicas),
            ("ready_replicas", self.ready_replicas),
            ("available_replicas", self.available_replicas),
            ("unavailable_replicas", self.unavailable_replicas),
        ):
            _validate_count(value, field=field_name)
        if self.progressing_status not in {None, "True", "False", "Unknown"}:
            raise ValueError("progressing_status MUST be True, False, Unknown, or None")
        _validate_reason(self.progressing_reason, field="progressing_reason")


@dataclass(frozen=True, slots=True)
class PodRolloutObservation:
    """Bounded provider observation for one Pod in the Deployment ownership path."""

    pod_id: str
    deployment_id: str
    phase: str | None
    ready: bool | None
    container_count: int | None
    ready_container_count: int | None
    restart_count: int | None
    waiting_reasons: tuple[str, ...]
    metadata: StateFactMetadata

    def __post_init__(self) -> None:
        _validate_id(self.pod_id, field="pod_id")
        _validate_id(self.deployment_id, field="deployment_id")
        _validate_reason(self.phase, field="phase")
        for field_name, value in (
            ("container_count", self.container_count),
            ("ready_container_count", self.ready_container_count),
            ("restart_count", self.restart_count),
        ):
            _validate_count(value, field=field_name)
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
        for reason in self.waiting_reasons:
            _validate_reason(reason, field="waiting_reason", required=True)


class KubernetesRolloutEvidenceResult(ContractBase):
    """One no-cause, no-authority assessment over bounded rollout evidence."""

    deployment_id: str
    status: KubernetesRolloutStatus
    complete: bool
    desired_replicas: int | None
    updated_replicas: int | None
    ready_replicas: int | None
    available_replicas: int | None
    unavailable_replicas: int | None
    pod_count: int = Field(ge=0)
    ready_pod_count: int = Field(ge=0)
    restart_count: int = Field(ge=0)
    waiting_reasons: tuple[str, ...]
    stall_signals: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    cause_claim_supported: Literal[False] = False
    execution_authority: Literal[False] = False


def evaluate_kubernetes_rollout(
    *,
    deployment: DeploymentRolloutObservation,
    pods: tuple[PodRolloutObservation, ...],
    cutoff: datetime,
    graph_complete: bool,
) -> KubernetesRolloutEvidenceResult:
    """Reduce exact Deployment and Pod observations to a calibrated rollout status.

    The result can establish a bounded healthy or stalled rollout observation. It
    never promotes a waiting reason, replica mismatch, or chronology to root cause.
    """

    if cutoff.tzinfo is None:
        raise ValueError("rollout evidence cutoff MUST be timezone-aware")
    if len({pod.pod_id for pod in pods}) != len(pods):
        raise ValueError("rollout Pod identities MUST be unique")
    for pod in pods:
        if pod.deployment_id != deployment.deployment_id:
            raise ValueError("rollout Pod does not belong to the requested deployment")

    gaps: list[str] = []
    conflicts: list[str] = []
    if not graph_complete:
        gaps.append("rollout_graph_incomplete")
    deployment_gaps, deployment_conflicts = _metadata_findings(
        deployment.metadata,
        cutoff=cutoff,
        subject="deployment",
    )
    gaps.extend(deployment_gaps)
    conflicts.extend(deployment_conflicts)
    for pod in pods:
        pod_gaps, pod_conflicts = _metadata_findings(
            pod.metadata,
            cutoff=cutoff,
            subject="pod",
        )
        gaps.extend(pod_gaps)
        conflicts.extend(pod_conflicts)

    counts = (
        deployment.desired_replicas,
        deployment.updated_replicas,
        deployment.ready_replicas,
        deployment.available_replicas,
        deployment.unavailable_replicas,
    )
    count_names = (
        "desired_replicas",
        "updated_replicas",
        "ready_replicas",
        "available_replicas",
        "unavailable_replicas",
    )
    gaps.extend(
        f"{name}_unavailable"
        for name, value in zip(count_names, counts, strict=True)
        if value is None
    )
    conflicts.extend(_replica_conflicts(deployment))
    if deployment.desired_replicas and not pods:
        gaps.append("deployment_pods_unavailable")

    waiting_reasons = tuple(sorted({reason for pod in pods for reason in pod.waiting_reasons}))
    stall_signals = _stall_signals(deployment, waiting_reasons=waiting_reasons)
    ready_pod_count = sum(pod.ready is True for pod in pods)
    restart_count = sum(pod.restart_count or 0 for pod in pods)

    canonical_conflicts = tuple(dict.fromkeys(conflicts))
    canonical_gaps = tuple(dict.fromkeys((*gaps, *canonical_conflicts)))
    if canonical_conflicts:
        status = KubernetesRolloutStatus.CONFLICTING_EVIDENCE
    elif canonical_gaps:
        status = KubernetesRolloutStatus.INSUFFICIENT_EVIDENCE
    elif _healthy(deployment, pods=pods, waiting_reasons=waiting_reasons):
        status = KubernetesRolloutStatus.HEALTHY
    elif stall_signals and _replica_shortfall(deployment):
        status = KubernetesRolloutStatus.STALLED
    else:
        status = KubernetesRolloutStatus.INSUFFICIENT_EVIDENCE
        canonical_gaps = ("rollout_disposition_unresolved",)

    evidence_refs = tuple(
        sorted(
            {
                reference
                for metadata in (deployment.metadata, *(pod.metadata for pod in pods))
                for reference in metadata.evidence_refs
            }
        )
    )
    return KubernetesRolloutEvidenceResult(
        deployment_id=deployment.deployment_id,
        status=status,
        complete=status in {KubernetesRolloutStatus.HEALTHY, KubernetesRolloutStatus.STALLED},
        desired_replicas=deployment.desired_replicas,
        updated_replicas=deployment.updated_replicas,
        ready_replicas=deployment.ready_replicas,
        available_replicas=deployment.available_replicas,
        unavailable_replicas=deployment.unavailable_replicas,
        pod_count=len(pods),
        ready_pod_count=ready_pod_count,
        restart_count=restart_count,
        waiting_reasons=waiting_reasons,
        stall_signals=stall_signals,
        evidence_gaps=canonical_gaps,
        evidence_refs=evidence_refs,
    )


def _metadata_findings(
    metadata: StateFactMetadata,
    *,
    cutoff: datetime,
    subject: str,
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


def _replica_conflicts(deployment: DeploymentRolloutObservation) -> tuple[str, ...]:
    desired = deployment.desired_replicas
    if desired is None:
        return ()
    findings = []
    for field_name, value in (
        ("updated_replicas", deployment.updated_replicas),
        ("ready_replicas", deployment.ready_replicas),
        ("available_replicas", deployment.available_replicas),
        ("unavailable_replicas", deployment.unavailable_replicas),
    ):
        if value is not None and value > desired:
            findings.append(f"{field_name}_exceed_desired")
    return tuple(findings)


def _stall_signals(
    deployment: DeploymentRolloutObservation,
    *,
    waiting_reasons: tuple[str, ...],
) -> tuple[str, ...]:
    signals = []
    if (
        deployment.progressing_status == "False"
        and deployment.progressing_reason == "ProgressDeadlineExceeded"
    ):
        signals.append("deployment_progress_deadline_exceeded")
    signals.extend(f"pod_waiting:{reason}" for reason in waiting_reasons)
    return tuple(signals)


def _replica_shortfall(deployment: DeploymentRolloutObservation) -> bool:
    desired = deployment.desired_replicas
    available = deployment.available_replicas
    return desired is not None and available is not None and available < desired


def _healthy(
    deployment: DeploymentRolloutObservation,
    *,
    pods: tuple[PodRolloutObservation, ...],
    waiting_reasons: tuple[str, ...],
) -> bool:
    desired = deployment.desired_replicas
    if desired is None:
        return False
    counts_match = (
        deployment.updated_replicas == desired
        and deployment.ready_replicas == desired
        and deployment.available_replicas == desired
        and deployment.unavailable_replicas == 0
    )
    ready_pods = sum(pod.ready is True and pod.phase == "Running" for pod in pods)
    return counts_match and ready_pods >= desired and not waiting_reasons


def _validate_id(value: str, *, field: str) -> None:
    if not value.strip() or len(value) > _MAX_ID_LENGTH:
        raise ValueError(f"{field} MUST be bounded non-empty text")


def _validate_count(value: int | None, *, field: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError(f"{field} MUST be a non-negative integer or None")


def _validate_reason(value: str | None, *, field: str, required: bool = False) -> None:
    if value is None:
        if required:
            raise ValueError(f"{field} MUST be bounded non-empty text")
        return
    if not value.strip() or len(value) > _MAX_REASON_LENGTH:
        raise ValueError(f"{field} MUST be bounded non-empty text")


__all__ = [
    "DeploymentRolloutObservation",
    "KubernetesRolloutEvidenceResult",
    "KubernetesRolloutStatus",
    "PodRolloutObservation",
    "evaluate_kubernetes_rollout",
]
