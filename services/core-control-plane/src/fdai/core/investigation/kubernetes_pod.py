"""Typed Kubernetes Pod lifecycle analyzer over the canonical reducers.

The threshold analyzers reduce a metric series to a bound. A Pod restart is
not that shape: distinguishing a same-UID container restart from a distinct-UID
Pod replacement, and deciding whether the workload actually recovered, needs
immutable identity, ownership, and time - which the canonical reducers in
:mod:`fdai.core.ontology_platform.kubernetes_pod_replacement_evidence` and
:mod:`fdai.core.ontology_platform.kubernetes_pod_recovery_evidence` already
decide.

This analyzer therefore observes typed evidence and delegates every conclusion
to those two reducers, then carries their verdict as a typed
:class:`~fdai.core.investigation.contract.FindingAssessment`. Nothing here
re-derives completeness or recovery from free-form text: a receipt that says
"evidence complete" or "recovery closed" is exactly what a replay of the same
observations re-derives.

Recovery closure requires **both** reducers to agree, because they read
independent observations: the replacement reducer verifies the replacement
Pod and its Deployment across the correlation window, and the recovery reducer
independently verifies the current Pod, its restart history, and its owner
Deployment at the cutoff. One reducer alone would let a single observation
both raise and clear the same finding.

Evidence is read through the :class:`PodLifecycleEvidenceSource` seam - the
same dependency-injection shape the metric analyzers use - so a deployment
binds a live source while a bounded scenario binds
:class:`StaticPodLifecycleEvidenceSource`. Nothing here executes a change.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from fdai.core.investigation.contract import AnalyzerFinding, FindingAssessment
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryEvidenceResult,
    PodOwnerDeploymentObservation,
    PodRecoveryObservation,
    PodRestartHistoryObservation,
    evaluate_kubernetes_pod_recovery,
)
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    KubernetesPodReplacementEvidenceResult,
    KubernetesPodReplacementStatus,
    PodLifecycleObservation,
    PodReplacementDeploymentObservation,
    PodTerminationObservation,
    evaluate_kubernetes_pod_replacement,
)
from fdai.shared.contracts.models import Severity

KIND_KUBERNETES_POD = "kubernetes_pod"
POD_LIFECYCLE_ASSESSOR = "core.ontology_platform.kubernetes_pod_lifecycle"
_MAX_CANDIDATES = 32

_SEVERITY_BY_STATUS = {
    KubernetesPodReplacementStatus.CONTAINER_RESTART: Severity.HIGH,
    KubernetesPodReplacementStatus.POD_REPLACEMENT: Severity.HIGH,
    KubernetesPodReplacementStatus.ROLLOUT_REPLACEMENT: Severity.MEDIUM,
    KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE: Severity.LOW,
    KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE: Severity.MEDIUM,
}

_OBSERVATION_BY_STATUS = {
    KubernetesPodReplacementStatus.CONTAINER_RESTART: (
        "A container restarted inside the same Kubernetes Pod UID."
    ),
    KubernetesPodReplacementStatus.POD_REPLACEMENT: (
        "The Kubernetes Pod was replaced by a distinct Pod UID under the same controller."
    ),
    KubernetesPodReplacementStatus.ROLLOUT_REPLACEMENT: (
        "The Kubernetes Pod was replaced during a workload revision rollout."
    ),
    KubernetesPodReplacementStatus.INSUFFICIENT_EVIDENCE: (
        "Kubernetes Pod lifecycle evidence is insufficient to classify the observation."
    ),
    KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE: (
        "Kubernetes Pod lifecycle evidence conflicts across its observation sources."
    ),
}


@dataclass(frozen=True, slots=True)
class PodLifecycleEvidence:
    """Every typed observation both canonical Pod reducers require.

    The bundle is validated as a unit so a source cannot mix one Pod's
    lifecycle observations with another Pod's recovery observations and have
    the reducers silently agree.
    """

    resource_ref: str
    old_pod: PodLifecycleObservation
    candidates: tuple[PodLifecycleObservation, ...]
    termination: PodTerminationObservation | None
    deployment: PodReplacementDeploymentObservation | None
    recovery_pod: PodRecoveryObservation
    restart_history: PodRestartHistoryObservation
    owner_deployment: PodOwnerDeploymentObservation
    correlation_window_start: datetime
    cutoff: datetime
    graph_complete: bool
    ownership_complete: bool
    detected_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.resource_ref.strip():
            raise ValueError("Pod lifecycle evidence resource_ref MUST be non-empty")
        if not self.candidates or len(self.candidates) > _MAX_CANDIDATES:
            raise ValueError("Pod lifecycle evidence MUST carry a bounded candidate set")
        for field_name in ("correlation_window_start", "cutoff"):
            value: datetime = getattr(self, field_name)
            if value.tzinfo is None:
                raise ValueError(f"Pod lifecycle evidence {field_name} MUST be timezone-aware")
        if self.correlation_window_start >= self.cutoff:
            raise ValueError("Pod lifecycle evidence window MUST be positive")
        if self.detected_at is not None and self.detected_at.tzinfo is None:
            raise ValueError("Pod lifecycle evidence detected_at MUST be timezone-aware")
        if self.restart_history.pod_id != self.recovery_pod.pod_id:
            raise ValueError("Pod restart history MUST describe the assessed Pod")
        if self.restart_history.end != self.cutoff:
            raise ValueError("Pod restart history MUST end at the evidence cutoff")
        if self.recovery_pod.pod_id not in {item.pod_id for item in self.candidates}:
            raise ValueError("Pod recovery observation MUST describe one replacement candidate")


@runtime_checkable
class PodLifecycleEvidenceSource(Protocol):
    """Return one bounded typed Pod lifecycle observation set."""

    async def observe(
        self,
        *,
        resource_ref: str,
        window_seconds: float,
    ) -> PodLifecycleEvidence | None:
        """Return the evidence for ``resource_ref``; ``None`` when unobserved."""
        ...


class StaticPodLifecycleEvidenceSource:
    """Serve pre-resolved typed evidence for an exact set of Pod resources.

    Mirrors :class:`~fdai.shared.providers.metric.StaticMetricProvider`: one
    in-memory binding of already-typed observations, used by a bounded
    replayable scenario and by any venue that resolves its Pod evidence ahead
    of the tick instead of during it.
    """

    __slots__ = ("_evidence",)

    def __init__(self, evidence: Sequence[PodLifecycleEvidence]) -> None:
        resolved: dict[str, PodLifecycleEvidence] = {}
        for item in evidence:
            if item.resource_ref in resolved:
                raise ValueError("Pod lifecycle evidence resource_ref MUST be unique")
            resolved[item.resource_ref] = item
        self._evidence = resolved

    async def observe(
        self,
        *,
        resource_ref: str,
        window_seconds: float,
    ) -> PodLifecycleEvidence | None:
        if window_seconds <= 0:
            raise ValueError("Pod lifecycle window_seconds MUST be positive")
        return self._evidence.get(resource_ref)


class KubernetesPodLifecycleAnalyzer:
    """Classify one Pod lifecycle observation with the canonical reducers."""

    __slots__ = ("_ordering_margin", "_source")

    resource_kind = KIND_KUBERNETES_POD

    def __init__(
        self,
        source: PodLifecycleEvidenceSource,
        *,
        ordering_margin: timedelta = timedelta(seconds=1),
    ) -> None:
        self._source = source
        self._ordering_margin = ordering_margin

    async def analyze(
        self,
        *,
        resource_ref: str,
        window_seconds: float,
    ) -> tuple[AnalyzerFinding, ...]:
        """Return at most one typed finding for ``resource_ref``."""

        evidence = await self._source.observe(
            resource_ref=resource_ref,
            window_seconds=window_seconds,
        )
        if evidence is None:
            return ()
        replacement = evaluate_kubernetes_pod_replacement(
            old_pod=evidence.old_pod,
            candidates=evidence.candidates,
            termination=evidence.termination,
            deployment=evidence.deployment,
            correlation_window_start=evidence.correlation_window_start,
            cutoff=evidence.cutoff,
            ordering_margin=self._ordering_margin,
        )
        recovery = evaluate_kubernetes_pod_recovery(
            pod=evidence.recovery_pod,
            restart_history=evidence.restart_history,
            owner_deployment=evidence.owner_deployment,
            cutoff=evidence.cutoff,
            graph_complete=evidence.graph_complete,
            ownership_complete=evidence.ownership_complete,
        )
        return (
            _finding(
                resource_ref=resource_ref,
                evidence=evidence,
                replacement=replacement,
                recovery=recovery,
            ),
        )


def pod_lifecycle_assessment(
    replacement: KubernetesPodReplacementEvidenceResult,
    recovery: KubernetesPodRecoveryEvidenceResult,
) -> FindingAssessment:
    """Join two independent reducers into one typed finding assessment.

    Completeness and recovery closure are conjunctions: an incomplete
    replacement correlation cannot be repaired by a complete recovery read,
    and a recovery the second observation cannot verify is not closed no
    matter what the replacement correlation concluded.
    """

    evidence_complete = replacement.complete and recovery.complete
    recovery_closed = (
        replacement.recovery_verified and recovery.recovery_verified if evidence_complete else False
    )
    return FindingAssessment(
        assessed_by=POD_LIFECYCLE_ASSESSOR,
        evidence_complete=evidence_complete,
        recovery_closed=recovery_closed,
        status=replacement.status.value,
        recovery_status=recovery.status.value,
        evidence_gaps=tuple(dict.fromkeys((*replacement.evidence_gaps, *recovery.evidence_gaps))),
    )


def _finding(
    *,
    resource_ref: str,
    evidence: PodLifecycleEvidence,
    replacement: KubernetesPodReplacementEvidenceResult,
    recovery: KubernetesPodRecoveryEvidenceResult,
) -> AnalyzerFinding:
    assessment = pod_lifecycle_assessment(replacement, recovery)
    occurred_at = evidence.detected_at or replacement.termination_time or evidence.cutoff
    return AnalyzerFinding(
        resource_ref=resource_ref,
        resource_kind=KIND_KUBERNETES_POD,
        signal=replacement.status.value,
        observation=_OBSERVATION_BY_STATUS[replacement.status],
        severity=_SEVERITY_BY_STATUS[replacement.status],
        occurred_at=occurred_at.astimezone(UTC),
        evidence_refs=tuple(
            sorted(
                {
                    *replacement.historical_evidence_refs,
                    *replacement.current_evidence_refs,
                    *recovery.evidence_refs,
                }
            )
        ),
        assessment=assessment,
    )


__all__ = [
    "KIND_KUBERNETES_POD",
    "POD_LIFECYCLE_ASSESSOR",
    "KubernetesPodLifecycleAnalyzer",
    "PodLifecycleEvidence",
    "PodLifecycleEvidenceSource",
    "StaticPodLifecycleEvidenceSource",
    "pod_lifecycle_assessment",
]
