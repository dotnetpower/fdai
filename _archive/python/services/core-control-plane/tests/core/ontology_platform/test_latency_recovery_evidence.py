"""Latency recovery reducer and FunctionType safety checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.latency_recovery_evidence import (
    LATENCY_RECOVERY_FUNCTION_NAME,
    LatencyRecoveryStatus,
    assess_latency_recovery,
    latency_recovery_function_type,
)
from fdai.core.ontology_platform.metric_semantics import MetricWindowComparison

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _comparison(
    concept_id: str,
    *,
    baseline: float | None = 100.0,
    current: float | None = 90.0,
    complete: bool = True,
    reason: str | None = None,
    current_end: datetime = NOW,
) -> MetricWindowComparison:
    return MetricWindowComparison(
        concept_id=concept_id,
        resource_id="service-example-api",
        unit="ms",
        baseline_start=NOW - timedelta(minutes=30),
        baseline_end=NOW - timedelta(minutes=20),
        current_start=current_end - timedelta(minutes=10),
        current_end=current_end,
        baseline_value=baseline if complete else None,
        current_value=current if complete else None,
        absolute_change=(current - baseline)
        if complete and current is not None and baseline is not None
        else None,
        relative_change=None,
        complete=complete,
        reason=reason,
        evidence_refs=(f"metric:{concept_id}",),
    )


def test_latency_recovery_requires_both_measures_at_or_below_baseline() -> None:
    recovered = assess_latency_recovery(
        service_latency=_comparison("service.latency"),
        dependency_latency=_comparison("dependency.latency", baseline=50.0, current=50.0),
    )
    not_recovered = assess_latency_recovery(
        service_latency=_comparison("service.latency", current=101.0),
        dependency_latency=_comparison("dependency.latency"),
    )

    assert recovered.status is LatencyRecoveryStatus.RECOVERED
    assert recovered.recovery_verified is True
    assert recovered.cause_claim_supported is False
    assert recovered.execution_authority is False
    assert not_recovered.status is LatencyRecoveryStatus.NOT_RECOVERED
    assert not_recovered.recovery_verified is False


def test_latency_recovery_keeps_incomplete_evidence_unverified() -> None:
    result = assess_latency_recovery(
        service_latency=_comparison(
            "service.latency",
            complete=False,
            reason="provider_unavailable",
        ),
        dependency_latency=_comparison("dependency.latency"),
    )

    assert result.status is LatencyRecoveryStatus.INSUFFICIENT_EVIDENCE
    assert result.complete is False
    assert result.recovery_verified is False
    assert result.limitations == ("service.latency:provider_unavailable",)


def test_latency_recovery_rejects_misaligned_current_cutoffs() -> None:
    with pytest.raises(ValueError, match="cutoffs MUST align"):
        assess_latency_recovery(
            service_latency=_comparison("service.latency"),
            dependency_latency=_comparison(
                "dependency.latency",
                current_end=NOW + timedelta(minutes=1),
            ),
        )


def test_latency_recovery_function_is_dependency_only_and_read_only() -> None:
    declaration = latency_recovery_function_type()

    assert declaration.name == LATENCY_RECOVERY_FUNCTION_NAME
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False
    assert declaration.input_schema["required"] == [
        "service_latency",
        "dependency_latency",
    ]
    properties = declaration.input_schema["properties"]
    assert properties["service_latency"]["x-fdai-dependency-only"] is True
    assert properties["dependency_latency"]["x-fdai-dependency-only"] is True
