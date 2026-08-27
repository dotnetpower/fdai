"""Reduce exact-Pod termination and log evidence without retaining raw logs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from fdai.shared.contracts.models import ContractBase

_MAX_ID_LENGTH = 512
_MAX_REASONS = 32
_MAX_REFS = 256


class KubernetesPodDiagnosisStatus(StrEnum):
    """Calibrated classification of one exact container termination."""

    OOM_KILLED = "oom_killed"
    PROBE_FAILURE_EVIDENCE = "probe_failure_evidence"
    NORMAL_EXIT = "normal_exit"
    ABNORMAL_EXIT = "abnormal_exit"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


@dataclass(frozen=True, slots=True)
class ContainerTerminationEvidence:
    """Bounded authoritative termination fields for one container."""

    pod_uid: str
    container_name: str
    reason: str | None
    exit_code: int
    signal: int | None
    finished_at: datetime | None
    lifecycle_reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("pod_uid", "container_name"):
            value = getattr(self, field_name)
            if not value.strip() or len(value) > _MAX_ID_LENGTH:
                raise ValueError(f"{field_name} MUST be bounded non-empty text")
        if self.reason is not None and (
            not self.reason.strip() or len(self.reason) > _MAX_ID_LENGTH
        ):
            raise ValueError("termination reason MUST be bounded non-empty text or null")
        for field_name in ("exit_code", "signal"):
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError(f"{field_name} MUST be a non-negative integer or null")
        if self.finished_at is not None and self.finished_at.tzinfo is None:
            raise ValueError("termination finished_at MUST be timezone-aware")
        _require_bounded_unique(self.lifecycle_reasons, "lifecycle_reasons", _MAX_REASONS)
        _require_bounded_unique(self.evidence_refs, "evidence_refs", _MAX_REFS)
        if not self.evidence_refs:
            raise ValueError("termination evidence MUST cite at least one source")


@dataclass(frozen=True, slots=True)
class KubernetesPodLogEvidence:
    """Content-free summary of one exact Pod log query."""

    pod_uid: str
    start: datetime
    end: datetime
    source_identity: str
    complete: bool
    limitation: str | None
    total_records: int
    error_records: int
    first_recorded_at: datetime | None
    last_recorded_at: datetime | None
    record_digests: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("pod_uid", "source_identity"):
            value = getattr(self, field_name)
            if not value.strip() or len(value) > _MAX_ID_LENGTH:
                raise ValueError(f"{field_name} MUST be bounded non-empty text")
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("Pod log evidence MUST have an aware positive interval")
        if self.complete != (self.limitation is None):
            raise ValueError("Pod log evidence completeness and limitation are inconsistent")
        if self.total_records < 0 or not 0 <= self.error_records <= self.total_records:
            raise ValueError("Pod log evidence counts are inconsistent")
        if len(self.record_digests) != self.total_records:
            raise ValueError("Pod log evidence MUST retain one digest per record")
        if len(self.record_digests) > _MAX_REFS or any(
            not value.startswith("sha256:") or len(value) != 71 for value in self.record_digests
        ):
            raise ValueError("record_digests MUST contain bounded SHA-256 digests")
        _require_bounded_unique(self.evidence_refs, "evidence_refs", _MAX_REFS)
        if self.total_records == 0:
            if self.first_recorded_at is not None or self.last_recorded_at is not None:
                raise ValueError("empty Pod log evidence cannot carry record timestamps")
        elif (
            self.first_recorded_at is None
            or self.last_recorded_at is None
            or self.first_recorded_at.tzinfo is None
            or self.last_recorded_at.tzinfo is None
            or not self.start <= self.first_recorded_at <= self.last_recorded_at <= self.end
        ):
            raise ValueError("Pod log evidence timestamps are outside the query interval")


class KubernetesPodDiagnosisResult(ContractBase):
    """Replayable no-authority Pod diagnosis evidence."""

    pod_uid: str
    container_name: str | None
    status: KubernetesPodDiagnosisStatus
    complete: bool
    termination_reason: str | None
    exit_code: int | None
    signal: int | None
    finished_at: datetime | None
    log_source_identity: str
    log_record_count: int
    log_error_record_count: int
    evidence_gaps: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    cause_claim_supported: Literal[False] = False
    execution_authority: Literal[False] = False


def assess_kubernetes_pod_diagnosis(
    *,
    pod_uid: str,
    termination: ContainerTerminationEvidence | None,
    logs: KubernetesPodLogEvidence,
    cutoff: datetime,
) -> KubernetesPodDiagnosisResult:
    """Classify bounded termination evidence while keeping causal authority false."""

    if not pod_uid.strip() or len(pod_uid) > _MAX_ID_LENGTH:
        raise ValueError("pod_uid MUST be bounded non-empty text")
    if cutoff.tzinfo is None:
        raise ValueError("Pod diagnosis cutoff MUST be timezone-aware")
    gaps: list[str] = []
    conflicts: list[str] = []
    if logs.pod_uid != pod_uid:
        conflicts.append("log_pod_uid_conflict")
    if logs.end != cutoff:
        conflicts.append("log_cutoff_conflict")
    if not logs.complete:
        gaps.append(f"logs_{logs.limitation or 'incomplete'}")
    if termination is None:
        gaps.append("termination_unavailable")
        status = KubernetesPodDiagnosisStatus.INSUFFICIENT_EVIDENCE
    else:
        if termination.pod_uid != pod_uid:
            conflicts.append("termination_pod_uid_conflict")
        if termination.finished_at is None:
            gaps.append("termination_finished_at_unavailable")
        elif termination.finished_at > cutoff:
            conflicts.append("termination_after_cutoff")
        status = _termination_status(termination, conflicts=conflicts, gaps=gaps)
    if conflicts:
        status = KubernetesPodDiagnosisStatus.CONFLICTING_EVIDENCE
    elif gaps and status not in {
        KubernetesPodDiagnosisStatus.OOM_KILLED,
        KubernetesPodDiagnosisStatus.PROBE_FAILURE_EVIDENCE,
        KubernetesPodDiagnosisStatus.NORMAL_EXIT,
        KubernetesPodDiagnosisStatus.ABNORMAL_EXIT,
    }:
        status = KubernetesPodDiagnosisStatus.INSUFFICIENT_EVIDENCE
    complete = not gaps and not conflicts
    evidence_refs = tuple(
        dict.fromkeys(
            (
                *(termination.evidence_refs if termination is not None else ()),
                *logs.evidence_refs,
            )
        )
    )
    return KubernetesPodDiagnosisResult(
        pod_uid=pod_uid,
        container_name=termination.container_name if termination is not None else None,
        status=status,
        complete=complete,
        termination_reason=termination.reason if termination is not None else None,
        exit_code=termination.exit_code if termination is not None else None,
        signal=termination.signal if termination is not None else None,
        finished_at=termination.finished_at if termination is not None else None,
        log_source_identity=logs.source_identity,
        log_record_count=logs.total_records,
        log_error_record_count=logs.error_records,
        evidence_gaps=tuple((*conflicts, *gaps)),
        evidence_refs=evidence_refs,
    )


def _termination_status(
    termination: ContainerTerminationEvidence,
    *,
    conflicts: list[str],
    gaps: list[str],
) -> KubernetesPodDiagnosisStatus:
    reason = termination.reason
    if reason == "OOMKilled":
        if termination.exit_code != 137:
            conflicts.append("oom_exit_code_conflict")
            return KubernetesPodDiagnosisStatus.CONFLICTING_EVIDENCE
        return KubernetesPodDiagnosisStatus.OOM_KILLED
    if "Unhealthy" in termination.lifecycle_reasons:
        if termination.exit_code == 0:
            conflicts.append("probe_failure_exit_code_conflict")
            return KubernetesPodDiagnosisStatus.CONFLICTING_EVIDENCE
        return KubernetesPodDiagnosisStatus.PROBE_FAILURE_EVIDENCE
    if reason == "Completed":
        if termination.exit_code != 0:
            conflicts.append("completed_exit_code_conflict")
            return KubernetesPodDiagnosisStatus.CONFLICTING_EVIDENCE
        return KubernetesPodDiagnosisStatus.NORMAL_EXIT
    if termination.exit_code > 0:
        return KubernetesPodDiagnosisStatus.ABNORMAL_EXIT
    gaps.append("termination_classification_unavailable")
    return KubernetesPodDiagnosisStatus.INSUFFICIENT_EVIDENCE


def _require_bounded_unique(values: tuple[str, ...], field: str, limit: int) -> None:
    if len(values) > limit or len(values) != len(set(values)):
        raise ValueError(f"{field} MUST be unique within its bound")
    if any(not value.strip() or len(value) > _MAX_ID_LENGTH for value in values):
        raise ValueError(f"{field} MUST contain bounded non-empty text")


__all__ = [
    "ContainerTerminationEvidence",
    "KubernetesPodDiagnosisResult",
    "KubernetesPodDiagnosisStatus",
    "KubernetesPodLogEvidence",
    "assess_kubernetes_pod_diagnosis",
]
