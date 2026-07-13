"""MTTR (mean time to resolution) aggregation over resolved incidents.

Realizes KPI 3a from
``docs/roadmap/architecture/goals-and-metrics.md``:
``MTTR = mean(resolve_time - detect_time)`` over resolved incidents,
reported as **mean, median, and p90** because the latency distribution is
skewed and a mean alone hides tail regressions.

This module is a **pure, deterministic aggregator** in the spirit of
:mod:`fdai.core.measurement.regression`: it folds a sequence of
:class:`~fdai.shared.contracts.models.incident.Incident` records into a
frozen :class:`MttrSummary`. It performs no I/O, imports no cloud SDK, and
holds no clock - the caller supplies the incidents (a delivery-layer
adapter drains them from the audit / incident store). That keeps the
``core/`` import boundary intact and the aggregation unit-testable with
plain fixtures.

Definitions (fixed to match goals-and-metrics):

- **detect_time** is the incident ``opened_at`` - the moment the first
  correlated event entered the loop.
- **resolve_time** is the incident ``resolved_at`` - the terminal
  resolution timestamp.
- Only incidents with a ``resolved_at`` contribute to the metric
  ("over resolved incidents"). Unresolved incidents are counted
  separately so the caller can report coverage honestly.
- An incident whose ``resolved_at`` precedes its ``opened_at`` is a data
  integrity fault; it is excluded from the metric and counted as
  ``invalid`` rather than silently contributing a negative duration.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from statistics import median

from fdai.shared.contracts.models import Incident


@dataclass(frozen=True, slots=True)
class MttrSummary:
    """Frozen MTTR aggregation over a set of incidents.

    ``mean_seconds`` / ``median_seconds`` / ``p90_seconds`` are ``None``
    when no resolved incident contributed a valid duration - a metric is
    never reported as ``0.0`` when it is simply unmeasured.
    """

    resolved_count: int
    unresolved_count: int
    invalid_count: int
    mean_seconds: float | None = None
    median_seconds: float | None = None
    p90_seconds: float | None = None
    durations_seconds: tuple[float, ...] = field(default_factory=tuple)

    @property
    def measured(self) -> bool:
        """True iff at least one resolved incident produced a duration."""
        return self.resolved_count > 0


def _percentile_nearest_rank(sorted_values: Sequence[float], percentile: float) -> float:
    """Nearest-rank percentile of an already-sorted, non-empty sequence.

    Deterministic and dependency-free: rank = ceil(p/100 * n), clamped to
    ``[1, n]``, and the value at that 1-based rank is returned. For
    ``n == 1`` every percentile is the single value.
    """
    n = len(sorted_values)
    if n == 0:
        raise ValueError("percentile of an empty sequence is undefined")
    if not 0.0 < percentile <= 100.0:
        raise ValueError("percentile MUST be in (0, 100]")
    rank = math.ceil(percentile / 100.0 * n)
    rank = min(max(rank, 1), n)
    return sorted_values[rank - 1]


def compute_mttr(incidents: Iterable[Incident]) -> MttrSummary:
    """Fold ``incidents`` into an :class:`MttrSummary`.

    Resolved incidents with ``resolved_at >= opened_at`` contribute their
    ``(resolved_at - opened_at)`` duration in seconds. Unresolved and
    integrity-violating incidents are counted but excluded from the
    metric.
    """
    durations: list[float] = []
    unresolved = 0
    invalid = 0

    for incident in incidents:
        resolved_at = incident.resolved_at
        if resolved_at is None:
            unresolved += 1
            continue
        delta = (resolved_at - incident.opened_at).total_seconds()
        if delta < 0:
            invalid += 1
            continue
        durations.append(delta)

    if not durations:
        return MttrSummary(
            resolved_count=0,
            unresolved_count=unresolved,
            invalid_count=invalid,
        )

    ordered = sorted(durations)
    return MttrSummary(
        resolved_count=len(ordered),
        unresolved_count=unresolved,
        invalid_count=invalid,
        mean_seconds=sum(ordered) / len(ordered),
        median_seconds=float(median(ordered)),
        p90_seconds=_percentile_nearest_rank(ordered, 90.0),
        durations_seconds=tuple(ordered),
    )


__all__ = [
    "MttrSummary",
    "compute_mttr",
]
