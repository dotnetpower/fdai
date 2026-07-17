"""Pure row projections for the Postgres console read model."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.delivery.read_api.read_model import (
    KPI_AUDIT_SAMPLE_LIMIT,
    AuditItem,
    AuditSample,
    DashboardKpi,
    HilQueueItem,
)


def parse_cursor(cursor: str | None) -> int | None:
    """Decode an opaque audit cursor into a sequence cutoff."""
    if cursor is None or cursor == "":
        return None
    try:
        return int(cursor)
    except ValueError as exc:
        raise ValueError(f"invalid cursor: {cursor!r}") from exc


def row_to_audit_item(row: Mapping[str, Any]) -> AuditItem:
    """Map a raw ``audit_log`` row to an :class:`AuditItem`."""
    entry_raw = row["entry"]
    if isinstance(entry_raw, str):
        entry = json.loads(entry_raw)
    elif isinstance(entry_raw, Mapping):
        entry = dict(entry_raw)
    else:
        raise TypeError(f"audit_log.entry MUST be JSONB (dict|str); got {type(entry_raw).__name__}")
    correlation_id = row.get("correlation_id")
    return AuditItem(
        seq=int(row["seq"]),
        event_id=str(row["event_id"]),
        correlation_id=str(correlation_id) if correlation_id is not None else None,
        actor=str(row["actor"]),
        action_kind=str(row["action_kind"]),
        mode=str(row["mode"]),
        entry=entry,
        entry_hash=str(row["entry_hash"]),
        previous_hash=str(row["previous_hash"]),
        recorded_at=_isoformat(row["created_at"]),
    )


def row_to_hil_queue_item(row: Mapping[str, Any]) -> HilQueueItem | None:
    """Map one ``state_kv`` HIL park row to a queue item."""
    value_raw = row["value"]
    if isinstance(value_raw, str):
        try:
            parked = json.loads(value_raw)
        except (TypeError, ValueError):
            return None
    elif isinstance(value_raw, Mapping):
        parked = dict(value_raw)
    else:
        return None
    approval_id = parked.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        return None
    parked_at = parked.get("parked_at")
    if not isinstance(parked_at, str) or not parked_at:
        return None
    action_raw = parked.get("action")
    action: Mapping[str, Any] = action_raw if isinstance(action_raw, Mapping) else {}
    idempotency_key = parked.get("idempotency_key") or action.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        return None
    event_id = action.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        event_id = "00000000-0000-0000-0000-000000000000"
    action_type = parked.get("action_type") or action.get("action_type")
    rule_id = parked.get("rule_id")
    context_raw = parked.get("approval_context")
    context: Mapping[str, Any] = context_raw if isinstance(context_raw, Mapping) else {}
    reasons_raw = context.get("reasons")
    reasons = (
        tuple(value for value in reasons_raw if isinstance(value, str) and value)
        if isinstance(reasons_raw, list)
        else ()
    )
    reason = reasons[0] if reasons else "Approval required by the risk gate."
    correlation_id = parked.get("correlation_id")
    rollback_raw = action.get("rollback_ref")
    rollback: Mapping[str, Any] = rollback_raw if isinstance(rollback_raw, Mapping) else {}
    blast_radius_raw = action.get("blast_radius")
    blast_radius: Mapping[str, Any] = (
        blast_radius_raw if isinstance(blast_radius_raw, Mapping) else {}
    )
    citing_rules_raw = action.get("citing_rules")
    citing_rule_ids = (
        tuple(value for value in citing_rules_raw if isinstance(value, str) and value)
        if isinstance(citing_rules_raw, list)
        else ((rule_id,) if isinstance(rule_id, str) and rule_id else ())
    )
    return HilQueueItem(
        idempotency_key=idempotency_key,
        event_id=event_id,
        action_kind=str(action_type) if action_type else "unknown",
        reason=reason,
        requested_at=parked_at,
        correlation_id=(
            str(correlation_id) if isinstance(correlation_id, str) and correlation_id else None
        ),
        approval_id=approval_id,
        action_id=str(action.get("action_id") or ""),
        target_resource_ref=str(action.get("target_resource_ref") or ""),
        mode=str(action.get("mode") or ""),
        stop_condition=str(action.get("stop_condition") or ""),
        rollback_kind=str(rollback.get("kind") or ""),
        rollback_reference=(
            str(rollback["reference"]) if rollback.get("reference") is not None else None
        ),
        blast_radius_scope=str(blast_radius.get("scope") or ""),
        blast_radius_count=(
            int(blast_radius["count"]) if isinstance(blast_radius.get("count"), int) else None
        ),
        blast_radius_rate_per_minute=(
            int(blast_radius["rate_per_minute"])
            if isinstance(blast_radius.get("rate_per_minute"), int)
            else None
        ),
        blast_radius_summary=str(context.get("blast_radius_summary") or ""),
        reasons=reasons,
        citing_rule_ids=citing_rule_ids,
        ttl_expires_at=(
            str(context["expires_at"])
            if isinstance(context.get("expires_at"), str) and context.get("expires_at")
            else None
        ),
    )


def _isoformat(value: Any) -> str:
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def aggregate_kpi(
    rows: Sequence[Mapping[str, Any]],
    *,
    hil_pending: int,
) -> DashboardKpi:
    """Compute dashboard KPIs from a bounded audit sample."""
    total = len(rows)
    sequences = [
        seq
        for row in rows
        if isinstance((seq := row.get("seq")), int) and not isinstance(seq, bool)
    ]
    audit_sample = AuditSample(
        from_seq=min(sequences) if len(sequences) == total and sequences else None,
        through_seq=max(sequences) if len(sequences) == total and sequences else None,
        row_count=total,
        limit=KPI_AUDIT_SAMPLE_LIMIT,
    )
    if total == 0:
        return DashboardKpi(
            event_count=0,
            shadow_share=0.0,
            enforce_share=0.0,
            hil_pending=hil_pending,
            by_action_kind={},
            by_outcome={},
            by_tier={},
            last_recorded_at=None,
            audit_sample=audit_sample,
        )
    by_kind: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    shadow = 0
    enforce = 0
    latest_raw: Any = None
    latest_iso: str | None = None
    for row in rows:
        action_kind = str(row.get("action_kind", "unknown"))
        by_kind[action_kind] = by_kind.get(action_kind, 0) + 1
        entry_raw = row.get("entry", {})
        if isinstance(entry_raw, str):
            try:
                entry = json.loads(entry_raw)
            except (TypeError, ValueError):
                entry = {}
        elif isinstance(entry_raw, Mapping):
            entry = dict(entry_raw)
        else:
            entry = {}
        outcome = str(entry.get("outcome", "unknown"))
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        tier = entry.get("tier")
        if tier is not None:
            tier_key = str(tier).lower()
            by_tier[tier_key] = by_tier.get(tier_key, 0) + 1
        mode = str(row.get("mode", ""))
        if mode == "shadow":
            shadow += 1
        elif mode == "enforce":
            enforce += 1
        raw_at = row.get("created_at")
        if raw_at is None:
            continue
        try:
            if latest_raw is None or raw_at > latest_raw:
                latest_raw = raw_at
                latest_iso = _isoformat(raw_at)
        except TypeError:
            iso = _isoformat(raw_at)
            if iso and (latest_iso is None or iso > latest_iso):
                latest_raw = raw_at
                latest_iso = iso
    return DashboardKpi(
        event_count=total,
        shadow_share=shadow / total,
        enforce_share=enforce / total,
        hil_pending=hil_pending,
        by_action_kind=by_kind,
        by_outcome=by_outcome,
        by_tier=by_tier,
        last_recorded_at=latest_iso,
        audit_sample=audit_sample,
    )


__all__ = ["aggregate_kpi", "parse_cursor", "row_to_audit_item", "row_to_hil_queue_item"]
