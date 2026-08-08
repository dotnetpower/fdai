"""Pure PostgreSQL-row projections for the independent Operator Service."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final, cast

from fdai_service_contracts import JsonObject, JsonValue

from fdai_operator_service.redaction import redact_projection

KPI_SAMPLE_LIMIT: Final = 500


def audit_item(row: Mapping[str, Any]) -> JsonObject:
    """Map one audit row to the frozen HTTP item with sensitive values redacted."""
    entry = _mapping(row.get("entry"))
    correlation_id = row.get("correlation_id")
    return cast(
        JsonObject,
        {
            "seq": int(row["seq"]),
            "event_id": str(row["event_id"]),
            "correlation_id": str(correlation_id) if correlation_id is not None else None,
            "actor": str(row["actor"]),
            "action_kind": str(row["action_kind"]),
            "mode": str(row["mode"]),
            "entry": redact(entry),
            "entry_hash": str(row["entry_hash"]),
            "previous_hash": str(row["previous_hash"]),
            "recorded_at": _isoformat(row.get("created_at")),
        },
    )


def redact(value: object) -> JsonValue:
    """Apply the shared bounded Operator projection redaction contract."""
    return redact_projection(value)


def hil_item(row: Mapping[str, Any]) -> JsonObject | None:
    """Project a validated pending HIL park record without exposing credentials."""
    parked = _mapping(row.get("value"))
    approval_id = _nonempty(parked.get("approval_id"))
    parked_at = _nonempty(parked.get("parked_at"))
    action = _mapping(parked.get("action"))
    idempotency_key = _nonempty(parked.get("idempotency_key")) or _nonempty(
        action.get("idempotency_key")
    )
    event_id = _nonempty(action.get("event_id"))
    if not approval_id or not parked_at or not idempotency_key or not event_id:
        return None
    context = _mapping(parked.get("approval_context"))
    rollback = _mapping(action.get("rollback_ref"))
    blast_radius = _mapping(action.get("blast_radius"))
    reasons = _strings(context.get("reasons"))
    citing_rules = _strings(action.get("citing_rules"))
    rule_id = _nonempty(parked.get("rule_id"))
    if not citing_rules and rule_id:
        citing_rules = [rule_id]
    correlation_id = _nonempty(parked.get("correlation_id"))
    return cast(
        JsonObject,
        {
            "idempotency_key": idempotency_key,
            "event_id": event_id,
            "action_kind": _nonempty(parked.get("action_type"))
            or _nonempty(action.get("action_type"))
            or "unknown",
            "reason": reasons[0] if reasons else "Approval required by the risk gate.",
            "requested_at": parked_at,
            "correlation_id": correlation_id,
            "approval_id": approval_id,
            "action_id": _nonempty(action.get("action_id")) or "",
            "target_resource_ref": _nonempty(action.get("target_resource_ref")) or "",
            "mode": _nonempty(action.get("mode")) or "",
            "stop_condition": _nonempty(action.get("stop_condition")) or "",
            "rollback_kind": _nonempty(rollback.get("kind")) or "",
            "rollback_reference": _nonempty(rollback.get("reference")),
            "blast_radius_scope": _nonempty(blast_radius.get("scope")) or "",
            "blast_radius_count": _integer(blast_radius.get("count")),
            "blast_radius_rate_per_minute": _integer(blast_radius.get("rate_per_minute")),
            "blast_radius_summary": _nonempty(context.get("blast_radius_summary")) or "",
            "reasons": reasons,
            "citing_rule_ids": citing_rules,
            "ttl_expires_at": _nonempty(context.get("expires_at")),
        },
    )


def dashboard_kpi(rows: Sequence[Mapping[str, Any]], *, hil_pending: int) -> JsonObject:
    """Aggregate the bounded newest audit sample into the frozen KPI envelope."""
    by_action_kind: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    shadow = 0
    enforce = 0
    sequences: list[int] = []
    recorded_at: list[str] = []
    for row in rows:
        action_kind = str(row.get("action_kind") or "unknown")
        by_action_kind[action_kind] = by_action_kind.get(action_kind, 0) + 1
        entry = _mapping(row.get("entry"))
        outcome = str(entry.get("outcome") or "unknown")
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        tier = _nonempty(entry.get("tier"))
        if tier:
            by_tier[tier.lower()] = by_tier.get(tier.lower(), 0) + 1
        mode = str(row.get("mode") or "")
        shadow += mode == "shadow"
        enforce += mode == "enforce"
        if isinstance(row.get("seq"), int):
            sequences.append(int(row["seq"]))
        timestamp = _isoformat(row.get("created_at"))
        if timestamp:
            recorded_at.append(timestamp)
    total = len(rows)
    return cast(
        JsonObject,
        {
            "event_count": total,
            "shadow_share": shadow / total if total else 0.0,
            "enforce_share": enforce / total if total else 0.0,
            "hil_pending": hil_pending,
            "by_action_kind": by_action_kind,
            "by_outcome": by_outcome,
            "by_tier": by_tier,
            "last_recorded_at": max(recorded_at) if recorded_at else None,
            "audit_sample": {
                "from_seq": min(sequences) if len(sequences) == total and sequences else None,
                "through_seq": max(sequences) if len(sequences) == total and sequences else None,
                "row_count": total,
                "limit": KPI_SAMPLE_LIMIT,
            },
        },
    )


def rule_fire_trace(correlation_id: str, items: Sequence[JsonObject]) -> JsonObject | None:
    """Reconstruct the frozen oldest-first rule-fire trace envelope."""
    if not items:
        return None
    ordered = sorted(items, key=lambda item: _as_int(item["seq"]))
    steps: list[JsonObject] = []
    terminal_stage: str | None = None
    for item in ordered:
        entry = _mapping(item.get("entry"))
        stage = _nonempty(entry.get("pipeline_stage")) or _nonempty(entry.get("stage"))
        if stage:
            terminal_stage = stage
        steps.append(
            {
                "seq": _as_int(item["seq"]),
                "recorded_at": str(item["recorded_at"]),
                "stage": stage,
                "decision": _nonempty(entry.get("decision")),
                "reason": _nonempty(entry.get("reason")) or _nonempty(entry.get("deny_reason")),
                "action_kind": str(item["action_kind"]),
                "mode": str(item["mode"]),
                "entry_hash": str(item["entry_hash"]),
            }
        )
    return cast(
        JsonObject,
        {
            "correlation_id": correlation_id,
            "step_count": len(steps),
            "steps": steps,
            "terminal_stage": terminal_stage,
        },
    )


def incident_summary(rows: Sequence[Mapping[str, Any]]) -> JsonObject:
    """Project one oldest-first correlated audit history into an incident summary."""
    items = [audit_item(row) for row in rows]
    newest = list(reversed(items))
    correlation_id = str(rows[-1]["normalized_correlation_id"])
    incident_id = _first_entry_string(newest, "incident_id")
    ticket_id = _first_entry_string(newest, "ticket_id")
    lifecycle = _incident_status(newest)
    vertical = _vertical(_first_entry_string(newest, "vertical", "category"))
    title = _first_entry_string(newest, "title", "summary") or _resource_title(items)
    return cast(
        JsonObject,
        {
            "correlation_id": correlation_id,
            "incident_id": incident_id,
            "ticket_id": ticket_id,
            "title": title or f"Incident {incident_id or correlation_id}",
            "severity": _first_entry_string(newest, "severity") or "unknown",
            "status": lifecycle[0],
            "status_source": lifecycle[1],
            "disposition": _first_entry_string(newest, "outcome") or "unknown",
            "verdict": _verdict(newest),
            "vertical": vertical,
            "opened_at": _first_entry_string(items, "opened_at") or str(items[0]["recorded_at"]),
            "last_updated_at": str(newest[0]["recorded_at"]),
            "latest_mode": str(newest[0]["mode"]),
            "history_count": int(rows[-1].get("group_history_count", len(rows))),
            "involved_agents": sorted({str(item["actor"]) for item in items}),
            "last_seq": int(rows[-1]["group_last_seq"]),
        },
    )


def _incident_status(items: Sequence[JsonObject]) -> tuple[str, str]:
    for item in items:
        entry = _mapping(item.get("entry"))
        kind = _nonempty(entry.get("kind"))
        state = (
            _nonempty(entry.get("to_state"))
            if kind == "incident.transition"
            else _nonempty(entry.get("state"))
            if kind == "incident.open"
            else None
        )
        if state:
            return ("resolved" if state in {"resolved", "closed"} else state, kind or "audit")
    if _first_entry_string(items, "outcome") in {
        "resolved",
        "remediated",
        "mitigated",
        "rollback_succeeded",
        "rollback_completed",
    }:
        return ("resolved", "audit_projection")
    if len(items) > 1 or _verdict(items) == "hil":
        return ("in_progress", "audit_projection")
    return ("open", "audit_projection")


def _verdict(items: Sequence[JsonObject]) -> str:
    for item in items:
        entry = _mapping(item.get("entry"))
        tokens = {
            str(item.get("action_kind") or "").lower(),
            str(entry.get("decision") or "").lower(),
            str(entry.get("gate_decision") or "").lower(),
            str(entry.get("outcome") or "").lower(),
            str(entry.get("status") or "").lower(),
        }
        for verdict in ("auto", "hil", "deny", "abstain"):
            if verdict in tokens or (verdict == "abstain" and "abstained" in tokens):
                return verdict
    return "unknown"


def _resource_title(items: Sequence[JsonObject]) -> str | None:
    for item in items:
        keys = _mapping(item.get("entry")).get("correlation_keys")
        for value in _strings(keys):
            if value.startswith("resource:") and value[9:]:
                return f"Resource {value[9:]}"
    return None


def _vertical(value: str | None) -> str:
    normalized = (value or "").lower().replace("-", "_")
    if normalized in {"resilience", "dr", "reliability", "chaos"}:
        return "resilience"
    if normalized in {"change", "change_safety", "config_drift", "security"}:
        return "change_safety"
    if normalized in {"cost", "cost_governance", "finops"}:
        return "cost_governance"
    return "unknown"


def _first_entry_string(items: Sequence[JsonObject], *keys: str) -> str | None:
    for item in items:
        entry = _mapping(item.get("entry"))
        for key in keys:
            if value := _nonempty(entry.get(key)):
                return value
    return None


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _nonempty(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _isoformat(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else ""


def _as_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("projection sequence MUST be an integer")
    return value


__all__ = [
    "KPI_SAMPLE_LIMIT",
    "audit_item",
    "dashboard_kpi",
    "hil_item",
    "incident_summary",
    "redact",
    "rule_fire_trace",
]
