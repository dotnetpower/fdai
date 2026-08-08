"""Dashboard metrics derived from audit-log entries.

Pure functions - no I/O, no async, no telemetry side effects. Consumers:

- The KPI dashboard (W1.9) renders these numbers.
- The reference-agent baseline runner (``tools/baseline_run.py``)
  computes a subset of them against a scenario replay.
- The golden-fixture regression test (``tests/telemetry/``) proves that
  a recorded trace reproduces every dashboard metric.

Every metric is grounded in a single audit-log column so a "why is this
number wrong" investigation is a `grep` away.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DashboardMetrics:
    """The KPI-dashboard's aggregated snapshot for a batch of audit entries.

    Every field maps to a documented metric in
    ``docs/roadmap/architecture/goals-and-metrics.md``. Ratios are in ``[0, 1]``; the
    ``per_100_events`` field is a scaled ratio.
    """

    event_count: int
    auto_resolution_rate: float
    hil_rate: float
    abstain_rate: float
    deny_rate: float
    human_touchpoints_per_100_events: float
    shadow_share: float
    enforce_share: float
    per_tier: Mapping[str, int]


_ALL_DECISIONS = ("auto", "hil", "abstain", "deny")
_ALL_MODES = ("shadow", "enforce")


def derive_dashboard_metrics(
    audit_entries: Sequence[Mapping[str, object]],
) -> DashboardMetrics:
    """Derive :class:`DashboardMetrics` from a batch of audit entries.

    ``audit_entries`` is expected to be the ``entry`` payload of each
    audit-log row - i.e. the JSON body committed by the executor when it
    finalized a decision. Missing required keys raise ``KeyError`` (the
    metric is undefined without them).
    """
    total = len(audit_entries)
    if total == 0:
        return DashboardMetrics(
            event_count=0,
            auto_resolution_rate=0.0,
            hil_rate=0.0,
            abstain_rate=0.0,
            deny_rate=0.0,
            human_touchpoints_per_100_events=0.0,
            shadow_share=0.0,
            enforce_share=0.0,
            per_tier={},
        )

    decisions: dict[str, int] = dict.fromkeys(_ALL_DECISIONS, 0)
    modes: dict[str, int] = dict.fromkeys(_ALL_MODES, 0)
    per_tier: dict[str, int] = {}
    human_touched = 0

    for entry in audit_entries:
        decision = str(entry["decision"])
        if decision not in decisions:
            raise ValueError(f"unknown decision {decision!r}; expected one of {_ALL_DECISIONS}")
        decisions[decision] += 1

        mode = str(entry["mode"])
        if mode not in modes:
            raise ValueError(f"unknown mode {mode!r}; expected one of {_ALL_MODES}")
        modes[mode] += 1

        tier = str(entry["tier"])
        per_tier[tier] = per_tier.get(tier, 0) + 1

        # Metric 4 - a human touchpoint is any HIL approval decision.
        # Reject / timeout counts as touched too (a human's absence is a decision).
        if decision == "hil" or bool(entry.get("human_touched")):
            human_touched += 1

    return DashboardMetrics(
        event_count=total,
        auto_resolution_rate=decisions["auto"] / total,
        hil_rate=decisions["hil"] / total,
        abstain_rate=decisions["abstain"] / total,
        deny_rate=decisions["deny"] / total,
        human_touchpoints_per_100_events=(human_touched / total) * 100,
        shadow_share=modes["shadow"] / total,
        enforce_share=modes["enforce"] / total,
        per_tier=dict(per_tier),
    )


__all__ = ["DashboardMetrics", "derive_dashboard_metrics"]
