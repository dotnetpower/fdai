"""Exact-Pod termination and content-free log evidence tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.kubernetes_pod_diagnosis_evidence import (
    ContainerTerminationEvidence,
    KubernetesPodDiagnosisStatus,
    KubernetesPodLogEvidence,
    assess_kubernetes_pod_diagnosis,
)

_END = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
_START = _END - timedelta(minutes=15)


def _termination(**changes: object) -> ContainerTerminationEvidence:
    values: dict[str, object] = {
        "pod_uid": "pod-uid-a",
        "container_name": "api",
        "reason": "OOMKilled",
        "exit_code": 137,
        "signal": 9,
        "finished_at": _END - timedelta(minutes=5),
        "lifecycle_reasons": ("Killing",),
        "evidence_refs": ("pod-status:pod-uid-a",),
    }
    values.update(changes)
    return ContainerTerminationEvidence(**values)  # type: ignore[arg-type]


def _logs(**changes: object) -> KubernetesPodLogEvidence:
    values: dict[str, object] = {
        "pod_uid": "pod-uid-a",
        "start": _START,
        "end": _END,
        "source_identity": "azure-monitor",
        "complete": True,
        "limitation": None,
        "total_records": 1,
        "error_records": 1,
        "first_recorded_at": _END - timedelta(minutes=5),
        "last_recorded_at": _END - timedelta(minutes=5),
        "record_digests": ("sha256:" + ("a" * 64),),
        "evidence_refs": ("pod-log-source:azure-monitor",),
    }
    values.update(changes)
    return KubernetesPodLogEvidence(**values)  # type: ignore[arg-type]


def test_oom_termination_is_classified_without_causal_authority() -> None:
    result = assess_kubernetes_pod_diagnosis(
        pod_uid="pod-uid-a",
        termination=_termination(),
        logs=_logs(),
        cutoff=_END,
    )

    assert result.status is KubernetesPodDiagnosisStatus.OOM_KILLED
    assert result.complete is True
    assert result.cause_claim_supported is False
    assert result.execution_authority is False


def test_probe_failure_requires_nonzero_exit_and_unhealthy_lifecycle_evidence() -> None:
    result = assess_kubernetes_pod_diagnosis(
        pod_uid="pod-uid-a",
        termination=_termination(
            reason="Error",
            exit_code=1,
            signal=0,
            lifecycle_reasons=("Unhealthy", "Killing"),
        ),
        logs=_logs(),
        cutoff=_END,
    )

    assert result.status is KubernetesPodDiagnosisStatus.PROBE_FAILURE_EVIDENCE
    assert result.complete is True


def test_completed_zero_exit_is_normal_without_a_cause_claim() -> None:
    result = assess_kubernetes_pod_diagnosis(
        pod_uid="pod-uid-a",
        termination=_termination(
            reason="Completed",
            exit_code=0,
            signal=0,
            lifecycle_reasons=(),
        ),
        logs=_logs(
            total_records=0,
            error_records=0,
            first_recorded_at=None,
            last_recorded_at=None,
            record_digests=(),
        ),
        cutoff=_END,
    )

    assert result.status is KubernetesPodDiagnosisStatus.NORMAL_EXIT
    assert result.cause_claim_supported is False


def test_unavailable_logs_remain_an_explicit_gap() -> None:
    result = assess_kubernetes_pod_diagnosis(
        pod_uid="pod-uid-a",
        termination=_termination(),
        logs=_logs(
            complete=False,
            limitation="source_unavailable",
            total_records=0,
            error_records=0,
            first_recorded_at=None,
            last_recorded_at=None,
            record_digests=(),
        ),
        cutoff=_END,
    )

    assert result.status is KubernetesPodDiagnosisStatus.OOM_KILLED
    assert result.complete is False
    assert result.evidence_gaps == ("logs_source_unavailable",)


def test_contradictory_termination_fields_fail_closed() -> None:
    result = assess_kubernetes_pod_diagnosis(
        pod_uid="pod-uid-a",
        termination=replace(_termination(), exit_code=0),
        logs=_logs(),
        cutoff=_END,
    )

    assert result.status is KubernetesPodDiagnosisStatus.CONFLICTING_EVIDENCE
    assert result.complete is False
    assert result.evidence_gaps == ("oom_exit_code_conflict",)


def test_missing_termination_remains_insufficient() -> None:
    result = assess_kubernetes_pod_diagnosis(
        pod_uid="pod-uid-a",
        termination=None,
        logs=_logs(),
        cutoff=_END,
    )

    assert result.status is KubernetesPodDiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_gaps == ("termination_unavailable",)
