"""Deterministically correlate immutable Kubernetes Pod replacement observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from fdai.shared.contracts.models import ContractBase
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

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
    owner_link: LinkObservationMetadata | None
    root_controller_link: LinkObservationMetadata | None
    created_at: datetime | None
    phase: str | None
    ready: bool | None
    container_count: int | None
    ready_container_count: int | None
    restart_count: int | None
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
        for field_name in ("container_count", "ready_container_count", "restart_count"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{field_name} MUST be a non-negative integer or null")
        if (
            self.container_count is not None
            and self.ready_container_count is not None
            and self.ready_container_count > self.container_count
        ):
            raise ValueError("ready_container_count MUST NOT exceed container_count")
        if len(self.waiting_reasons) != len(set(self.waiting_reasons)):
            raise ValueError("waiting_reasons MUST be unique")
        if self.workload_revision is not None and (
            not self.workload_revision.strip() or len(self.workload_revision) > _MAX_ID_LENGTH
        ):
            raise ValueError("workload_revision MUST be bounded non-empty text or null")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("Pod lifecycle observation MUST cite evidence")


@dataclass(frozen=True, slots=True)
class PodTerminationObservation:
    """One retained termination observation for an immutable Pod UID."""

    pod_uid: str
    cluster_id: str
    namespace: str
    event_type: str | None
    reason: str | None
    exit_code: int | None
    event_time: datetime | None
    recorded_at: datetime | None
    source_identity: str | None
    source_revision: str | None
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("pod_uid", "cluster_id", "namespace"):
            value = getattr(self, field_name)
            if not value.strip() or len(value) > _MAX_ID_LENGTH:
                raise ValueError(f"termination {field_name} MUST be bounded non-empty text")
        for field_name in ("event_time", "recorded_at"):
            value = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"termination {field_name} MUST be timezone-aware")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool)
            or not isinstance(self.exit_code, int)
            or self.exit_code < 0
        ):
            raise ValueError("termination exit_code MUST be a non-negative integer or null")
        for field_name in ("source_identity", "source_revision"):
            value = getattr(self, field_name)
            if value is not None and (not value.strip() or len(value) > _MAX_ID_LENGTH):
                raise ValueError(f"termination {field_name} MUST be bounded non-empty text or null")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("termination observation MUST cite evidence")


@dataclass(frozen=True, slots=True)
class DeploymentReplicaObservation:
    """One desired-replica observation in a complete replacement interval."""

    observed_at: datetime
    desired_replicas: int

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("replica observation time MUST be timezone-aware")
        if isinstance(self.desired_replicas, bool) or not isinstance(self.desired_replicas, int):
            raise ValueError("desired_replicas MUST be an integer")
        if self.desired_replicas < 0:
            raise ValueError("desired_replicas MUST be non-negative")


@dataclass(frozen=True, slots=True)
class PodReplacementDeploymentObservation:
    """Deployment state spanning the replacement correlation window."""

    deployment_id: str
    deployment_uid: str
    cluster_id: str
    namespace: str
    desired_replicas_before: int | None
    desired_replicas_after: int | None
    desired_replica_history: tuple[DeploymentReplicaObservation, ...]
    replica_history_complete: bool
    ready_replicas: int | None
    available_replicas: int | None
    unavailable_replicas: int | None
    metadata: StateFactMetadata
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("deployment_id", "deployment_uid", "cluster_id", "namespace"):
            value = getattr(self, field_name)
            if not value.strip() or len(value) > _MAX_ID_LENGTH:
                raise ValueError(f"{field_name} MUST be bounded non-empty text")
        for field_name in (
            "desired_replicas_before",
            "desired_replicas_after",
            "ready_replicas",
            "available_replicas",
            "unavailable_replicas",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{field_name} MUST be a non-negative integer or null")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("Deployment replacement observation MUST cite evidence")
        if not self.desired_replica_history:
            raise ValueError("Deployment replacement observation MUST include replica history")
        if not isinstance(self.replica_history_complete, bool):
            raise ValueError("replica_history_complete MUST be a boolean")
        observed_times = tuple(item.observed_at for item in self.desired_replica_history)
        if observed_times != tuple(sorted(observed_times)) or len(observed_times) != len(
            set(observed_times)
        ):
            raise ValueError("Deployment replica history MUST be uniquely time ordered")
        if (
            self.desired_replicas_before is not None
            and self.desired_replica_history[0].desired_replicas != self.desired_replicas_before
        ):
            raise ValueError("Deployment replica history start MUST match desired_replicas_before")
        if (
            self.desired_replicas_after is not None
            and self.desired_replica_history[-1].desired_replicas != self.desired_replicas_after
        ):
            raise ValueError("Deployment replica history end MUST match desired_replicas_after")


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
    candidate_pod_uids: tuple[str, ...]
    candidate_evidence_refs: tuple[str, ...]
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
        pod_created_at=old_pod.created_at,
    )
    old_link_gaps, old_link_conflicts = _ownership_link_findings(
        old_pod,
        subject="old_pod",
        cutoff=cutoff,
        window_start=correlation_window_start,
    )
    historical_gaps = (
        *historical_gaps,
        *(("old_owner_uid_unavailable",) if old_pod.owner_uid is None else ()),
        *(("root_controller_uid_unavailable",) if old_pod.root_controller_uid is None else ()),
        *(("root_controller_kind_unavailable",) if old_pod.root_controller_kind is None else ()),
        *old_link_gaps,
    )
    historical_conflicts = (*historical_conflicts, *old_link_conflicts)
    admitted = tuple(
        candidate
        for candidate in candidates
        if candidate.cluster_id == old_pod.cluster_id
        and candidate.namespace == old_pod.namespace
        and candidate.root_controller_uid is not None
        and candidate.root_controller_uid == old_pod.root_controller_uid
        and candidate.created_at is not None
        and (
            (candidate.pod_uid == old_pod.pod_uid)
            or (
                candidate.pod_uid != old_pod.pod_uid
                and correlation_window_start <= candidate.created_at <= cutoff
            )
        )
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
            candidates=candidates,
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
    new_link_gaps, new_link_conflicts = _ownership_link_findings(
        new_pod,
        subject="new_pod",
        cutoff=cutoff,
    )
    gaps.extend(new_link_gaps)
    conflicts.extend(new_link_conflicts)
    for field_name, value in (
        ("old_owner_uid", old_pod.owner_uid),
        ("new_owner_uid", new_pod.owner_uid),
        ("root_controller_uid", old_pod.root_controller_uid),
        ("root_controller_kind", old_pod.root_controller_kind),
        ("new_pod_created_at", new_pod.created_at),
    ):
        if value is None:
            gaps.append(f"{field_name}_unavailable")
    if new_pod.created_at is not None and new_pod.metadata.effective_at < new_pod.created_at:
        gaps.append("current_pod_evidence_before_creation")
    if old_pod.root_controller_kind != new_pod.root_controller_kind:
        conflicts.append("root_controller_kind_conflict")
    if old_pod.workload_revision is None:
        gaps.append("old_workload_revision_unavailable")
    if new_pod.workload_revision is None:
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
        if old_pod.created_at is None or new_pod.created_at is None:
            gaps.append("pod_creation_time_unavailable")
        elif old_pod.created_at != new_pod.created_at:
            conflicts.append("same_uid_creation_time_conflict")
        if new_pod.metadata.effective_at <= old_pod.metadata.effective_at:
            conflicts.append("restart_observation_order_conflict")
        if old_pod.restart_count is None or new_pod.restart_count is None:
            gaps.append("restart_count_evidence_unavailable")
        elif new_pod.restart_count <= old_pod.restart_count:
            gaps.append("restart_count_increase_unproven")
    elif old_pod.owner_uid != new_pod.owner_uid:
        status = KubernetesPodReplacementStatus.ROLLOUT_REPLACEMENT
        if old_pod.workload_revision == new_pod.workload_revision:
            gaps.append("rollout_revision_change_unproven")
        replacement_supported = not gaps and not conflicts
    else:
        status = KubernetesPodReplacementStatus.POD_REPLACEMENT
        replacement_supported = not gaps and not conflicts
    if old_pod.pod_uid != new_pod.pod_uid:
        _append_termination_findings(
            gaps,
            conflicts,
            old_pod=old_pod,
            new_pod=new_pod,
            termination=termination,
            correlation_window_start=correlation_window_start,
            cutoff=cutoff,
            ordering_margin=ordering_margin,
            require_precedes_creation=(status is KubernetesPodReplacementStatus.POD_REPLACEMENT),
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
        and _deployment_supports_abnormal_replacement(
            deployment,
            new_pod,
            termination=termination,
            cutoff=cutoff,
        )
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
        candidates=(new_pod,),
        correlation_window_start=correlation_window_start,
        cutoff=cutoff,
        ordering_margin=ordering_margin,
        replacement_supported=replacement_supported,
        abnormal_replacement_supported=abnormal_supported,
        recovery_verified=recovery_verified and not gaps and not conflicts,
        evidence_gaps=(*conflicts, *gaps),
    )


def _append_termination_findings(
    gaps: list[str],
    conflicts: list[str],
    *,
    old_pod: PodLifecycleObservation,
    new_pod: PodLifecycleObservation,
    termination: PodTerminationObservation | None,
    correlation_window_start: datetime,
    cutoff: datetime,
    ordering_margin: timedelta,
    require_precedes_creation: bool,
) -> None:
    if termination is None:
        gaps.append("termination_observation_unavailable")
        return
    if termination.pod_uid != old_pod.pod_uid:
        conflicts.append("termination_pod_uid_conflict")
    if termination.cluster_id != old_pod.cluster_id:
        conflicts.append("termination_cluster_conflict")
    if termination.namespace != old_pod.namespace:
        conflicts.append("termination_namespace_conflict")
    if termination.event_time is None:
        gaps.append("termination_event_time_unavailable")
    elif termination.event_time < correlation_window_start:
        gaps.append("termination_event_outside_window")
    elif termination.event_time > cutoff:
        conflicts.append("termination_event_after_cutoff")
    if termination.recorded_at is None:
        gaps.append("termination_recorded_at_unavailable")
    elif termination.recorded_at > cutoff:
        conflicts.append("termination_recorded_after_cutoff")
    elif termination.event_time is not None and termination.recorded_at < termination.event_time:
        conflicts.append("termination_recorded_before_event")
    if termination.source_identity is None:
        gaps.append("termination_source_identity_unavailable")
    if termination.source_revision is None:
        gaps.append("termination_source_revision_unavailable")
    if old_pod.created_at is None:
        gaps.append("old_pod_created_at_unavailable")
    elif termination.event_time is not None and old_pod.created_at > termination.event_time:
        conflicts.append("old_pod_created_after_termination")
    if (
        require_precedes_creation
        and termination.event_time is not None
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
    state_gaps = []
    for field_name, value in (
        ("phase", pod.phase),
        ("ready", pod.ready),
        ("container_count", pod.container_count),
        ("ready_container_count", pod.ready_container_count),
    ):
        if value is None:
            state_gaps.append(f"current_pod_{field_name}_unavailable")
    gaps.extend(state_gaps)
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
    if pod.created_at is not None and deployment.metadata.effective_at < pod.created_at:
        gaps.append("deployment_evidence_before_pod_creation")
    if deployment.cluster_id != pod.cluster_id:
        conflicts.append("deployment_cluster_conflict")
    if deployment.namespace != pod.namespace:
        conflicts.append("deployment_namespace_conflict")
    if deployment.deployment_uid != pod.root_controller_uid:
        conflicts.append("deployment_uid_conflict")
        return False
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
    if desired == 0:
        gaps.append("deployment_desired_replicas_zero")
        return False
    if pod.container_count == 0:
        gaps.append("current_pod_container_count_zero")
        return False
    return (
        not state_gaps
        and pod.phase == "Running"
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


def _deployment_supports_abnormal_replacement(
    deployment: PodReplacementDeploymentObservation,
    pod: PodLifecycleObservation,
    *,
    termination: PodTerminationObservation,
    cutoff: datetime,
) -> bool:
    gaps, conflicts = _current_metadata_findings(
        deployment.metadata,
        cutoff=cutoff,
        subject="deployment",
    )
    return (
        not gaps
        and not conflicts
        and pod.root_controller_kind == "Deployment"
        and deployment.deployment_uid == pod.root_controller_uid
        and deployment.cluster_id == pod.cluster_id
        and deployment.namespace == pod.namespace
        and pod.created_at is not None
        and deployment.metadata.effective_at >= pod.created_at
        and deployment.desired_replicas_before is not None
        and deployment.desired_replicas_after is not None
        and deployment.desired_replicas_before > 0
        and deployment.desired_replicas_after > 0
        and deployment.desired_replicas_before == deployment.desired_replicas_after
        and deployment.replica_history_complete is True
        and termination.event_time is not None
        and deployment.desired_replica_history[0].observed_at <= termination.event_time
        and pod.created_at is not None
        and deployment.desired_replica_history[-1].observed_at >= pod.created_at
        and all(
            item.observed_at <= cutoff and item.observed_at <= deployment.metadata.evidence_cutoff
            for item in deployment.desired_replica_history
        )
        and all(
            item.desired_replicas == deployment.desired_replicas_before
            for item in deployment.desired_replica_history
        )
    )


def _historical_metadata_findings(
    metadata: StateFactMetadata,
    *,
    window_start: datetime,
    cutoff: datetime,
    pod_created_at: datetime | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    gaps: list[str] = []
    conflicts = [f"historical_evidence_conflict:{item}" for item in metadata.conflicts]
    if not window_start <= metadata.effective_at <= cutoff:
        gaps.append("historical_evidence_outside_window")
    if pod_created_at is None:
        gaps.append("old_pod_created_at_unavailable")
    elif metadata.effective_at < pod_created_at:
        gaps.append("historical_evidence_before_pod_creation")
    if metadata.recorded_at > cutoff:
        conflicts.append("historical_evidence_recorded_after_cutoff")
    if metadata.completeness < 1.0:
        gaps.append("historical_evidence_incomplete")
    if metadata.lane is not StateFactLane.OBSERVED:
        gaps.append("historical_evidence_not_observed")
    if metadata.authority not in {
        StateFactAuthority.PROVIDER,
        StateFactAuthority.TELEMETRY,
    }:
        gaps.append("historical_evidence_authority_invalid")
    if metadata.synthetic:
        gaps.append("historical_evidence_synthetic")
    if not metadata.source_revision:
        gaps.append("historical_source_revision_unavailable")
    return tuple(gaps), tuple(conflicts)


def _ownership_link_findings(
    pod: PodLifecycleObservation,
    *,
    subject: str,
    cutoff: datetime,
    window_start: datetime | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    gaps: list[str] = []
    conflicts: list[str] = []
    for link_name, metadata in (
        ("owner", pod.owner_link),
        ("root_controller", pod.root_controller_link),
    ):
        if metadata is None or not metadata.verified:
            gaps.append(f"{subject}_{link_name}_link_unverified")
            continue
        if window_start is None:
            link_gaps, link_conflicts = _current_metadata_findings(
                metadata.state_fact,
                cutoff=cutoff,
                subject=f"{subject}_{link_name}_link",
            )
        else:
            link_gaps, link_conflicts = _historical_metadata_findings(
                metadata.state_fact,
                window_start=window_start,
                cutoff=cutoff,
                pod_created_at=pod.created_at,
            )
            link_gaps = tuple(f"{subject}_{link_name}_link_{item}" for item in link_gaps)
            link_conflicts = tuple(f"{subject}_{link_name}_link_{item}" for item in link_conflicts)
        gaps.extend(link_gaps)
        conflicts.extend(link_conflicts)
    return tuple(gaps), tuple(conflicts)


def _current_metadata_findings(
    metadata: StateFactMetadata,
    *,
    cutoff: datetime,
    subject: str = "current_pod",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    gaps: list[str] = []
    conflicts = [f"{subject}_evidence_conflict:{item}" for item in metadata.conflicts]
    if metadata.lane is not StateFactLane.OBSERVED:
        gaps.append(f"{subject}_evidence_not_observed")
    if metadata.authority not in {
        StateFactAuthority.PROVIDER,
        StateFactAuthority.TELEMETRY,
    }:
        gaps.append(f"{subject}_evidence_authority_invalid")
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
    candidates: tuple[PodLifecycleObservation, ...] = (),
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
                    *(ref for candidate in candidates for ref in candidate.evidence_refs),
                    *(deployment.evidence_refs if deployment is not None else ()),
                )
            )
        )
    )
    candidate_pod_uids = tuple(sorted({candidate.pod_uid for candidate in candidates}))
    candidate_evidence_refs = tuple(
        sorted({ref for candidate in candidates for ref in candidate.evidence_refs})
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
        candidate_pod_uids=candidate_pod_uids,
        candidate_evidence_refs=candidate_evidence_refs,
        historical_evidence_refs=historical_refs,
        current_evidence_refs=current_refs,
    )


__all__ = [
    "KubernetesPodReplacementEvidenceResult",
    "KubernetesPodReplacementStatus",
    "DeploymentReplicaObservation",
    "PodLifecycleObservation",
    "PodReplacementDeploymentObservation",
    "PodTerminationObservation",
    "evaluate_kubernetes_pod_replacement",
]
