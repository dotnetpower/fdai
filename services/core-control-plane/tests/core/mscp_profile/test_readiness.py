"""MSCP reviewed readiness aggregation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.mscp_profile.readiness import (
    MscpCandidateKey,
    MscpReadinessPolicy,
    ReviewedEffectOutcome,
    evaluate_mscp_candidate_groups,
    evaluate_mscp_readiness,
)

_START = datetime(2026, 8, 1, tzinfo=UTC)
_CANDIDATE = MscpCandidateKey(
    action_type="example.restart",
    effect_metric="availability",
    environment="non-production",
    observer_version="observer-v1",
)


def _outcome(index: int, **changes: object) -> ReviewedEffectOutcome:
    values: dict[str, object] = {
        "candidate": _CANDIDATE,
        "observed_at": _START + timedelta(days=index % 14, seconds=index),
        "reviewed": True,
        "prediction_accurate": True,
        "false_positive": False,
        "false_negative": False,
        "policy_escape": False,
        "correlation_error": False,
        "verified_then_rollback_or_incident": False,
        "observer_available": True,
        "stale": False,
        "provider_failed": False,
        "observation_latency_ms": 100,
        "rollback": False,
        "human_touchpoint": False,
    }
    values.update(changes)
    return ReviewedEffectOutcome(**values)  # type: ignore[arg-type]


def _cohort(size: int = 200) -> tuple[ReviewedEffectOutcome, ...]:
    return tuple(_outcome(index) for index in range(size))


def _policy(**changes: object) -> MscpReadinessPolicy:
    values: dict[str, object] = {
        "min_accuracy": 0.95,
        "demotion_drill_passed": True,
    }
    values.update(changes)
    return MscpReadinessPolicy(**values)  # type: ignore[arg-type]


def test_qualifying_candidate_reports_complete_reviewed_metrics() -> None:
    report = evaluate_mscp_readiness(_cohort(), policy=_policy())

    assert report.ready_for_review is True
    assert report.gaps == ()
    assert report.shadow_days == 14
    assert report.sample_count == report.reviewed_count == 200
    assert report.accuracy == 1.0
    assert report.accuracy_lower_95 >= 0.95
    assert report.false_positive_rate == 0.0
    assert report.false_negative_count == 0
    assert report.policy_escape_count == 0
    assert report.correlation_error_count == 0
    assert report.verified_then_rollback_or_incident_count == 0
    assert report.observer_coverage == 1.0
    assert report.p95_latency_ms == 100
    assert report.stale_rate == report.provider_failure_rate == 0.0
    assert report.rollback_rate == report.human_touchpoints_per_100 == 0.0
    assert report.promotion_authority is False


@pytest.mark.parametrize(
    ("changes", "policy_changes", "gap"),
    [
        ({}, {"min_samples": 201}, "sample_count"),
        ({"reviewed": False, "prediction_accurate": False}, {}, "reviewed_count"),
        ({"prediction_accurate": False}, {}, "accuracy"),
        ({"false_positive": True, "prediction_accurate": False}, {}, "false_positive_rate"),
        ({"false_negative": True, "prediction_accurate": False}, {}, "false_negative_count"),
        ({"policy_escape": True}, {}, "policy_escape_count"),
        ({"correlation_error": True}, {}, "correlation_error_count"),
        (
            {"verified_then_rollback_or_incident": True},
            {},
            "verified_then_rollback_or_incident_count",
        ),
        ({"observer_available": False}, {}, "observer_coverage"),
        ({"observation_latency_ms": 5_001}, {}, "p95_latency_ms"),
        ({"stale": True}, {}, "stale_rate"),
        ({"provider_failed": True}, {}, "provider_failure_rate"),
        (
            {"human_touchpoint": True},
            {"max_human_touchpoints_per_100": 1.0},
            "human_touchpoints_per_100",
        ),
    ],
)
def test_each_measured_guard_produces_a_gap(
    changes: dict[str, object],
    policy_changes: dict[str, object],
    gap: str,
) -> None:
    cohort = list(_cohort())
    count = (
        len(cohort)
        if gap in {"p95_latency_ms", "accuracy"}
        else 101
        if gap == "reviewed_count"
        else 3
    )
    for index in range(count):
        cohort[index] = replace(cohort[index], **changes)  # type: ignore[arg-type]

    report = evaluate_mscp_readiness(
        tuple(cohort),
        policy=_policy(**policy_changes),
    )

    assert report.ready_for_review is False
    assert gap in report.gaps


def test_accuracy_confidence_lower_bound_is_independently_enforced() -> None:
    report = evaluate_mscp_readiness(
        tuple(_outcome(index) for index in range(100)),
        policy=_policy(min_accuracy=0.98),
    )

    assert report.accuracy == 1.0
    assert report.accuracy_lower_95 < 0.98
    assert "accuracy_lower_95" in report.gaps


def test_candidate_dimensions_are_never_pooled() -> None:
    other = replace(_CANDIDATE, observer_version="observer-v2")
    mixed = (*_cohort(), replace(_outcome(0), candidate=other))

    with pytest.raises(ValueError, match="MUST NOT pool"):
        evaluate_mscp_readiness(mixed, policy=_policy())

    reports = evaluate_mscp_candidate_groups(mixed, policy=_policy())
    assert tuple(report.candidate.observer_version for report in reports) == (
        "observer-v1",
        "observer-v2",
    )
    assert reports[0].sample_count == 200
    assert reports[1].sample_count == 1


def test_policy_cannot_weaken_initial_shadow_floors() -> None:
    with pytest.raises(ValueError, match="cannot weaken"):
        MscpReadinessPolicy(min_shadow_days=13, min_samples=99)
