"""Read-only Pod status findings over typed provider and diagnosis evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.core.investigation.contract import AnalyzerFinding, FindingAssessment
from fdai.core.investigation.kubernetes_pod import (
    KIND_KUBERNETES_POD,
    KubernetesPodLifecycleAnalyzer,
    PodLifecycleEvidence,
    StaticPodLifecycleEvidenceSource,
)
from fdai.core.ontology_platform.kubernetes_pod_diagnosis_evidence import (
    ContainerTerminationEvidence,
    KubernetesPodDiagnosisStatus,
    KubernetesPodLogEvidence,
    assess_kubernetes_pod_diagnosis,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import PodRecoveryObservation
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.state_evidence import StateFactAuthority, StateFactLane

POD_STATUS_ASSESSOR = "core.investigation.kubernetes_pod_status"
POD_STATUS_FAULT_SIGNALS = frozenset(
    {
        "pod_crash_loop_back_off",
        "pod_oom_killed",
        "pod_abnormal_termination",
        "pod_probe_failure",
        "pod_failed",
        "pod_unready",
    }
)


@dataclass(frozen=True, slots=True)
class PodStatusEvidence:
    """Current exact-UID facts; retained terminations stay inside the requested window."""

    resource_ref: str
    pod_uid: str
    pod: PodRecoveryObservation
    terminations: tuple[ContainerTerminationEvidence, ...]
    start: datetime
    cutoff: datetime
    evidence_gaps: tuple[str, ...] = ()
    rollout_observed: bool = False

    def __post_init__(self) -> None:
        if (
            not self.resource_ref.strip()
            or not self.pod_uid.strip()
            or self.resource_ref != self.pod.pod_id
        ):
            raise ValueError("Pod status MUST bind one exact Resource and Pod UID")
        if (
            self.start.tzinfo is None
            or self.start.utcoffset() is None
            or self.cutoff.tzinfo is None
            or self.cutoff.utcoffset() is None
            or self.start >= self.cutoff
        ):
            raise ValueError("Pod status MUST have an aware positive window")
        if not isinstance(self.rollout_observed, bool):
            raise ValueError("Pod status rollout_observed MUST be a boolean")
        if len(self.terminations) > 256:
            raise ValueError("Pod status termination bound exceeded")
        if any(item.pod_uid != self.pod_uid for item in self.terminations):
            raise ValueError("Pod status termination UID conflict")
        if any(not gap.strip() for gap in self.evidence_gaps):
            raise ValueError("Pod status evidence_gaps MUST be non-empty strings")


@dataclass(frozen=True, slots=True)
class PodFailureEvidence:
    """One read shared by the lifecycle and current-status analyzers."""

    lifecycle: PodLifecycleEvidence | None
    status: PodStatusEvidence | None


class PodStatusEvidenceSource(Protocol):
    async def observe_status(
        self, *, resource_ref: str, window_seconds: float
    ) -> PodStatusEvidence | None: ...


@runtime_checkable
class PodFailureEvidenceSource(Protocol):
    async def observe_pod(
        self, *, resource_ref: str, window_seconds: float
    ) -> PodFailureEvidence: ...


def assess_pod_status(evidence: PodStatusEvidence) -> tuple[AnalyzerFinding, ...]:
    """Reduce provider status without inferring OOM, cause, or recovery from an exit code."""

    metadata = evidence.pod.metadata
    gaps = list(evidence.evidence_gaps)
    if metadata.conflicts or metadata.recorded_at > evidence.cutoff:
        return (_diagnostic(evidence, "conflicting_evidence", ("pod_state_conflict",)),)
    if (
        metadata.lane is not StateFactLane.OBSERVED
        or metadata.authority not in {StateFactAuthority.PROVIDER, StateFactAuthority.TELEMETRY}
        or metadata.synthetic
        or metadata.completeness < 1
    ):
        return (_diagnostic(evidence, "insufficient_evidence", ("pod_state_unverified",)),)
    if (
        evidence.cutoff - metadata.evidence_cutoff
    ).total_seconds() > metadata.freshness_ceiling_seconds:
        return (_diagnostic(evidence, "stale_evidence", ("pod_state_stale",)),)
    if evidence.pod.ready is True and (
        evidence.pod.phase != "Running"
        or (
            evidence.pod.container_count is not None
            and evidence.pod.ready_container_count is not None
            and evidence.pod.container_count != evidence.pod.ready_container_count
        )
    ):
        return (_diagnostic(evidence, "conflicting_evidence", ("pod_readiness_conflict",)),)
    if evidence.pod.phase in {None, "Unknown"}:
        return (_diagnostic(evidence, "insufficient_evidence", ("pod_phase_unavailable",)),)

    findings: list[AnalyzerFinding] = []
    if "CrashLoopBackOff" in evidence.pod.waiting_reasons:
        findings.append(
            _status_finding(
                evidence,
                "pod_crash_loop_back_off",
                "The Kubernetes API reports CrashLoopBackOff for this exact Pod UID.",
                Severity.HIGH,
                gaps=tuple(gaps),
            )
        )
    for termination in evidence.terminations:
        if termination.finished_at is None or not (
            evidence.start <= termination.finished_at <= evidence.cutoff
        ):
            continue
        # Logs are not required to observe an exit. They remain explicitly
        # unavailable for the stronger diagnostic-completeness/cause claim.
        diagnosis = assess_kubernetes_pod_diagnosis(
            pod_uid=evidence.pod_uid,
            termination=termination,
            logs=KubernetesPodLogEvidence(
                pod_uid=evidence.pod_uid,
                start=evidence.start,
                end=evidence.cutoff,
                source_identity="pod-status-no-log-query",
                source_revision="pod-status.v1",
                complete=False,
                limitation="source_unavailable",
                total_records=0,
                error_records=0,
                first_recorded_at=None,
                last_recorded_at=None,
                record_digests=(),
                evidence_refs=metadata.evidence_refs,
            ),
            cutoff=evidence.cutoff,
        )
        if diagnosis.status is KubernetesPodDiagnosisStatus.CONFLICTING_EVIDENCE:
            findings.append(_diagnostic(evidence, "conflicting_evidence", diagnosis.evidence_gaps))
            continue
        signals = {
            KubernetesPodDiagnosisStatus.OOM_KILLED: (
                "pod_oom_killed",
                "The Kubernetes API reports an OOMKilled container termination.",
            ),
            KubernetesPodDiagnosisStatus.ABNORMAL_EXIT: (
                "pod_abnormal_termination",
                "The Kubernetes API reports a nonzero container exit; its cause is unverified.",
            ),
            KubernetesPodDiagnosisStatus.PROBE_FAILURE_EVIDENCE: (
                "pod_probe_failure",
                "Container termination and exact-UID lifecycle evidence report a probe failure.",
            ),
        }
        selected = signals.get(diagnosis.status)
        if selected is not None:
            findings.append(
                _status_finding(
                    evidence,
                    *selected,
                    Severity.HIGH,
                    occurred_at=termination.finished_at,
                    refs=diagnosis.evidence_refs,
                    gaps=tuple(dict.fromkeys((*gaps, *diagnosis.evidence_gaps))),
                )
            )
    if evidence.pod.phase == "Failed":
        findings.append(
            _status_finding(
                evidence,
                "pod_failed",
                "The Kubernetes API reports Failed phase for this exact Pod UID.",
                Severity.HIGH,
                gaps=tuple(gaps),
            )
        )
    elif (
        not findings
        and not evidence.rollout_observed
        and evidence.pod.phase == "Running"
        and evidence.pod.ready is False
    ):
        findings.append(
            _status_finding(
                evidence,
                "pod_unready",
                "The Kubernetes API reports that this exact Pod UID is not Ready.",
                Severity.MEDIUM,
                gaps=tuple(gaps),
            )
        )
    # Several containers may share a status. One resource/signal finding keeps
    # all citations instead of silently dropping a container's evidence.
    by_signal: dict[str, AnalyzerFinding] = {}
    for finding in findings:
        previous = by_signal.get(finding.signal)
        if previous is None:
            by_signal[finding.signal] = finding
        else:
            by_signal[finding.signal] = replace(
                previous,
                evidence_refs=tuple(sorted(set((*previous.evidence_refs, *finding.evidence_refs)))),
                occurred_at=max(previous.occurred_at, finding.occurred_at),
                assessment=(
                    replace(
                        previous.assessment,
                        evidence_complete=(
                            previous.assessment.evidence_complete
                            and finding.assessment.evidence_complete
                        ),
                        evidence_gaps=tuple(
                            sorted(
                                set(
                                    (
                                        *previous.assessment.evidence_gaps,
                                        *finding.assessment.evidence_gaps,
                                    )
                                )
                            )
                        ),
                    )
                    if previous.assessment is not None and finding.assessment is not None
                    else None
                ),
            )
    return tuple(by_signal[key] for key in sorted(by_signal))


class KubernetesPodStatusAnalyzer:
    resource_kind = KIND_KUBERNETES_POD

    def __init__(self, source: PodStatusEvidenceSource) -> None:
        self._source = source

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> tuple[AnalyzerFinding, ...]:
        if not resource_ref.strip():
            raise ValueError("KubernetesPodStatusAnalyzer.resource_ref MUST be non-empty")
        if (
            isinstance(window_seconds, bool)
            or not math.isfinite(window_seconds)
            or window_seconds <= 0
        ):
            raise ValueError("KubernetesPodStatusAnalyzer.window_seconds MUST be positive")
        evidence = await self._source.observe_status(
            resource_ref=resource_ref, window_seconds=window_seconds
        )
        return assess_pod_status(evidence) if evidence is not None else ()

    async def assess_recovery(
        self, *, prior: AnalyzerFinding, window_seconds: float
    ) -> AnalyzerFinding | None:
        """Caller must supply an actual active finding, never an ordinary healthy sample."""
        if (
            isinstance(window_seconds, bool)
            or not math.isfinite(window_seconds)
            or window_seconds <= 0
        ):
            raise ValueError("KubernetesPodStatusAnalyzer.window_seconds MUST be positive")

        evidence = await self._source.observe_status(
            resource_ref=prior.resource_ref, window_seconds=window_seconds
        )
        return assess_pod_status_recovery(evidence, prior=prior) if evidence is not None else None


class KubernetesPodFailureAnalyzer:
    """Combine lifecycle and status once; a verified rollout is not a failure."""

    resource_kind = KIND_KUBERNETES_POD

    def __init__(self, source: PodFailureEvidenceSource) -> None:
        self._source = source

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> tuple[AnalyzerFinding, ...]:
        if not resource_ref.strip():
            raise ValueError("KubernetesPodFailureAnalyzer.resource_ref MUST be non-empty")
        if (
            isinstance(window_seconds, bool)
            or not math.isfinite(window_seconds)
            or window_seconds <= 0
        ):
            raise ValueError("KubernetesPodFailureAnalyzer.window_seconds MUST be positive")
        evidence = await self._source.observe_pod(
            resource_ref=resource_ref, window_seconds=window_seconds
        )
        findings = assess_pod_status(evidence.status) if evidence.status is not None else ()
        if evidence.lifecycle is None:
            return findings
        lifecycle_findings = await KubernetesPodLifecycleAnalyzer(
            StaticPodLifecycleEvidenceSource((evidence.lifecycle,))
        ).analyze(resource_ref=resource_ref, window_seconds=window_seconds)
        return (
            *findings,
            *(item for item in lifecycle_findings if item.signal != "rollout_replacement"),
        )

    async def assess_recovery(
        self, *, prior: AnalyzerFinding, window_seconds: float
    ) -> AnalyzerFinding | None:
        """Assess an existing status fault only; lifecycle recovery uses its own reducers."""

        evidence = await self._source.observe_pod(
            resource_ref=prior.resource_ref, window_seconds=window_seconds
        )
        return (
            assess_pod_status_recovery(evidence.status, prior=prior)
            if evidence.status is not None
            else None
        )


def assess_pod_status_recovery(
    evidence: PodStatusEvidence, *, prior: AnalyzerFinding
) -> AnalyzerFinding | None:
    """Require a prior grounded fault and an independent later complete Ready observation."""

    pod = evidence.pod
    if (
        prior.resource_kind != KIND_KUBERNETES_POD
        or prior.resource_ref != evidence.resource_ref
        or prior.signal not in POD_STATUS_FAULT_SIGNALS
        or not prior.evidence_refs
        or prior.occurred_at.tzinfo is None
        or (prior.assessment is not None and prior.assessment.recovery_closed is True)
        or pod.metadata.effective_at <= prior.occurred_at
        or evidence.evidence_gaps
        or evidence.rollout_observed
        or pod.phase != "Running"
        or pod.ready is not True
        or not pod.container_count
        or pod.ready_container_count != pod.container_count
        or pod.restart_count is None
        or pod.waiting_reasons
    ):
        return None
    current_only = replace(
        evidence,
        terminations=tuple(
            item
            for item in evidence.terminations
            if item.finished_at is None or item.finished_at > prior.occurred_at
        ),
    )
    if assess_pod_status(current_only):
        return None
    finding = _status_finding(
        evidence,
        prior.signal,
        "Fresh Kubernetes API status confirms this Pod is Ready after the prior active fault.",
        prior.severity,
        refs=prior.evidence_refs,
    )
    return replace(
        finding,
        assessment=FindingAssessment(
            assessed_by=POD_STATUS_ASSESSOR,
            evidence_complete=True,
            recovery_closed=True,
            status=prior.signal,
            recovery_status="pod_ready_after_fault",
        ),
    )


def _status_finding(
    evidence: PodStatusEvidence,
    signal: str,
    observation: str,
    severity: Severity,
    *,
    occurred_at: datetime | None = None,
    refs: tuple[str, ...] = (),
    gaps: tuple[str, ...] = (),
) -> AnalyzerFinding:
    return AnalyzerFinding(
        resource_ref=evidence.resource_ref,
        resource_kind=KIND_KUBERNETES_POD,
        signal=signal,
        observation=observation,
        severity=severity,
        occurred_at=occurred_at or evidence.pod.metadata.effective_at,
        evidence_refs=tuple(sorted(set((*evidence.pod.metadata.evidence_refs, *refs)))),
        assessment=FindingAssessment(
            assessed_by=POD_STATUS_ASSESSOR,
            evidence_complete=not gaps,
            recovery_closed=False,
            status=signal,
            evidence_gaps=gaps,
        ),
    )


def _diagnostic(evidence: PodStatusEvidence, status: str, gaps: tuple[str, ...]) -> AnalyzerFinding:
    return _status_finding(
        evidence,
        status,
        "Kubernetes Pod status evidence cannot support a failure or recovery conclusion.",
        Severity.LOW,
        gaps=gaps,
    )
