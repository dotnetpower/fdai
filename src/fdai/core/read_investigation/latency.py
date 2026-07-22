"""Pure durable-latency profile aggregation and plan estimation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai.core.read_investigation.catalog import LatencyClass, read_tool_spec
from fdai.core.read_investigation.models import ReadInvestigationPlan
from fdai.shared.providers.read_investigation import ReadLatencySample, ReadToolId


@dataclass(frozen=True, slots=True)
class ReadLatencyProfile:
    sample_count: int
    failure_rate: float
    p50_ms: int | None
    p95_ms: int | None

    def __post_init__(self) -> None:
        if self.sample_count < 0 or not 0.0 <= self.failure_rate <= 1.0:
            raise ValueError("latency profile counts and rates MUST be valid")
        if self.sample_count == 0 and self.failure_rate != 0.0:
            raise ValueError("empty latency profile failure_rate MUST be zero")
        if self.p50_ms is not None and self.p50_ms < 0:
            raise ValueError("p50_ms MUST be non-negative")
        if self.p95_ms is not None and self.p95_ms < 0:
            raise ValueError("p95_ms MUST be non-negative")
        if self.p50_ms is not None and self.p95_ms is not None and self.p50_ms > self.p95_ms:
            raise ValueError("p50_ms MUST NOT exceed p95_ms")


@dataclass(frozen=True, slots=True)
class PlanLatencyEstimate:
    lower_ms: int
    upper_ms: int
    measured: bool
    sample_count: int
    multi_source: bool

    def __post_init__(self) -> None:
        if min(self.lower_ms, self.upper_ms, self.sample_count) < 0:
            raise ValueError("latency estimate values MUST be non-negative")
        if self.lower_ms > self.upper_ms:
            raise ValueError("latency estimate lower_ms MUST NOT exceed upper_ms")


_COLD_RANGES: Mapping[LatencyClass, tuple[int, int]] = {
    LatencyClass.FAST: (500, 4_000),
    LatencyClass.STANDARD: (2_000, 15_000),
    LatencyClass.SLOW: (5_000, 30_000),
}


def latency_profile(samples: Sequence[ReadLatencySample]) -> ReadLatencyProfile:
    count = len(samples)
    if count == 0:
        return ReadLatencyProfile(sample_count=0, failure_rate=0.0, p50_ms=None, p95_ms=None)
    successful = sorted(sample.total_duration_ms for sample in samples if sample.succeeded)
    failures = count - len(successful)
    return ReadLatencyProfile(
        sample_count=count,
        failure_rate=failures / count,
        p50_ms=_percentile(successful, 0.50),
        p95_ms=_percentile(successful, 0.95),
    )


def estimate_plan_latency(
    plan: ReadInvestigationPlan,
    profiles: Mapping[ReadToolId, ReadLatencyProfile],
    *,
    minimum_samples: int,
) -> PlanLatencyEstimate:
    if minimum_samples < 1:
        raise ValueError("minimum_samples MUST be positive")
    estimates = [
        _tool_estimate(step.tool_id, profiles.get(step.tool_id), minimum_samples)
        for step in plan.steps
    ]
    resolve_lower, resolve_upper, resolve_measured, resolve_samples = estimates[0]
    evidence = estimates[1:]
    if evidence:
        evidence_lower = max(value[0] for value in evidence)
        evidence_upper = max(value[1] for value in evidence)
    else:
        evidence_lower = evidence_upper = 0
    return PlanLatencyEstimate(
        lower_ms=resolve_lower + evidence_lower,
        upper_ms=resolve_upper + evidence_upper,
        measured=resolve_measured and all(value[2] for value in evidence),
        sample_count=resolve_samples + sum(value[3] for value in evidence),
        multi_source=len(evidence) > 1,
    )


def estimate_sequential_p95(profiles: Sequence[ReadLatencyProfile]) -> int | None:
    if any(profile.p95_ms is None for profile in profiles):
        return None
    return sum(profile.p95_ms or 0 for profile in profiles)


def estimate_parallel_p95(profiles: Sequence[ReadLatencyProfile]) -> int | None:
    if any(profile.p95_ms is None for profile in profiles):
        return None
    return max((profile.p95_ms or 0 for profile in profiles), default=0)


def _tool_estimate(
    tool_id: ReadToolId,
    profile: ReadLatencyProfile | None,
    minimum_samples: int,
) -> tuple[int, int, bool, int]:
    if (
        profile is not None
        and profile.sample_count >= minimum_samples
        and profile.p50_ms is not None
        and profile.p95_ms is not None
    ):
        return profile.p50_ms, profile.p95_ms, True, profile.sample_count
    lower, upper = _COLD_RANGES[read_tool_spec(tool_id).latency_class]
    return lower, upper, False, 0 if profile is None else profile.sample_count


def _percentile(values: Sequence[int], quantile: float) -> int | None:
    if not values:
        return None
    index = max(0, math.ceil(quantile * len(values)) - 1)
    return values[index]


__all__ = [
    "PlanLatencyEstimate",
    "ReadLatencyProfile",
    "estimate_parallel_p95",
    "estimate_plan_latency",
    "estimate_sequential_p95",
    "latency_profile",
]
