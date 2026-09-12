"""Aggregate validated measurement facts without deriving execution authority.

The input adapter owns wire validation and source authentication. This module
owns one cutoff-bound descriptive view, never baseline claim admission.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import mean


@dataclass(frozen=True, slots=True)
class ClassifiedEvent:
    """A normalized event's durable terminal classification, not an effect."""

    event_id: str
    identity: str
    tier: str | None
    decision: str
    mode: str
    occurred_at: datetime
    seq: int
    action_ids: tuple[str, ...] = ()
    synthetic: bool = False


@dataclass(frozen=True, slots=True)
class ActionObservation:
    """One independently observed action outcome or its later correction."""

    event_id: str
    action_id: str
    observation_id: str
    mode: str
    decision: str
    scorable: bool
    verified: bool
    rollback: bool
    observed_at: datetime | None
    seq: int


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """An already source-validated numeric observation in its canonical unit."""

    event_id: str
    metric_id: str
    value: float | None
    observed_at: datetime
    seq: int
    source_context: tuple[str, str, str, str] | None = None
    sample_identity: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True)
class HumanTouchpoint:
    """One uniquely identified action or approval requiring human input."""

    event_id: str
    identity: str


_METRIC_DIRECTIONS = {
    "auto_resolution_rate": "higher",
    "human_touchpoints_per_100": "lower",
    "mttr_seconds": "lower",
    "change_lead_time_seconds": "lower",
    "cost_per_resolved_event_usd": "lower",
}


