"""Pure event-level classification for audit-derived autonomy measurements."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TypeGuard

from fdai.delivery.read_api.read_model import AuditItem
from fdai.delivery.read_api.routes.measurement_summary import _vertical_of

HUMAN_TOUCH = frozenset({"awaiting_approval", "escalated_hil", "hil", "hil.await", "hil_pending"})
EXECUTION_SUCCESS = frozenset({"already_applied", "dispatched"})
EXECUTION_FAILURE = frozenset(
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
VERIFIED_OUTCOME_KIND = "measurement.action_outcome.v1"
VERTICAL_KEYS = ("resilience", "change_safety", "cost", "unattributed")


def event_evidence(items: Sequence[AuditItem]) -> dict[str, list[AuditItem]]:
    grouped: dict[str, list[AuditItem]] = {}
    for item in items:
        grouped.setdefault(item.event_id, []).append(item)
    return {
        event_id: event_items
        for event_id, event_items in grouped.items()
        if any(item.actor == "fdai.core.control_loop" for item in event_items)
    }


def normalized_entry_value(item: AuditItem, key: str) -> str:
    return str(item.entry.get(key, "")).strip().lower()


def human_touchpoint_count(items: Sequence[AuditItem]) -> int:
    touchpoint_ids: set[str] = set()
    for item in items:
        if not (
            normalized_entry_value(item, "decision") == "hil"
            or normalized_entry_value(item, "outcome") in HUMAN_TOUCH
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


def latest_finalizations(items: Sequence[AuditItem]) -> dict[str, AuditItem]:
    by_action: dict[str, AuditItem] = {}
    for item in items:
        if item.action_kind != VERIFIED_OUTCOME_KIND:
            continue
        action_id = item.entry.get("action_id")
        action_type_id = item.entry.get("action_type_id")
        observed_at = item.entry.get("observed_at")
        if (
            not isinstance(action_id, str)
            or not action_id
            or not isinstance(action_type_id, str)
            or not action_type_id
            or not isinstance(observed_at, str)
            or not valid_timestamp(observed_at)
        ):
            continue
        observed = by_action.get(action_id)
        if observed is None or item.seq > observed.seq:
            by_action[action_id] = item
    return by_action


def event_outcome_state(
    items: Sequence[AuditItem],
    finalizations: Mapping[str, AuditItem],
) -> str:
    if human_touchpoint_count(items) > 0:
        return "not_eligible"
    decisions = {normalized_entry_value(item, "decision") for item in items}
    outcomes = {normalized_entry_value(item, "outcome") for item in items}
    if decisions & {"deny", "denied"} or outcomes & EXECUTION_FAILURE:
        return "adverse"
    successful_action_ids = {
        str(action_id)
        for item in items
        if item.actor in {"fdai.core.executor.direct_api", "fdai.core.executor.tool_call"}
        and item.mode == "enforce"
        and normalized_entry_value(item, "outcome") in EXECUTION_SUCCESS
        and item.entry.get("rollback_succeeded") is not True
        and (action_id := item.entry.get("action_id")) is not None
    }
    if not successful_action_ids:
        return "not_eligible"
    if not successful_action_ids.issubset(finalizations):
        return "pending"
    finalized = [finalizations[action_id] for action_id in successful_action_ids]
    if any(
        item.entry.get("execution_mode") != "enforce"
        or item.entry.get("verification_passed") is not True
        or item.entry.get("decision") != "auto"
        or item.entry.get("rollback_succeeded") is True
        for item in finalized
    ):
        return "adverse"
    return "auto_resolved"


def valid_timestamp(value: str) -> bool:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def event_tier(items: Sequence[AuditItem]) -> str | None:
    if any(item.action_kind == "control_loop.t2_evaluate" for item in items):
        return "t2"
    if any(item.action_kind == "control_loop.t1_evaluate" for item in items):
        return "t1"
    if any(
        item.action_kind in {"risk_gate.unified", "risk_gate.shadow_authority"}
        or normalized_entry_value(item, "stage") == "t0_evaluate"
        for item in items
    ):
        return "t0"
    return None


def event_vertical(items: Sequence[AuditItem]) -> str:
    for item in items:
        for key in ("vertical", "category"):
            value = item.entry.get(key)
            if isinstance(value, str) and value.strip():
                vertical = canonical_vertical(value)
                if vertical is not None:
                    return vertical
        for key in ("action_type_id", "resource_type"):
            value = item.entry.get(key)
            if isinstance(value, str) and value.strip():
                vertical = _vertical_of(value)
                if vertical in {"resilience", "cost"}:
                    return vertical
    return "unattributed"


def canonical_vertical(value: str) -> str | None:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "resilience":
        return "resilience"
    if normalized in {"change", "change_safety"}:
        return "change_safety"
    if normalized in {"cost", "cost_governance"}:
        return "cost"
    return None


def event_savings(items: Sequence[AuditItem]) -> float:
    by_action: dict[str, tuple[int, float]] = {}
    for item in items:
        savings = item.entry.get("estimated_savings")
        if not is_number(savings):
            continue
        action_id = item.entry.get("action_id")
        key = str(action_id) if action_id is not None else item.entry_hash
        observed = by_action.get(key)
        if observed is None or item.seq > observed[0]:
            by_action[key] = (item.seq, float(savings))
    return sum(value for _, value in by_action.values())


def is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


__all__ = [
    "VERTICAL_KEYS",
    "event_evidence",
    "event_outcome_state",
    "event_savings",
    "event_tier",
    "event_vertical",
    "human_touchpoint_count",
    "is_number",
    "latest_finalizations",
]
