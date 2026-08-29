"""Reviewed statistical readiness for one MSCP gating candidate."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

_Z_95 = 1.959963984540054


@dataclass(frozen=True, order=True, slots=True)
class MscpCandidateKey:
    """Exact candidate dimensions that must never be pooled."""

    action_type: str
    effect_metric: str
    environment: str
    observer_version: str

    def __post_init__(self) -> None:
        for name, value in (
            ("action_type", self.action_type),
            ("effect_metric", self.effect_metric),
            ("environment", self.environment),
            ("observer_version", self.observer_version),
        ):
            if not value.strip() or len(value) > 256:
                raise ValueError(f"MscpCandidateKey.{name} MUST be bounded non-empty text")


@dataclass(frozen=True, slots=True)
class ReviewedEffectOutcome:
    """One sanitized shadow outcome with independent review labels."""

    candidate: MscpCandidateKey
    observed_at: datetime
    reviewed: bool
    prediction_accurate: bool
    false_positive: bool
    false_negative: bool
    policy_escape: bool
    correlation_error: bool
    verified_then_rollback_or_incident: bool
    observer_available: bool
    stale: bool
    provider_failed: bool
    observation_latency_ms: int
    rollback: bool
    human_touchpoint: bool

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("ReviewedEffectOutcome.observed_at MUST be timezone-aware")
        for name in (
            "reviewed",
            "prediction_accurate",
            "false_positive",
            "false_negative",
            "policy_escape",
            "correlation_error",
            "verified_then_rollback_or_incident",
            "observer_available",
            "stale",
            "provider_failed",
            "rollback",
            "human_touchpoint",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"ReviewedEffectOutcome.{name} MUST be a boolean")
        if isinstance(self.observation_latency_ms, bool) or not isinstance(
            self.observation_latency_ms, int
        ):
            raise ValueError("observation_latency_ms MUST be an integer")
        if self.observation_latency_ms < 0:
            raise ValueError("observation_latency_ms MUST be non-negative")
        review_labels = (
            self.prediction_accurate,
            self.false_positive,
            self.false_negative,
            self.policy_escape,
            self.correlation_error,
            self.verified_then_rollback_or_incident,
        )
        if not self.reviewed and any(review_labels):
            raise ValueError("unreviewed outcomes MUST NOT carry review labels")
        if self.prediction_accurate and (self.false_positive or self.false_negative):
            raise ValueError("accurate outcomes MUST NOT be false positives or false negatives")


@dataclass(frozen=True, slots=True)
class MscpReadinessPolicy:
    """Predeclared gate and SLO floor for one ActionType candidate."""

    min_shadow_days: int = 14
    min_samples: int = 100
    min_accuracy: float = 0.95
    max_false_positive_rate: float = 0.01
    min_observer_coverage: float = 0.99
    max_p95_latency_ms: int = 5_000
    max_stale_rate: float = 0.01
    max_provider_failure_rate: float = 0.01
    max_human_touchpoints_per_100: float = 10.0
    demotion_drill_passed: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.min_shadow_days, bool)
            or not isinstance(self.min_shadow_days, int)
            or isinstance(self.min_samples, bool)
            or not isinstance(self.min_samples, int)
            or self.min_shadow_days < 14
            or self.min_samples < 100
        ):
            raise ValueError("MSCP readiness cannot weaken the 14-day and 100-sample floors")
        for name, value in (
            ("min_accuracy", self.min_accuracy),
            ("max_false_positive_rate", self.max_false_positive_rate),
            ("min_observer_coverage", self.min_observer_coverage),
            ("max_stale_rate", self.max_stale_rate),
            ("max_provider_failure_rate", self.max_provider_failure_rate),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0.0 <= value <= 1.0
            ):
                raise ValueError(f"MscpReadinessPolicy.{name} MUST be a finite ratio")
        if (
            isinstance(self.max_p95_latency_ms, bool)
            or not isinstance(self.max_p95_latency_ms, int)
            or self.max_p95_latency_ms < 1
        ):
            raise ValueError("max_p95_latency_ms MUST be positive")
        if (
            isinstance(self.max_human_touchpoints_per_100, bool)
            or not isinstance(self.max_human_touchpoints_per_100, (int, float))
            or not math.isfinite(self.max_human_touchpoints_per_100)
            or self.max_human_touchpoints_per_100 < 0
        ):
            raise ValueError("max_human_touchpoints_per_100 MUST be finite and non-negative")
        if not isinstance(self.demotion_drill_passed, bool):
            raise ValueError("demotion_drill_passed MUST be a boolean")


@dataclass(frozen=True, slots=True)
class MscpReadinessReport:
    """Content-free candidate metrics and fail-closed readiness gaps."""

    candidate: MscpCandidateKey
    shadow_days: int
    sample_count: int
    reviewed_count: int
    accuracy: float
    accuracy_lower_95: float
    false_positive_rate: float
    false_negative_count: int
    policy_escape_count: int
    correlation_error_count: int
    verified_then_rollback_or_incident_count: int
    observer_coverage: float
    p95_latency_ms: int
    stale_rate: float
    provider_failure_rate: float
    rollback_rate: float
    human_touchpoints_per_100: float
    gaps: tuple[str, ...]
    ready_for_review: bool
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.promotion_authority:
            raise ValueError("MSCP readiness MUST NOT grant promotion authority")


def evaluate_mscp_readiness(
    outcomes: tuple[ReviewedEffectOutcome, ...],
    *,
    policy: MscpReadinessPolicy,
) -> MscpReadinessReport:
    """Evaluate one exact candidate tuple against the conservative floor."""

    if not outcomes:
        raise ValueError("MSCP readiness requires at least one outcome")
    candidates = {outcome.candidate for outcome in outcomes}
    if len(candidates) != 1:
        raise ValueError("MSCP readiness MUST NOT pool different candidate tuples")
    ordered = tuple(sorted(outcomes, key=lambda outcome: outcome.observed_at))
    sample_count = len(ordered)
    reviewed = tuple(outcome for outcome in ordered if outcome.reviewed)
    reviewed_count = len(reviewed)
    accurate_count = sum(outcome.prediction_accurate for outcome in reviewed)
    accuracy = _rate(accurate_count, reviewed_count)
    shadow_days = (ordered[-1].observed_at.date() - ordered[0].observed_at.date()).days + 1
    false_positive_rate = _rate(sum(outcome.false_positive for outcome in reviewed), reviewed_count)
    false_negative_count = sum(outcome.false_negative for outcome in reviewed)
    policy_escape_count = sum(outcome.policy_escape for outcome in reviewed)
    correlation_error_count = sum(outcome.correlation_error for outcome in reviewed)
    verified_then_count = sum(outcome.verified_then_rollback_or_incident for outcome in reviewed)
    observer_coverage = _rate(
        sum(outcome.observer_available for outcome in ordered),
        sample_count,
    )
    p95_latency_ms = _percentile_95(tuple(outcome.observation_latency_ms for outcome in ordered))
    stale_rate = _rate(sum(outcome.stale for outcome in ordered), sample_count)
    provider_failure_rate = _rate(
        sum(outcome.provider_failed for outcome in ordered),
        sample_count,
    )
    rollback_rate = _rate(sum(outcome.rollback for outcome in ordered), sample_count)
    human_touchpoints = 100.0 * _rate(
        sum(outcome.human_touchpoint for outcome in ordered),
        sample_count,
    )
    lower_bound = _wilson_lower(accurate_count, reviewed_count)
    gaps = _gaps(
        policy=policy,
        shadow_days=shadow_days,
        sample_count=sample_count,
        reviewed_count=reviewed_count,
        accuracy=accuracy,
        lower_bound=lower_bound,
        false_positive_rate=false_positive_rate,
        false_negative_count=false_negative_count,
        policy_escape_count=policy_escape_count,
        correlation_error_count=correlation_error_count,
        verified_then_count=verified_then_count,
        observer_coverage=observer_coverage,
        p95_latency_ms=p95_latency_ms,
        stale_rate=stale_rate,
        provider_failure_rate=provider_failure_rate,
        human_touchpoints=human_touchpoints,
    )
    return MscpReadinessReport(
        candidate=candidates.pop(),
        shadow_days=shadow_days,
        sample_count=sample_count,
        reviewed_count=reviewed_count,
        accuracy=accuracy,
        accuracy_lower_95=lower_bound,
        false_positive_rate=false_positive_rate,
        false_negative_count=false_negative_count,
        policy_escape_count=policy_escape_count,
        correlation_error_count=correlation_error_count,
        verified_then_rollback_or_incident_count=verified_then_count,
        observer_coverage=observer_coverage,
        p95_latency_ms=p95_latency_ms,
        stale_rate=stale_rate,
        provider_failure_rate=provider_failure_rate,
        rollback_rate=rollback_rate,
        human_touchpoints_per_100=human_touchpoints,
        gaps=gaps,
        ready_for_review=not gaps,
    )


def evaluate_mscp_candidate_groups(
    outcomes: tuple[ReviewedEffectOutcome, ...],
    *,
    policy: MscpReadinessPolicy,
) -> tuple[MscpReadinessReport, ...]:
    """Evaluate each candidate independently in stable key order."""

    grouped: dict[MscpCandidateKey, list[ReviewedEffectOutcome]] = {}
    for outcome in outcomes:
        grouped.setdefault(outcome.candidate, []).append(outcome)
    return tuple(
        evaluate_mscp_readiness(tuple(grouped[candidate]), policy=policy)
        for candidate in sorted(grouped)
    )


def _gaps(
    *,
    policy: MscpReadinessPolicy,
    shadow_days: int,
    sample_count: int,
    reviewed_count: int,
    accuracy: float,
    lower_bound: float,
    false_positive_rate: float,
    false_negative_count: int,
    policy_escape_count: int,
    correlation_error_count: int,
    verified_then_count: int,
    observer_coverage: float,
    p95_latency_ms: int,
    stale_rate: float,
    provider_failure_rate: float,
    human_touchpoints: float,
) -> tuple[str, ...]:
    gaps: list[str] = []
    checks = (
        (shadow_days < policy.min_shadow_days, "shadow_days"),
        (sample_count < policy.min_samples, "sample_count"),
        (reviewed_count < policy.min_samples, "reviewed_count"),
        (accuracy < policy.min_accuracy, "accuracy"),
        (lower_bound < policy.min_accuracy, "accuracy_lower_95"),
        (false_positive_rate > policy.max_false_positive_rate, "false_positive_rate"),
        (false_negative_count > 0, "false_negative_count"),
        (policy_escape_count > 0, "policy_escape_count"),
        (correlation_error_count > 0, "correlation_error_count"),
        (verified_then_count > 0, "verified_then_rollback_or_incident_count"),
        (observer_coverage < policy.min_observer_coverage, "observer_coverage"),
        (p95_latency_ms > policy.max_p95_latency_ms, "p95_latency_ms"),
        (stale_rate > policy.max_stale_rate, "stale_rate"),
        (provider_failure_rate > policy.max_provider_failure_rate, "provider_failure_rate"),
        (
            human_touchpoints > policy.max_human_touchpoints_per_100,
            "human_touchpoints_per_100",
        ),
        (not policy.demotion_drill_passed, "demotion_drill"),
    )
    gaps.extend(name for failed, name in checks if failed)
    return tuple(gaps)


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _wilson_lower(successes: int, total: int) -> float:
    if total == 0:
        return 0.0
    point = successes / total
    z_squared = _Z_95**2
    denominator = 1 + z_squared / total
    centre = point + z_squared / (2 * total)
    margin = _Z_95 * math.sqrt((point * (1 - point) + z_squared / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def _percentile_95(values: tuple[int, ...]) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


__all__ = [
    "MscpCandidateKey",
    "MscpReadinessPolicy",
    "MscpReadinessReport",
    "ReviewedEffectOutcome",
    "evaluate_mscp_candidate_groups",
    "evaluate_mscp_readiness",
]
