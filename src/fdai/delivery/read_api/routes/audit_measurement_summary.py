"""Audit-derived autonomy measurements with explicit unavailable values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any, TypeGuard

from fdai.delivery.read_api.read_model import AuditItem, AuditQueryFilters, ConsoleReadModel
from fdai.delivery.read_api.routes.measurement_summary import _vertical_of

_HUMAN_TOUCH = frozenset({"awaiting_approval", "escalated_hil", "hil", "hil.await", "hil_pending"})
_AUTONOMY_ACTORS = (
    "fdai.core.control_loop",
    "fdai.core.executor.direct_api",
    "fdai.core.executor.shadow",
    "fdai.core.executor.tool_call",
)
_EXECUTION_SUCCESS = frozenset({"already_applied", "dispatched"})
_EXECUTION_FAILURE = frozenset(
    {
        "abstained_blast_radius",
        "abstained_precondition",
        "failed",
        "rejected_idempotency_conflict",
        "rejected_invariant",
        "rejected_mode",
        "stopped",
    }
)
_VERTICAL_KEYS = ("resilience", "change_safety", "cost")


class AuditAutonomyMeasurementPanel:
    """Project only measurements present in the durable audit window."""

    def __init__(
        self,
        read_model: ConsoleReadModel,
        *,
        active_rule_count: int = 0,
        window_days: int = 30,
    ) -> None:
        self._read_model = read_model
        self._active_rule_count = active_rule_count
        self._window_days = window_days

    @property
    def path(self) -> str:
        return "/kpi/autonomy"

    @property
    def name(self) -> str:
        return "autonomy"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params
        event_page = await self._read_model.list_audit(
            limit=500,
            filters=AuditQueryFilters(
                actors=_AUTONOMY_ACTORS,
                window_days=self._window_days,
            ),
        )
        evidence_page = await self._read_model.list_audit(
            limit=500,
            filters=AuditQueryFilters(window_days=self._window_days),
        )
        return _audit_payload(
            tuple(event_page.items),
            window_days=self._window_days,
            active_rule_count=self._active_rule_count,
            supplemental_items=tuple(evidence_page.items),
        )


def _audit_payload(
    items: Sequence[AuditItem],
    *,
    window_days: int,
    active_rule_count: int,
    supplemental_items: Sequence[AuditItem] = (),
) -> Mapping[str, Any]:
    events = _event_evidence(items)
    evidence_items = _merge_items(items, supplemental_items)
    auto_count = sum(_is_auto_resolved(event_items) for event_items in events.values())
    human_count = sum(_human_touchpoint_count(event_items) for event_items in events.values())
    auto_rate = auto_count / len(events) if events else None
    touchpoints = human_count * 100.0 / len(events) if events else None

    verticals: dict[str, dict[str, float]] = {
        key: {"events": 0, "auto_resolved": 0, "open_risks": 0, "monthly_savings": 0.0}
        for key in _VERTICAL_KEYS
    }
    by_tier: dict[str, int] = {}
    for event_items in events.values():
        bucket = verticals[_event_vertical(event_items)]
        bucket["events"] += 1
        if _is_auto_resolved(event_items):
            bucket["auto_resolved"] += 1
        bucket["open_risks"] += _human_touchpoint_count(event_items)
        bucket["monthly_savings"] += _event_savings(event_items)
        tier = _event_tier(event_items)
        if tier is not None:
            by_tier[tier] = by_tier.get(tier, 0) + 1

    tier_total = sum(by_tier.values())
    tier_mix = {
        key: by_tier.get(key, 0) / tier_total if tier_total else 0.0 for key in ("t0", "t1", "t2")
    }
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
            "auto_resolution_rate": _metric(
                evidence_items, "auto_resolution_rate", "higher", auto_rate
            ),
            "human_touchpoints_per_100": _metric(
                evidence_items, "human_touchpoints_per_100", "lower", touchpoints
            ),
            "mttr_seconds": _metric(evidence_items, "mttr_seconds", "lower"),
            "change_lead_time_seconds": _metric(
                evidence_items, "change_lead_time_seconds", "lower"
            ),
            "cost_per_resolved_event_usd": _metric(
                evidence_items, "cost_per_resolved_event_usd", "lower"
            ),
        },
        "leading": {
            "mixed_model_disagreement_rate": _metric(
                evidence_items, "mixed_model_disagreement_rate", "lower"
            ),
            "verifier_failure_rate": _metric(evidence_items, "verifier_failure_rate", "lower"),
            "shadow_divergence_rate": _metric(evidence_items, "shadow_divergence_rate", "lower"),
        },
        "guards": _guards(evidence_items),
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


def _merge_items(*groups: Sequence[AuditItem]) -> tuple[AuditItem, ...]:
    by_sequence = {item.seq: item for group in groups for item in group}
    return tuple(by_sequence[seq] for seq in sorted(by_sequence, reverse=True))


def _event_evidence(items: Sequence[AuditItem]) -> dict[str, list[AuditItem]]:
    grouped: dict[str, list[AuditItem]] = {}
    for item in items:
        grouped.setdefault(item.event_id, []).append(item)
    return {
        event_id: event_items
        for event_id, event_items in grouped.items()
        if any(item.actor == "fdai.core.control_loop" for item in event_items)
    }


def _normalized_entry_value(item: AuditItem, key: str) -> str:
    return str(item.entry.get(key, "")).strip().lower()


def _has_human_touch(items: Sequence[AuditItem]) -> bool:
    return _human_touchpoint_count(items) > 0


def _human_touchpoint_count(items: Sequence[AuditItem]) -> int:
    touchpoint_ids: set[str] = set()
    for item in items:
        if not (
            _normalized_entry_value(item, "decision") == "hil"
            or _normalized_entry_value(item, "outcome") in _HUMAN_TOUCH
        ):
            continue
        identity = next(
            (
                str(value)
                for key in ("action_id", "approval_id", "idempotency_key")
                if (value := item.entry.get(key)) is not None and str(value).strip()
            ),
            "unidentified",
        )
        touchpoint_ids.add(identity)
    return len(touchpoint_ids)


def _is_auto_resolved(items: Sequence[AuditItem]) -> bool:
    if _has_human_touch(items):
        return False
    decisions = {_normalized_entry_value(item, "decision") for item in items}
    outcomes = {_normalized_entry_value(item, "outcome") for item in items}
    if decisions & {"deny", "denied"} or outcomes & _EXECUTION_FAILURE:
        return False
    return any(
        item.actor in {"fdai.core.executor.direct_api", "fdai.core.executor.tool_call"}
        and item.mode == "enforce"
        and _normalized_entry_value(item, "outcome") in _EXECUTION_SUCCESS
        and item.entry.get("rollback_succeeded") is not True
        for item in items
    )


def _event_tier(items: Sequence[AuditItem]) -> str | None:
    if any(item.action_kind == "control_loop.t2_evaluate" for item in items):
        return "t2"
    if any(item.action_kind == "control_loop.t1_evaluate" for item in items):
        return "t1"
    if any(
        item.action_kind in {"risk_gate.unified", "risk_gate.shadow_authority"}
        or _normalized_entry_value(item, "stage") == "t0_evaluate"
        for item in items
    ):
        return "t0"
    return None


def _event_vertical(items: Sequence[AuditItem]) -> str:
    for item in items:
        for key in ("vertical", "category", "action_type_id", "resource_type"):
            value = item.entry.get(key)
            if isinstance(value, str) and value.strip():
                vertical = _vertical_of(value)
                if vertical != "change_safety":
                    return vertical
    return "change_safety"


def _event_savings(items: Sequence[AuditItem]) -> float:
    by_action: dict[str, float] = {}
    for item in items:
        savings = item.entry.get("estimated_savings")
        if not _is_number(savings):
            continue
        action_id = item.entry.get("action_id")
        key = str(action_id) if action_id is not None else item.entry_hash
        by_action[key] = float(savings)
    return sum(by_action.values())


def _metric(
    items: Sequence[AuditItem],
    key: str,
    direction: str,
    derived_value: float | None = None,
) -> Mapping[str, Any]:
    measured = _values(items, key)
    baselines = _values(items, key, baseline=True)
    return {
        "value": fmean(measured) if measured else derived_value,
        "baseline": fmean(baselines) if baselines else None,
        "direction": direction,
    }


def _values(items: Sequence[AuditItem], key: str, *, baseline: bool = False) -> list[float]:
    values: list[float] = []
    for item in items:
        container = item.entry.get("baseline" if baseline else "measurement")
        raw = container.get(key) if isinstance(container, Mapping) else None
        if raw is None:
            raw = item.entry.get(f"baseline_{key}" if baseline else key)
        if _is_number(raw):
            values.append(float(raw))
    return values


def _guards(items: Sequence[AuditItem]) -> list[Mapping[str, Any]]:
    for item in items:
        raw = item.entry.get("guards")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            continue
        guards = [guard for guard in raw if _valid_guard(guard)]
        if guards:
            return [dict(guard) for guard in guards]
    return []


def _valid_guard(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("key"), str)
        and all(_is_number(value.get(key)) for key in ("value", "baseline", "threshold"))
        and isinstance(value.get("ok"), bool)
    )


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


__all__ = ["AuditAutonomyMeasurementPanel"]
