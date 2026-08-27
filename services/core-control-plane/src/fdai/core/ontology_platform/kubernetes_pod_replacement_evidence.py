"""Deterministically correlate immutable Kubernetes Pod replacement observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from fdai.shared.contracts.models import ContractBase
from fdai.shared.providers.state_evidence import StateFactMetadata

from .kubernetes_lifecycle_observation import KubernetesLifecycleObservation

_MAX_ID_LENGTH = 512
_MAX_CANDIDATES = 32
_ABNORMAL_REASONS = frozenset(
    {
        "BackOff",
        "Failed",
        "OOMKilled",
        "Unhealthy",
    }
)


class KubernetesPodReplacementStatus(StrEnum):
    """Calibrated classification of immutable Pod lifecycle observations."""

    CONTAINER_RESTART = "container_restart"
    POD_REPLACEMENT = "pod_replacement"
    ROLLOUT_REPLACEMENT = "rollout_replacement"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


@dataclass(frozen=True, slots=True)
class PodLifecycleObservation:
    """One independently replayable current or historical Pod observation."""

    pod_id: str
    pod_uid: str
    cluster_id: str
    namespace: str
    owner_uid: str | None
    root_controller_uid: str | None
    root_controller_kind: str | None
    created_at: datetime | None
    phase: str | None
    ready: bool | None
    container_count: int | None
    ready_container_count: int | None
    waiting_reasons: tuple[str, ...]
    workload_revision: str | None
    metadata: StateFactMetadata
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("pod_id", "pod_uid", "cluster_id", "namespace"):
            value = getattr(self, field_name)
            if not value.strip() or len(value) > _MAX_ID_LENGTH:
                raise ValueError(f"{field_name} MUST be bounded non-empty text")
        for field_name in ("owner_uid", "root_controller_uid", "root_controller_kind"):
            value = getattr(self, field_name)
            if value is not None and (not value.strip() or len(value) > _MAX_ID_LENGTH):
                raise ValueError(f"{field_name} MUST be bounded non-empty text or null")
        if self.created_at is not None and self.created_at.tzinfo is None:
            raise ValueError("Pod creation time MUST be timezone-aware")
        for field_name in ("container_count", "ready_container_count"):
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError(f"{field_name} MUST be a non-negative integer or null")
        if (
            self.container_count is not None
            and self.ready_container_count is not None
            and self.ready_container_count > self.container_count
        ):
            raise ValueError("ready_container_count MUST NOT exceed container_count")
        if len(self.waiting_reasons) != len(set(self.waiting_reasons)):
            raise ValueError("waiting_reasons MUST be unique")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("Pod lifecycle observation MUST cite evidence")


@dataclass(frozen=True, slots=True)
class PodTerminationObservation:
    """One retained termination observation for an immutable Pod UID."""

    pod_uid: str
    event_type: str | None
    reason: str | None
    exit_code: int | None
    event_time: datetime | None
    recorded_at: datetime | None
    source_identity: str | None
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.pod_uid.strip() or len(self.pod_uid) > _MAX_ID_LENGTH:
            raise ValueError("termination pod_uid MUST be bounded non-empty text")
        for field_name in ("event_time", "recorded_at"):
            value = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"termination {field_name} MUST be timezone-aware")
        if self.exit_code is not None and (isinstance(self.exit_code, bool) or self.exit_code < 0):
            raise ValueError("termination exit_code MUST be a non-negative integer or null")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("termination observation MUST cite evidence")


@dataclass(frozen=True, slots=True)
class PodReplacementDeploymentObservation:
    """Deployment state spanning the replacement correlation window."""

    deployment_id: str
    desired_replicas_before: int | None
    desired_replicas_after: int | None
    ready_replicas: int | None
    available_replicas: int | None
    unavailable_replicas: int | None
    metadata: StateFactMetadata
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.deployment_id.strip() or len(self.deployment_id) > _MAX_ID_LENGTH:
            raise ValueError("deployment_id MUST be bounded non-empty text")
        for field_name in (
            "desired_replicas_before",
            "desired_replicas_after",
            "ready_replicas",
            "available_replicas",
            "unavailable_replicas",
        ):
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError(f"{field_name} MUST be a non-negative integer or null")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("Deployment replacement observation MUST cite evidence")


class KubernetesPodReplacementEvidenceResult(ContractBase):
    """Replayable, no-cause, no-authority Pod replacement assessment."""

    status: KubernetesPodReplacementStatus
    complete: bool
    replacement_supported: bool
    abnormal_replacement_supported: bool
    recovery_verified: bool
    old_pod_id: str
    old_pod_uid: str
    new_pod_id: str | None
    new_pod_uid: str | None
    old_owner_uid: str | None
    new_owner_uid: str | None
    root_controller_uid: str | None
    root_controller_kind: str | None
    termination_time: datetime | None
    creation_time: datetime | None
    correlation_window_start: datetime
    cutoff: datetime
    ordering_margin_seconds: int
    evidence_gaps: tuple[str, ...]
    historical_evidence_refs: tuple[str, ...]
    current_evidence_refs: tuple[str, ...]
    cause_claim_supported: Literal[False] = False
    execution_authority: Literal[False] = False


def evaluate_kubernetes_pod_replacement(
    *,
    old_pod: PodLifecycleObservation,
    candidates: tuple[PodLifecycleObservation, ...],
    termination: PodTerminationObservation | None,
    deployment: PodReplacementDeploymentObservation | None,
    correlation_window_start: datetime,
    cutoff: datetime,
    ordering_margin: timedelta = timedelta(seconds=1),
) -> KubernetesPodReplacementEvidenceResult:
    """Correlate one historical Pod with one bounded current replacement candidate."""

    if correlation_window_start.tzinfo is None or cutoff.tzinfo is None:
        raise ValueError("replacement correlation window MUST be timezone-aware")
    if correlation_window_start >= cutoff:
        raise ValueError("replacement correlation window MUST be positive")
    if ordering_margin < timedelta(0) or ordering_margin.microseconds:
        raise ValueError("ordering_margin MUST be a non-negative whole-second duration")
    if len(candidates) > _MAX_CANDIDATES:
        raise ValueError("replacement candidate set exceeds its bound")

    historical_gaps, historical_conflicts = _historical_metadata_findings(
        old_pod.metadata,
        window_start=correlation_window_start,
        cutoff=cutoff,
    )
    historical_gaps = (
        *historical_gaps,
        *(("old_owner_uid_unavailable",) if old_pod.owner_uid is None else ()),
        *(("root_controller_uid_unavailable",) if old_pod.root_controller_uid is None else ()),
        *(("root_controller_kind_unavailable",) if old_pod.root_controller_kind is None else ()),
    )
    admitted = tuple(
        candidate
        for candidate in candidates
        if candidate.cluster_id == old_pod.cluster_id
        and candidate.namespace == old_pod.namespace
        and candidate.root_controller_uid is not None
        and candidate.root_controller_uid == old_pod.root_controller_uid
        and candidate.created_at is not None
        and correlation_window_start <= candidate.created_at <= cutoff
    )
    if len(admitted) != 1:
        gaps = [
            *historical_gaps,
            ("no_replacement_candidate" if not admitted else "ambiguous_replacement_candidates"),
        ]
        return _result(
            status=(
                KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
                if historical_conflicts
                else KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
            ),
            old_pod=old_pod,
            new_pod=None,
            termination=termination,
            correlation_window_start=correlation_window_start,
            cutoff=cutoff,
            ordering_margin=ordering_margin,
            evidence_gaps=(*historical_conflicts, *gaps),
        )

    new_pod = admitted[0]
    current_gaps, current_conflicts = _current_metadata_findings(new_pod.metadata, cutoff=cutoff)
    gaps = [*historical_gaps, *current_gaps]
    conflicts = [*historical_conflicts, *current_conflicts]
    for field_name, value in (
        ("old_owner_uid", old_pod.owner_uid),
        ("new_owner_uid", new_pod.owner_uid),
        ("root_controller_uid", old_pod.root_controller_uid),
        ("root_controller_kind", old_pod.root_controller_kind),
        ("new_pod_created_at", new_pod.created_at),
    ):
        if value is None:
            gaps.append(f"{field_name}_unavailable")
    if old_pod.root_controller_kind != new_pod.root_controller_kind:
        conflicts.append("root_controller_kind_conflict")
    if old_pod.workload_revision is None and new_pod.workload_revision is not None:
        gaps.append("old_workload_revision_unavailable")
    if old_pod.workload_revision is not None and new_pod.workload_revision is None:
        gaps.append("new_workload_revision_unavailable")
    if (
        old_pod.workload_revision is not None
        and new_pod.workload_revision is not None
        and old_pod.workload_revision != new_pod.workload_revision
        and old_pod.owner_uid == new_pod.owner_uid
    ):
        conflicts.append("workload_revision_conflict")

    if old_pod.pod_uid == new_pod.pod_uid:
        status = KubernetesPodReplacementStatus.CONTAINER_RESTART
        replacement_supported = False
    elif old_pod.owner_uid != new_pod.owner_uid:
        status = KubernetesPodReplacementStatus.ROLLOUT_REPLACEMENT
        replacement_supported = not gaps and not conflicts
    else:
        status = KubernetesPodReplacementStatus.POD_REPLACEMENT
        replacement_supported = not gaps and not conflicts
        _append_termination_findings(
            gaps,
            conflicts,
            old_pod=old_pod,
            new_pod=new_pod,
            termination=termination,
            cutoff=cutoff,
            ordering_margin=ordering_margin,
        )
        replacement_supported = not gaps and not conflicts

    recovery_verified = _recovery_verified(
        new_pod,
        deployment,
        cutoff=cutoff,
        gaps=gaps,
        conflicts=conflicts,
    )
    abnormal_supported = (
        status is KubernetesPodReplacementStatus.POD_REPLACEMENT
        and replacement_supported
        and termination is not None
        and _abnormal_termination(termination)
        and deployment is not None
        and deployment.desired_replicas_before == deployment.desired_replicas_after
    )
    if status is KubernetesPodReplacementStatus.POD_REPLACEMENT and not abnormal_supported:
        gaps.append("abnormal_replacement_unproven")
    if conflicts:
        status = KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE
    elif gaps:
        status = KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE
    return _result(
        status=status,
        old_pod=old_pod,
        new_pod=new_pod,
        termination=termination,
        deployment=deployment,
        correlation_window_start=correlation_window_start,
        cutoff=cutoff,
        ordering_margin=ordering_margin,
        replacement_supported=replacement_supported,
        abnormal_replacement_supported=abnormal_supported,
        recovery_verified=recovery_verified and not gaps and not conflicts,
        evidence_gaps=(*conflicts, *gaps),
    )


def termination_from_lifecycle_observations(
    *,
    pod_uid: str,
    observations: tuple[KubernetesLifecycleObservation, ...],
    cutoff: datetime,
) -> PodTerminationObservation | None:
    """Convert retained lifecycle rows into one replayable old-Pod termination fact.

    Only rows for the exact old UID and at or before the secured cutoff are
    considered. An empty match is intentionally ``None`` rather than evidence
    that termination did not occur.
    """

    if not pod_uid.strip() or cutoff.tzinfo is None:
        raise ValueError("lifecycle termination identity and cutoff MUST be valid")
    matching = tuple(
        item for item in observations if item.object_uid == pod_uid and item.event_time <= cutoff
    )
    if not matching:
        return None
    selected = max(matching, key=lambda item: (item.event_time, item.evidence_ref))
    return PodTerminationObservation(
        pod_uid=pod_uid,
        event_type=selected.event_type,
        reason=selected.reason,
        exit_code=None,
        event_time=selected.event_time,
        recorded_at=selected.recorded_time,
        source_identity="durable-kubernetes-lifecycle",
        evidence_refs=tuple(
            item.evidence_ref
            for item in sorted(matching, key=lambda item: (item.event_time, item.evidence_ref))
        ),
    )


def _append_termination_findings(
    gaps: list[str],
    conflicts: list[str],
    *,
    old_pod: PodLifecycleObservation,
    new_pod: PodLifecycleObservation,
    termination: PodTerminationObservation | None,
    cutoff: datetime,
    ordering_margin: timedelta,
) -> None:
    if termination is None:
        gaps.append("termination_observation_unavailable")
        return
    if termination.pod_uid != old_pod.pod_uid:
        conflicts.append("termination_pod_uid_conflict")
    if termination.event_time is None:
        gaps.append("termination_event_time_unavailable")
    if termination.recorded_at is None:
        gaps.append("termination_recorded_at_unavailable")
    elif termination.recorded_at > cutoff:
        conflicts.append("termination_recorded_after_cutoff")
    if termination.source_identity is None:
        gaps.append("termination_source_identity_unavailable")
    if (
        termination.event_time is not None
        and new_pod.created_at is not None
        and termination.event_time + ordering_margin > new_pod.created_at
    ):
        gaps.append("termination_ordering_unproven")


def _recovery_verified(
    pod: PodLifecycleObservation,
    deployment: PodReplacementDeploymentObservation | None,
    *,
    cutoff: datetime,
    gaps: list[str],
    conflicts: list[str],
) -> bool:
    if pod.root_controller_kind != "Deployment":
        gaps.append("unsupported_controller_kind")
        return False
    if deployment is None:
        gaps.append("deployment_observation_unavailable")
        return False
    deployment_gaps, deployment_conflicts = _current_metadata_findings(
        deployment.metadata,
        cutoff=cutoff,
        subject="deployment",
    )
    gaps.extend(deployment_gaps)
    conflicts.extend(deployment_conflicts)
    values = (
        deployment.desired_replicas_after,
        deployment.ready_replicas,
        deployment.available_replicas,
        deployment.unavailable_replicas,
    )
    if any(value is None for value in values):
        gaps.append("deployment_replica_evidence_unavailable")
        return False
    desired = deployment.desired_replicas_after
    return (
        pod.phase == "Running"
        and pod.ready is True
        and pod.container_count is not None
        and pod.ready_container_count == pod.container_count
        and not pod.waiting_reasons
        and desired == deployment.ready_replicas == deployment.available_replicas
        and deployment.unavailable_replicas == 0
    )


def _abnormal_termination(termination: PodTerminationObservation) -> bool:
    return (
        termination.reason in _ABNORMAL_REASONS
        or termination.event_type in _ABNORMAL_REASONS
        or (termination.exit_code is not None and termination.exit_code != 0)
    )


def _historical_metadata_findings(
    metadata: StateFactMetadata,
    *,
    window_start: datetime,
    cutoff: datetime,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    gaps: list[str] = []
    conflicts = [f"historical_evidence_conflict:{item}" for item in metadata.conflicts]
    if not window_start <= metadata.effective_at <= cutoff:
        gaps.append("historical_evidence_outside_window")
    if metadata.recorded_at > cutoff:
        conflicts.append("historical_evidence_recorded_after_cutoff")
    if metadata.completeness < 1.0:
        gaps.append("historical_evidence_incomplete")
    if metadata.synthetic:
        gaps.append("historical_evidence_synthetic")
    if not metadata.source_revision:
        gaps.append("historical_source_revision_unavailable")
    return tuple(gaps), tuple(conflicts)


def _current_metadata_findings(
    metadata: StateFactMetadata,
    *,
    cutoff: datetime,
    subject: str = "current_pod",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    gaps: list[str] = []
    conflicts = [f"{subject}_evidence_conflict:{item}" for item in metadata.conflicts]
    if metadata.effective_at > cutoff or metadata.recorded_at > cutoff:
        conflicts.append(f"{subject}_evidence_after_cutoff")
    if cutoff - metadata.evidence_cutoff > timedelta(seconds=metadata.freshness_ceiling_seconds):
        gaps.append(f"{subject}_evidence_stale")
    if metadata.completeness < 1.0:
        gaps.append(f"{subject}_evidence_incomplete")
    if metadata.synthetic:
        gaps.append(f"{subject}_evidence_synthetic")
    if not metadata.source_revision:
        gaps.append(f"{subject}_source_revision_unavailable")
    return tuple(gaps), tuple(conflicts)


def _result(
    *,
    status: KubernetesPodReplacementStatus,
    old_pod: PodLifecycleObservation,
    new_pod: PodLifecycleObservation | None,
    termination: PodTerminationObservation | None,
    correlation_window_start: datetime,
    cutoff: datetime,
    ordering_margin: timedelta,
    deployment: PodReplacementDeploymentObservation | None = None,
    replacement_supported: bool = False,
    abnormal_replacement_supported: bool = False,
    recovery_verified: bool = False,
    evidence_gaps: tuple[str, ...] = (),
) -> KubernetesPodReplacementEvidenceResult:
    historical_refs = tuple(
        sorted(
            set(
                (
                    *old_pod.evidence_refs,
                    *(termination.evidence_refs if termination is not None else ()),
                )
            )
        )
    )
    current_refs = tuple(
        sorted(
            set(
                (
                    *(new_pod.evidence_refs if new_pod is not None else ()),
                    *(deployment.evidence_refs if deployment is not None else ()),
                )
            )
        )
    )
    return KubernetesPodReplacementEvidenceResult(
        status=status,
        complete=not evidence_gaps,
        replacement_supported=replacement_supported,
        abnormal_replacement_supported=abnormal_replacement_supported,
        recovery_verified=recovery_verified,
        old_pod_id=old_pod.pod_id,
        old_pod_uid=old_pod.pod_uid,
        new_pod_id=new_pod.pod_id if new_pod is not None else None,
        new_pod_uid=new_pod.pod_uid if new_pod is not None else None,
        old_owner_uid=old_pod.owner_uid,
        new_owner_uid=new_pod.owner_uid if new_pod is not None else None,
        root_controller_uid=old_pod.root_controller_uid,
        root_controller_kind=old_pod.root_controller_kind,
        termination_time=termination.event_time if termination is not None else None,
        creation_time=new_pod.created_at if new_pod is not None else None,
        correlation_window_start=correlation_window_start,
        cutoff=cutoff,
        ordering_margin_seconds=int(ordering_margin.total_seconds()),
        evidence_gaps=tuple(dict.fromkeys(evidence_gaps)),
        historical_evidence_refs=historical_refs,
        current_evidence_refs=current_refs,
    )


__all__ = [
    "KubernetesPodReplacementEvidenceResult",
    "KubernetesPodReplacementStatus",
    "PodLifecycleObservation",
    "PodReplacementDeploymentObservation",
    "PodTerminationObservation",
    "evaluate_kubernetes_pod_replacement",
    "termination_from_lifecycle_observations",
]
