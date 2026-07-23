"""Truth table for fail-closed startup readiness reduction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.readiness import (
    AuthorityCeiling,
    ProbeCriticality,
    ProbeStatus,
    ReadinessDecision,
    StartupPhase,
    StartupProbeResult,
    StartupProbeSpec,
    reduce_startup_readiness,
)

_NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _spec(
    criticality: ProbeCriticality,
    *,
    capability: str = "audit",
    ceiling: AuthorityCeiling = AuthorityCeiling.DISABLED,
) -> StartupProbeSpec:
    return StartupProbeSpec(
        probe_id=f"{capability}.probe",
        capability=capability,
        phase=StartupPhase.REQUIRED_REACHABILITY,
        criticality=criticality,
        failure_ceiling=ceiling,
    )


def _result(status: ProbeStatus, *, expires_at: datetime | None = None) -> StartupProbeResult:
    return StartupProbeResult(
        probe_id="audit.probe",
        status=status,
        observed_at=_NOW - timedelta(seconds=1),
        expires_at=expires_at or _NOW + timedelta(minutes=5),
        latency_ms=12.5,
        failure_class=None if status is ProbeStatus.PASSED else "dependency_unavailable",
    )


@pytest.mark.parametrize(
    "status",
    [ProbeStatus.FAILED, ProbeStatus.TIMED_OUT, ProbeStatus.CRASHED],
)
def test_process_critical_non_passed_result_is_blocked(status: ProbeStatus) -> None:
    report = reduce_startup_readiness(
        [_spec(ProbeCriticality.PROCESS_CRITICAL)],
        [_result(status)],
        generated_at=_NOW,
    )

    assert report.decision is ReadinessDecision.BLOCKED
    assert report.authority_ceilings == {"audit": AuthorityCeiling.DISABLED}


def test_missing_process_critical_result_is_blocked() -> None:
    report = reduce_startup_readiness(
        [_spec(ProbeCriticality.PROCESS_CRITICAL)],
        [],
        generated_at=_NOW,
    )

    assert report.decision is ReadinessDecision.BLOCKED
    assert report.missing_probe_ids == ("audit.probe",)


def test_stale_process_critical_result_is_blocked() -> None:
    report = reduce_startup_readiness(
        [_spec(ProbeCriticality.PROCESS_CRITICAL)],
        [_result(ProbeStatus.PASSED, expires_at=_NOW)],
        generated_at=_NOW,
    )

    assert report.decision is ReadinessDecision.BLOCKED
    assert report.stale_probe_ids == ("audit.probe",)


def test_all_process_critical_results_pass_is_ready() -> None:
    report = reduce_startup_readiness(
        [_spec(ProbeCriticality.PROCESS_CRITICAL)],
        [_result(ProbeStatus.PASSED)],
        generated_at=_NOW,
    )

    assert report.decision is ReadinessDecision.READY


def test_optional_failure_degrades_with_configured_fallback() -> None:
    spec = _spec(
        ProbeCriticality.OPTIONAL,
        capability="web-search",
        ceiling=AuthorityCeiling.DETERMINISTIC_FALLBACK,
    )
    result = _result(ProbeStatus.FAILED).model_copy(update={"probe_id": spec.probe_id})

    report = reduce_startup_readiness([spec], [result], generated_at=_NOW)

    assert report.decision is ReadinessDecision.DEGRADED
    assert report.authority_ceilings == {"web-search": AuthorityCeiling.DETERMINISTIC_FALLBACK}


def test_recovery_never_raises_deployment_ceiling() -> None:
    spec = _spec(
        ProbeCriticality.AUTHORITY_CRITICAL,
        ceiling=AuthorityCeiling.HUMAN_APPROVAL,
    )

    report = reduce_startup_readiness(
        [spec],
        [_result(ProbeStatus.PASSED)],
        generated_at=_NOW,
        deployment_ceilings={"audit": AuthorityCeiling.SHADOW},
    )

    assert report.decision is ReadinessDecision.READY
    assert report.authority_ceilings == {"audit": AuthorityCeiling.SHADOW}


def test_report_serialization_is_stable_and_sanitized() -> None:
    report = reduce_startup_readiness(
        [_spec(ProbeCriticality.PROCESS_CRITICAL)],
        [_result(ProbeStatus.FAILED)],
        generated_at=_NOW,
    )

    assert report.to_json() == report.to_json()
    assert "dependency_unavailable" in report.to_json()
    assert "endpoint" not in report.to_json()


def test_duplicate_or_unknown_results_are_rejected() -> None:
    spec = _spec(ProbeCriticality.PROCESS_CRITICAL)
    result = _result(ProbeStatus.PASSED)

    with pytest.raises(ValueError, match="unique"):
        reduce_startup_readiness([spec], [result, result], generated_at=_NOW)
    with pytest.raises(ValueError, match="not configured"):
        reduce_startup_readiness(
            [spec],
            [result.model_copy(update={"probe_id": "unknown.probe"})],
            generated_at=_NOW,
        )
