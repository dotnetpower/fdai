"""Pure payload aggregation for audit-derived autonomy measurements."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any

from fdai.delivery.operator_api.read_model import AuditItem
from fdai.delivery.operator_api.routes.audit_measurement_events import (
    VERTICAL_KEYS,
    event_evidence,
    event_outcome_state,
    event_savings,
    event_tier,
    event_vertical,
    human_touchpoint_count,
    is_number,
    latest_finalizations,
)


def audit_payload(
    items: Sequence[AuditItem],
    *,
    window_days: int,
    active_rule_count: int,
    supplemental_items: Sequence[AuditItem] = (),
) -> Mapping[str, Any]:
    events = event_evidence(items)
    evidence_items = merge_items(items, supplemental_items)
    finalizations = latest_finalizations(evidence_items)
    event_outcomes = {
        event_id: event_outcome_state(event_items, finalizations)
        for event_id, event_items in events.items()
    }
    auto_count = sum(state == "auto_resolved" for state in event_outcomes.values())
    finalized_count = sum(
        state in {"auto_resolved", "adverse"} for state in event_outcomes.values()
    )
    pending_count = sum(state == "pending" for state in event_outcomes.values())
    adverse_count = sum(state == "adverse" for state in event_outcomes.values())
    human_count = sum(human_touchpoint_count(event_items) for event_items in events.values())
    auto_rate = auto_count / len(events) if events else None
    touchpoints = human_count * 100.0 / len(events) if events else None

    verticals: dict[str, dict[str, float]] = {
        key: {"events": 0, "auto_resolved": 0, "open_risks": 0, "monthly_savings": 0.0}
        for key in VERTICAL_KEYS
    }
    by_tier: dict[str, int] = {}
    for event_id, event_items in events.items():
        bucket = verticals[event_vertical(event_items)]
        bucket["events"] += 1
        if event_outcomes[event_id] == "auto_resolved":
            bucket["auto_resolved"] += 1
        bucket["open_risks"] += human_touchpoint_count(event_items)
        bucket["monthly_savings"] += event_savings(event_items)
        tier = event_tier(event_items)
        if tier is not None:
            by_tier[tier] = by_tier.get(tier, 0) + 1

    tier_total = sum(by_tier.values())
    tier_mix = {
        key: by_tier.get(key, 0) / tier_total if tier_total else 0.0 for key in ("t0", "t1", "t2")
    }
    attributed_events = sum(
        int(bucket["events"]) for key, bucket in verticals.items() if key != "unattributed"
    )
    unattributed_events = int(verticals["unattributed"]["events"])
    attribution_total = attributed_events + unattributed_events
    return {
        "synthetic": False,
        "window_days": window_days,
        "sample_size": len(events),
        "confidence": None,
        "source": {
            "name": "postgres-audit",
            "kind": "audit",
            "as_of": items[0].recorded_at if items else None,
        },
        "rules": {
            "active": active_rule_count,
            "candidates_30d": sum(
                item.entry.get("kind") == "rule.candidate" for item in evidence_items
            ),
            "promoted_30d": sum(
                item.entry.get("kind") == "rule.promoted" for item in evidence_items
            ),
        },
        "success": {
            "auto_resolution_rate": derived_metric(
                evidence_items, "auto_resolution_rate", "higher", auto_rate
            ),
            "human_touchpoints_per_100": derived_metric(
                evidence_items, "human_touchpoints_per_100", "lower", touchpoints
            ),
            "mttr_seconds": metric(evidence_items, "mttr_seconds", "lower"),
            "change_lead_time_seconds": metric(evidence_items, "change_lead_time_seconds", "lower"),
            "cost_per_resolved_event_usd": metric(
                evidence_items, "cost_per_resolved_event_usd", "lower"
            ),
        },
        "leading": {
            "mixed_model_disagreement_rate": metric(
                evidence_items, "mixed_model_disagreement_rate", "lower"
            ),
            "verifier_failure_rate": metric(evidence_items, "verifier_failure_rate", "lower"),
            "shadow_divergence_rate": metric(evidence_items, "shadow_divergence_rate", "lower"),
        },
        "guards": guards(evidence_items),
        "finalization": {
            "finalized_events": finalized_count,
            "pending_events": pending_count,
            "adverse_events": adverse_count,
        },
        "attribution": {
            "attributed_events": attributed_events,
            "unattributed_events": unattributed_events,
            "coverage": (attributed_events / attribution_total if attribution_total else None),
        },
        "verticals": [
            {
                "key": key,
                "events": int(bucket["events"]),
                "auto_resolved": int(bucket["auto_resolved"]),
                "open_risks": int(bucket["open_risks"]),
                "monthly_savings": round(bucket["monthly_savings"], 2),
            }
            for key, bucket in verticals.items()
        ],
        "tier": {
            "mix": tier_mix,
            "bands": {"t0": [0.7, 0.8], "t1": [0.15, 0.2], "t2": [0.05, 0.1]},
        },
        "trend": {},
    }


def merge_items(*groups: Sequence[AuditItem]) -> tuple[AuditItem, ...]:
    by_sequence = {item.seq: item for group in groups for item in group}
    return tuple(by_sequence[seq] for seq in sorted(by_sequence, reverse=True))


def metric(
    items: Sequence[AuditItem],
    key: str,
    direction: str,
    derived_value: float | None = None,
) -> Mapping[str, Any]:
    measured = values(items, key)
    baselines = values(items, key, baseline=True)
    return {
        "value": fmean(measured) if measured else derived_value,
        "baseline": fmean(baselines) if baselines else None,
        "direction": direction,
    }


def derived_metric(
    items: Sequence[AuditItem],
    key: str,
    direction: str,
    derived_value: float | None,
) -> Mapping[str, Any]:
    baselines = values(items, key, baseline=True)
    return {
        "value": derived_value,
        "baseline": fmean(baselines) if baselines else None,
        "direction": direction,
    }


def values(items: Sequence[AuditItem], key: str, *, baseline: bool = False) -> list[float]:
    latest_by_event: dict[str, tuple[int, float]] = {}
    for item in items:
        container = item.entry.get("baseline" if baseline else "measurement")
        raw = container.get(key) if isinstance(container, Mapping) else None
        if raw is None:
            raw = item.entry.get(f"baseline_{key}" if baseline else key)
        if is_number(raw):
            observed = latest_by_event.get(item.event_id)
            if observed is None or item.seq > observed[0]:
                latest_by_event[item.event_id] = (item.seq, float(raw))
    return [value for _, value in latest_by_event.values()]


def guards(items: Sequence[AuditItem]) -> list[Mapping[str, Any]]:
    for item in items:
        raw = item.entry.get("guards")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            continue
        valid = [guard for guard in raw if valid_guard(guard)]
        if valid:
            return [dict(guard) for guard in valid]
    return []


def valid_guard(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("key"), str)
        and all(is_number(value.get(key)) for key in ("value", "baseline", "threshold"))
        and isinstance(value.get("ok"), bool)
    )


__all__ = ["audit_payload"]