def aggregate_dashboard(
    *,
    events: Sequence[ClassifiedEvent],
    outcomes: Sequence[ActionObservation],
    metrics: Sequence[MetricObservation],
    touchpoints: Sequence[HumanTouchpoint],
    window_start: datetime,
    window_end: datetime,
    human_source_complete: bool = True,
) -> dict[str, object]:
    """Reduce a complete validated source snapshot into the Console envelope.

    Corrections replace earlier observations before an invalidated value can
    contribute. Pending and neutral events remain in the event denominator.
    Timing measures retain their own sample sizes. Cost requires complete spend
    coverage of that event universe and at least one independently resolved event.
    """

    latest_events: dict[str, ClassifiedEvent] = {}
    for event in sorted(events, key=lambda item: item.seq):
        previous = latest_events.get(event.identity)
        if previous is not None and (
            previous.event_id != event.event_id
            or previous.occurred_at != event.occurred_at
            or previous.mode != event.mode
        ):
            raise ValueError("measurement event identity changed across records")
        latest_events[event.identity] = event
    cohort = {
        event.event_id: event
        for event in latest_events.values()
        if not event.synthetic and window_start <= event.occurred_at <= window_end
    }
    if len(cohort) != sum(
        not event.synthetic and window_start <= event.occurred_at <= window_end
        for event in latest_events.values()
    ):
        raise ValueError("measurement event id has conflicting idempotency identities")

    latest_outcomes: dict[str, ActionObservation] = {}
    for outcome in sorted(outcomes, key=lambda item: item.seq):
        prior = latest_outcomes.get(outcome.observation_id)
        if prior is not None and (
            prior.event_id != outcome.event_id or prior.action_id != outcome.action_id
        ):
            raise ValueError("outcome correction changed its event or action identity")
        latest_outcomes[outcome.observation_id] = outcome
    by_action: dict[str, list[ActionObservation]] = defaultdict(list)
    for outcome in latest_outcomes.values():
        if outcome.event_id in cohort:
            by_action[outcome.action_id].append(outcome)

    human: dict[str, set[str]] = defaultdict(set)
    for point in touchpoints:
        if point.event_id in cohort:
            human[point.event_id].add(point.identity)
    human_complete = human_source_complete and all(
        event.decision != "hil" or bool(human[event.event_id]) for event in cohort.values()
    )

    resolved: set[str] = set()
    adverse: set[str] = set()
    pending: set[str] = set()
    for event in cohort.values():
        observations = [
            outcome for action_id in event.action_ids for outcome in by_action.get(action_id, ())
        ]
        if any(outcome.event_id != event.event_id for outcome in observations):
            raise ValueError("action observation belongs to a different event")
        if event.decision in {"deny", "abstain"} or any(
            outcome.rollback or (outcome.scorable and not outcome.verified)
            for outcome in observations
        ):
            adverse.add(event.event_id)
        elif (
            event.mode == "enforce"
            and event.decision == "auto"
            and human_source_complete
            and event.action_ids
            and not human[event.event_id]
            and all(by_action.get(action_id) for action_id in event.action_ids)
            and all(
                outcome.mode == "enforce"
                and outcome.decision == "auto"
                and outcome.scorable
                and outcome.verified
                and not outcome.rollback
                and outcome.observed_at is not None
                and event.occurred_at <= outcome.observed_at <= window_end
                for outcome in observations
            )
        ):
            resolved.add(event.event_id)
        elif event.decision in {"auto", "hil"}:
            pending.add(event.event_id)

    latest_metrics: dict[tuple[str, object], MetricObservation] = {}
    for metric in sorted(metrics, key=lambda item: item.seq):
        latest_metrics[(metric.metric_id, metric.sample_identity or metric.event_id)] = metric
    measured: dict[str, dict[object, float]] = defaultdict(dict)
    contexts: dict[str, set[tuple[str, str, str, str] | None]] = defaultdict(set)
    incomplete: set[str] = set()
    for metric in latest_metrics.values():
        if window_start <= metric.observed_at <= window_end:
            contexts[metric.metric_id].add(metric.source_context)
            if metric.value is None:
                incomplete.add(metric.metric_id)
            else:
                measured[metric.metric_id][metric.sample_identity or metric.event_id] = metric.value
    mixed = {key for key, values in contexts.items() if len(values) > 1}
    for key in incomplete | mixed:
        measured[key] = {}

    total = len(cohort)
    costs = measured["attributed_cost_usd"]
    cost_complete = bool(cohort) and set(cohort).issubset(costs)
    cost_per_resolved = None
    if cost_complete and resolved:
        try:
            cost_per_resolved = math.fsum(costs[event_id] for event_id in cohort) / len(resolved)
        except OverflowError as exc:
            raise ValueError("attributable cost exceeds the finite reporting range") from exc
    metric_values: Mapping[str, float | None] = {
        "auto_resolution_rate": (
            len(resolved) / total if total and human_source_complete else None
        ),
        "human_touchpoints_per_100": (
            sum(len(points) for points in human.values()) / total * 100
            if total and human_complete
            else None
        ),
        "mttr_seconds": _mean(measured["mttr_seconds"]),
        "change_lead_time_seconds": _mean(measured["change_lead_time_seconds"]),
        "cost_per_resolved_event_usd": cost_per_resolved,
    }
    by_tier = Counter(event.tier for event in cohort.values() if event.tier is not None)
    finalized = len(resolved) + len(adverse)
    return {
        "synthetic": False,
        "window_days": max(1, round((window_end - window_start).total_seconds() / 86_400)),
        "sample_size": total,
        "confidence": None,
        "source": {
            "name": "postgresql:operational_measurements",
            "kind": "measurement",
            "as_of": window_end.isoformat(),
        },
        "rules": {"active": 0, "candidates_30d": 0, "promoted_30d": 0},
        "rules_evidence": "unavailable",
        "success": {
            key: {"value": value, "baseline": None, "direction": _METRIC_DIRECTIONS[key]}
            for key, value in metric_values.items()
        },
        "metric_samples": {
            "auto_resolution_rate": total,
            "human_touchpoints_per_100": total if human_complete else 0,
            "mttr_seconds": len(measured["mttr_seconds"]),
            "change_lead_time_seconds": len(measured["change_lead_time_seconds"]),
            "cost_per_resolved_event_usd": len(resolved) if cost_complete else 0,
        },
        "measurement_gaps": [
            *(f"incomplete:{key}" for key in sorted(incomplete)),
            *(f"mixed_context:{key}" for key in sorted(mixed)),
            *(["unattributed_human_input"] if not human_source_complete else []),
        ],
        "leading": {
            key: {"value": None, "baseline": None, "direction": "lower"}
            for key in (
                "mixed_model_disagreement_rate",
                "verifier_failure_rate",
                "shadow_divergence_rate",
            )
        },
        "guards": [],
        "finalization": {
            "finalized_events": finalized,
            "pending_events": len(pending),
            "adverse_events": len(adverse),
            "neutral_events": total - finalized - len(pending),
        },
        "attribution": {
            "attributed_events": 0,
            "unattributed_events": total,
            "coverage": 0.0 if total else None,
        },
        "verticals": [
            {
                "key": "unattributed",
                "events": total,
                "auto_resolved": len(resolved),
                "open_risks": len(pending) + len(adverse),
                "monthly_savings": 0.0,
            }
        ]
        if total
        else [],
        "tier": {
            "mix": {key: value / total for key, value in sorted(by_tier.items())} if total else {},
            "bands": {"t0": [0.70, 0.80], "t1": [0.15, 0.20], "t2": [0.05, 0.10]},
        },
        "trend": {},
    }


def _mean(values: Mapping[object, float]) -> float | None:
    return mean(values.values()) if values else None
