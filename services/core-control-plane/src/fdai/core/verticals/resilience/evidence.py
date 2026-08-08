"""RPO/RTO evidence contracts and cohort aggregation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Final


@dataclass(frozen=True, slots=True)
class DrRunReport:
    experiment_id: str
    completed_at: datetime
    rpo_seconds: float
    rto_seconds: float
    integrity_mismatches: int = 0
    smoke_pass: bool = True


_MEDIAN_SENTINEL: Final[float] = -1.0


@dataclass(frozen=True, slots=True)
class DrObjective:
    max_rpo_seconds: float
    max_rto_seconds: float


@dataclass(frozen=True, slots=True)
class DrObjectiveReport:
    objective: DrObjective
    run_count: int
    rpo_median_seconds: float
    rpo_p90_seconds: float
    rto_median_seconds: float
    rto_p90_seconds: float
    breach_count: int
    integrity_mismatches_total: int
    smoke_failures: int

    @property
    def rpo_objective_met(self) -> bool:
        if self.run_count == 0:
            return False
        return self.rpo_p90_seconds <= self.objective.max_rpo_seconds

    @property
    def rto_objective_met(self) -> bool:
        if self.run_count == 0:
            return False
        return self.rto_p90_seconds <= self.objective.max_rto_seconds


def summarize_runs(*, runs: Iterable[DrRunReport], objective: DrObjective) -> DrObjectiveReport:
    """Aggregate measured runs into median and nearest-rank p90 evidence."""
    runs_list = list(runs)
    if not runs_list:
        return DrObjectiveReport(
            objective=objective,
            run_count=0,
            rpo_median_seconds=_MEDIAN_SENTINEL,
            rpo_p90_seconds=_MEDIAN_SENTINEL,
            rto_median_seconds=_MEDIAN_SENTINEL,
            rto_p90_seconds=_MEDIAN_SENTINEL,
            breach_count=0,
            integrity_mismatches_total=0,
            smoke_failures=0,
        )

    rpos = sorted(run.rpo_seconds for run in runs_list)
    rtos = sorted(run.rto_seconds for run in runs_list)
    breaches = sum(
        1
        for run in runs_list
        if run.rpo_seconds > objective.max_rpo_seconds
        or run.rto_seconds > objective.max_rto_seconds
    )
    return DrObjectiveReport(
        objective=objective,
        run_count=len(runs_list),
        rpo_median_seconds=median(rpos),
        rpo_p90_seconds=percentile(rpos, 0.9),
        rto_median_seconds=median(rtos),
        rto_p90_seconds=percentile(rtos, 0.9),
        breach_count=breaches,
        integrity_mismatches_total=sum(run.integrity_mismatches for run in runs_list),
        smoke_failures=sum(1 for run in runs_list if not run.smoke_pass),
    )


def percentile(sorted_values: list[float], p: float) -> float:
    """Return the nearest-rank percentile for a sorted small sample."""
    if not sorted_values:
        return _MEDIAN_SENTINEL
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(1, int(round(p * len(sorted_values))))
    rank = min(rank, len(sorted_values))
    return sorted_values[rank - 1]
