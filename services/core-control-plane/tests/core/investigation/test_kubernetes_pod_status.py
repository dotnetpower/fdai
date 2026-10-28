"""Provider-state qualification and prior-fault-only Pod recovery."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.investigation.contract import AnalyzerFinding
from fdai.core.investigation.kubernetes_pod_status import (
    KubernetesPodStatusAnalyzer,
    PodStatusEvidence,
    assess_pod_status,
    assess_pod_status_recovery,
)
from fdai.core.ontology_platform.kubernetes_pod_diagnosis_evidence import (
    ContainerTerminationEvidence,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import PodRecoveryObservation
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
RESOURCE = "resource:example-pod"


def _evidence() -> PodStatusEvidence:
    return PodStatusEvidence(
        resource_ref=RESOURCE,
        pod_uid="uid-example",
        pod=PodRecoveryObservation(
            pod_id=RESOURCE,
            phase="Running",
            ready=True,
            container_count=1,
            ready_container_count=1,
            restart_count=1,
            waiting_reasons=(),
            metadata=StateFactMetadata(
                lane=StateFactLane.OBSERVED,
                authority=StateFactAuthority.PROVIDER,
                source_identity="provider-example",
                source_revision="current-example",
                effective_at=NOW,
                recorded_at=NOW,
                evidence_cutoff=NOW,
                freshness_ceiling_seconds=60,
                completeness=1,
                synthetic=False,
                evidence_refs=("pod:current-example",),
            ),
        ),
        terminations=(),
        start=NOW - timedelta(minutes=5),
        cutoff=NOW,
    )


def _prior() -> AnalyzerFinding:
    return AnalyzerFinding(
        resource_ref=RESOURCE,
        resource_kind="kubernetes_pod",
        signal="pod_crash_loop_back_off",
        severity=Severity.HIGH,
        observation="Provider observed CrashLoopBackOff.",
        occurred_at=NOW - timedelta(seconds=10),
        evidence_refs=("pod:prior-fault-example",),
    )


@pytest.mark.parametrize(
    ("changes", "signal"),
    [
        ({"conflicts": ("equal_time_conflict",)}, "conflicting_evidence"),
        ({"synthetic": True}, "insufficient_evidence"),
        ({"completeness": 0.5}, "insufficient_evidence"),
        (
            {
                "effective_at": NOW - timedelta(minutes=10),
                "evidence_cutoff": NOW - timedelta(minutes=10),
            },
            "stale_evidence",
        ),
    ],
)
def test_unqualified_evidence_is_never_a_healthy_or_positive_failure(
    changes: dict[str, object], signal: str
) -> None:
    evidence = _evidence()
    pod = replace(evidence.pod, metadata=replace(evidence.pod.metadata, **changes))
    evidence = replace(evidence, pod=pod)
    findings = assess_pod_status(evidence)
    assert [finding.signal for finding in findings] == [signal]
    assert findings[0].assessment is not None
    assert not findings[0].assessment.evidence_complete
    assert not findings[0].assessment.recovery_closed
    assert assess_pod_status_recovery(evidence, prior=_prior()) is None


def test_unknown_phase_stays_unknown() -> None:
    evidence = _evidence()
    evidence = replace(evidence, pod=replace(evidence.pod, phase="Unknown", ready=None))
    findings = assess_pod_status(evidence)
    assert [finding.signal for finding in findings] == ["insufficient_evidence"]


def test_contradictory_ready_and_container_counts_stay_conflicting() -> None:
    evidence = _evidence()
    evidence = replace(evidence, pod=replace(evidence.pod, ready_container_count=0))
    assert [finding.signal for finding in assess_pod_status(evidence)] == ["conflicting_evidence"]


def test_normal_pending_does_not_create_a_failure() -> None:
    evidence = _evidence()
    evidence = replace(evidence, pod=replace(evidence.pod, phase="Pending", ready=False))
    assert assess_pod_status(evidence) == ()


def test_healthy_reading_never_creates_a_finding() -> None:
    assert assess_pod_status(_evidence()) == ()


def test_recovery_requires_prior_actual_fault_and_preserves_signal_and_evidence() -> None:
    prior = _prior()
    recovered = assess_pod_status_recovery(_evidence(), prior=prior)
    assert recovered is not None and recovered.assessment is not None
    assert recovered.signal == prior.signal
    assert recovered.severity == prior.severity
    assert recovered.assessment.evidence_complete
    assert recovered.assessment.recovery_closed
    assert set(recovered.evidence_refs) == {"pod:current-example", "pod:prior-fault-example"}


@pytest.mark.parametrize(
    "changes",
    [
        {"signal": "healthy"},
        {"resource_ref": "resource:foreign"},
        {"resource_kind": "vm"},
        {"evidence_refs": ()},
        {"occurred_at": NOW},
        {"occurred_at": NOW + timedelta(seconds=5)},
    ],
)
def test_invalid_or_nonfault_prior_cannot_authorize_recovery(changes: dict[str, object]) -> None:
    assert assess_pod_status_recovery(_evidence(), prior=replace(_prior(), **changes)) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"ready": False},
        {"waiting_reasons": ("CrashLoopBackOff",)},
        {"container_count": 0, "ready_container_count": 0},
        {"restart_count": None},
    ],
)
def test_current_failure_or_missing_positive_evidence_does_not_close(
    changes: dict[str, object],
) -> None:
    evidence = _evidence()
    assert (
        assess_pod_status_recovery(
            replace(evidence, pod=replace(evidence.pod, **changes)), prior=_prior()
        )
        is None
    )


def test_history_gap_remains_explicit_and_cannot_close_recovery() -> None:
    evidence = replace(_evidence(), evidence_gaps=("kubernetes_lifecycle_cursor_expired",))
    assert assess_pod_status_recovery(evidence, prior=_prior()) is None


def _termination(time: datetime, container_name: str = "example") -> ContainerTerminationEvidence:
    return ContainerTerminationEvidence(
        pod_uid="uid-example",
        container_name=container_name,
        reason="OOMKilled",
        exit_code=137,
        signal=9,
        finished_at=time,
        lifecycle_reasons=(),
        evidence_refs=(f"termination:{container_name}",),
    )


def test_old_prior_termination_does_not_forever_block_independent_current_recovery() -> None:
    evidence = replace(_evidence(), terminations=(_termination(_prior().occurred_at),))
    recovered = assess_pod_status_recovery(evidence, prior=_prior())
    assert recovered is not None and recovered.assessment is not None
    assert recovered.assessment.recovery_closed


def test_newer_termination_keeps_the_existing_fault_open() -> None:
    evidence = replace(_evidence(), terminations=(_termination(NOW - timedelta(seconds=5)),))
    assert assess_pod_status_recovery(evidence, prior=_prior()) is None


def test_multiple_containers_preserve_all_termination_citations_in_one_signal() -> None:
    evidence = replace(
        _evidence(),
        terminations=(
            _termination(NOW - timedelta(seconds=5), "example-a"),
            _termination(NOW - timedelta(seconds=4), "example-b"),
        ),
    )
    findings = assess_pod_status(evidence)
    assert [finding.signal for finding in findings] == ["pod_oom_killed"]
    assert set(findings[0].evidence_refs) == {
        "pod:current-example",
        "termination:example-a",
        "termination:example-b",
    }


async def test_optional_recovery_api_uses_only_the_requested_active_finding_target() -> None:
    source = SimpleNamespace(observe_status=AsyncMock(return_value=_evidence()))
    analyzer = KubernetesPodStatusAnalyzer(source)
    recovered = await analyzer.assess_recovery(prior=_prior(), window_seconds=60)
    assert recovered is not None and recovered.assessment is not None
    assert recovered.assessment.recovery_closed
    source.observe_status.assert_awaited_once_with(resource_ref=RESOURCE, window_seconds=60)
