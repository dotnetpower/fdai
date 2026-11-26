"""Pure DORA deployment metrics over normalized deployment observations."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import median


@dataclass(frozen=True, slots=True)
class DeploymentObservation:
    """One deployment with authoritative commit, outcome, and recovery times."""

    deployment_id: str
    committed_at: datetime
    deployed_at: datetime
    failed: bool
    recovered_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.deployment_id.strip() or len(self.deployment_id) > 256:
            raise ValueError("deployment observation id MUST be non-empty and bounded")
        if self.committed_at.tzinfo is None or self.deployed_at.tzinfo is None:
            raise ValueError("deployment observation timestamps MUST include timezone")
        if self.recovered_at is not None and self.recovered_at.tzinfo is None:
            raise ValueError("deployment recovery timestamp MUST include timezone")
        if not self.failed and self.recovered_at is not None:
            raise ValueError("only failed deployments may carry recovered_at")


@dataclass(frozen=True, slots=True)
class DoraSummary:
    window_days: float
    deployment_count: int
    failed_count: int
    unrecovered_failure_count: int
    invalid_count: int
    deployment_frequency_per_day: float
    change_failure_rate: float | None
    lead_time_mean_seconds: float | None
    lead_time_median_seconds: float | None
    lead_time_p90_seconds: float | None
    failed_change_recovery_mean_seconds: float | None
    failed_change_recovery_median_seconds: float | None
    failed_change_recovery_p90_seconds: float | None


def compute_dora(
    deployments: Iterable[DeploymentObservation],
    *,
    window_start: datetime,
    window_end: datetime,
) -> DoraSummary:
    """Compute deployment frequency, lead time, failure rate, and recovery time."""

    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("DORA measurement window MUST include timezone")
    window_seconds = (window_end - window_start).total_seconds()
    if window_seconds <= 0:
        raise ValueError("DORA measurement window MUST be positive")

    included = 0
    failed = 0
    unrecovered = 0
    invalid = 0
    lead_times: list[float] = []
    recovery_times: list[float] = []
    seen: set[str] = set()

    for deployment in deployments:
        if deployment.deployment_id in seen:
            continue
        seen.add(deployment.deployment_id)
        if not window_start <= deployment.deployed_at <= window_end:
            continue
        lead = (deployment.deployed_at - deployment.committed_at).total_seconds()
        if lead < 0:
            invalid += 1
            continue
        if deployment.recovered_at is not None and deployment.recovered_at < deployment.deployed_at:
            invalid += 1
            continue
        included += 1
        lead_times.append(lead)
        if deployment.failed:
            failed += 1
            if deployment.recovered_at is None:
                unrecovered += 1
            else:
                recovery_times.append(
                    (deployment.recovered_at - deployment.deployed_at).total_seconds()
                )

    window_days = window_seconds / 86_400
    lead_stats = _distribution(lead_times)
    recovery_stats = _distribution(recovery_times)
    return DoraSummary(
        window_days=window_days,
        deployment_count=included,
        failed_count=failed,
        unrecovered_failure_count=unrecovered,
        invalid_count=invalid,
        deployment_frequency_per_day=included / window_days,
        change_failure_rate=(failed / included if included else None),
        lead_time_mean_seconds=lead_stats[0],
        lead_time_median_seconds=lead_stats[1],
        lead_time_p90_seconds=lead_stats[2],
        failed_change_recovery_mean_seconds=recovery_stats[0],
        failed_change_recovery_median_seconds=recovery_stats[1],
        failed_change_recovery_p90_seconds=recovery_stats[2],
    )


def _distribution(values: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    ordered = sorted(values)
    rank = min(max(math.ceil(0.9 * len(ordered)), 1), len(ordered))
    return sum(ordered) / len(ordered), float(median(ordered)), ordered[rank - 1]


__all__ = ["DeploymentObservation", "DoraSummary", "compute_dora"]
