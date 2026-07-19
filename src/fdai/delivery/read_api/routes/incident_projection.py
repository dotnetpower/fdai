"""Pure audit-to-incident read projection for the operator console."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from fdai.delivery.read_api.read_model import (
    AuditItem,
    IncidentStatus,
    IncidentStatusFilter,
    IncidentSummary,
)
from fdai.delivery.read_api.routes.provenance import is_dev_seed_fixture

_ACTIVE_STATUSES: frozenset[IncidentStatus] = frozenset({"open", "in_progress"})
_LIFECYCLE_STATES = frozenset({"open", "triaging", "mitigated", "resolved", "closed"})
_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
_INCIDENT_SEVERITIES = {
    "sev1": "critical",
    "sev2": "high",
    "sev3": "medium",
    "sev4": "low",
    "sev5": "info",
}
_VERTICALS = {
    "resilience": "resilience",
    "dr": "resilience",
    "reliability": "resilience",
    "chaos": "resilience",
    "change": "change_safety",
    "change_safety": "change_safety",
    "change-safety": "change_safety",
    "config_drift": "change_safety",
    "security": "change_safety",
    "cost": "cost_governance",
    "cost_governance": "cost_governance",
    "cost-governance": "cost_governance",
    "finops": "cost_governance",
}
_PANTHEON_AGENTS = frozenset(
    {
        "Odin",
        "Thor",
        "Forseti",
        "Huginn",
        "Heimdall",
        "Var",
        "Vidar",
        "Bragi",
        "Saga",
        "Mimir",
        "Norns",
        "Muninn",
        "Njord",
        "Freyr",
        "Loki",
    }
)


def correlate_audit_items(items: Iterable[AuditItem]) -> dict[str, tuple[AuditItem, ...]]:
    """Attach audit rows to an unambiguous correlation without inventing one."""
    ordered = sorted(items, key=lambda item: item.seq)
    event_correlations: dict[str, set[str]] = defaultdict(set)
    incident_candidates: dict[str, set[str]] = defaultdict(set)
    ambiguous_incidents: set[str] = set()
    for item in ordered:
        if item.correlation_id:
            event_correlations[item.event_id].add(item.correlation_id)
        incident_id = _string(item.entry, "incident_id")
        correlation_status, key_correlation = _correlation_key_state(item.entry)
        correlation = item.correlation_id or key_correlation
        if incident_id and item.correlation_id is None and correlation_status == "ambiguous":
            ambiguous_incidents.add(incident_id)
        if incident_id and correlation:
            incident_candidates[incident_id].add(correlation)
    incident_correlations = {
        incident_id: next(iter(candidates))
        for incident_id, candidates in incident_candidates.items()
        if len(candidates) == 1 and incident_id not in ambiguous_incidents
    }
    grouped: dict[str, list[AuditItem]] = defaultdict(list)
    for item in ordered:
        correlation_status, key_correlation = _correlation_key_state(item.entry)
        correlation = item.correlation_id or key_correlation
        if correlation is None:
            incident_id = _string(item.entry, "incident_id")
            if incident_id:
                correlation = incident_correlations.get(incident_id)
                if (
                    correlation is None
                    and incident_id not in ambiguous_incidents
                    and not incident_candidates.get(incident_id)
                    and correlation_status == "absent"
                    and _is_incident_lifecycle(item.entry)
                ):
                    correlation = incident_id
        if correlation is None:
            candidates = event_correlations.get(item.event_id, set())
            if len(candidates) == 1:
                correlation = next(iter(candidates))
        if correlation:
            grouped[correlation].append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def project_incidents(
    items: Iterable[AuditItem], *, status: IncidentStatusFilter = "all"
) -> tuple[IncidentSummary, ...]:
    """Project audit rows into newest-first incident summaries."""
    if status not in {"active", "resolved", "all"}:
        raise ValueError(f"invalid incident status filter: {status!r}")
    operational_items = (item for item in items if not is_dev_seed_fixture(item.entry))
    summaries = tuple(
        _project_one(correlation_id, history)
        for correlation_id, history in correlate_audit_items(operational_items).items()
    )
    filtered = (
        item
        for item in summaries
        if status == "all"
        or (status == "active" and item.status in _ACTIVE_STATUSES)
        or (status == "resolved" and item.status == "resolved")
    )
    return tuple(sorted(filtered, key=lambda item: item.last_seq, reverse=True))


def _project_one(correlation_id: str, history: Sequence[AuditItem]) -> IncidentSummary:
    ordered = sorted(history, key=lambda item: item.seq)
    latest_first = tuple(reversed(ordered))
    lifecycle_state = _latest_lifecycle_state(latest_first)
    if lifecycle_state:
        status = _status_from_lifecycle(lifecycle_state)
        status_source = "incident_lifecycle"
    else:
        status = _status_from_audit(ordered)
        status_source = "audit_projection"
    earliest = ordered[0]
    latest = ordered[-1]
    return IncidentSummary(
        correlation_id=correlation_id,
        incident_id=_first_string(ordered, "incident_id"),
        ticket_id=_first_string(ordered, "ticket_id"),
        title=_title(ordered),
        severity=_metadata_value(latest_first, ("severity", "severity_hint"), _SEVERITIES),
        status=status,
        status_source=status_source,
        disposition=_disposition(latest_first, status),
        verdict=_verdict(latest_first),
        vertical=_vertical(latest_first),
        opened_at=_opened_at(ordered) or earliest.recorded_at,
        last_updated_at=latest.recorded_at,
        latest_mode=latest.mode,
        history_count=len(ordered),
        involved_agents=_involved_agents(ordered),
        last_seq=latest.seq,
    )


def _involved_agents(items: Sequence[AuditItem]) -> tuple[str, ...]:
    traversed_control_loop = any(
        item.action_kind.lower().startswith(("control_loop.", "risk_gate.", "hil."))
        for item in items
    )
    involved: list[str] = ["Huginn", "Heimdall"] if traversed_control_loop else []
    for item in items:
        agent = _audit_agent(item)
        if agent is not None and agent not in involved:
            involved.append(agent)
    if traversed_control_loop and "Saga" not in involved:
        involved.append("Saga")
    return tuple(involved)


def _audit_agent(item: AuditItem) -> str | None:
    principal = _string(item.entry, "producer_principal")
    if principal in _PANTHEON_AGENTS:
        return principal
    action_kind = item.action_kind.lower()
    stage = (_string(item.entry, "stage") or "").lower()
    if action_kind.startswith("hil.") or item.actor == "fdai.core.hil_resume":
        return "Var"
    if action_kind.startswith("risk_gate."):
        return "Forseti"
    if action_kind.startswith("rca.") or item.actor == "fdai.core.rca":
        return "Forseti"
    if action_kind.startswith("governance."):
        return "Mimir"
    if action_kind.startswith("measurement.pattern_growth"):
        return "Norns"
    if action_kind.startswith("control_loop."):
        return "Heimdall" if stage == "trust_router" else "Forseti"
    if item.actor in _PANTHEON_AGENTS:
        return item.actor
    return None


def _latest_lifecycle_state(items: Sequence[AuditItem]) -> str | None:
    for item in items:
        kind = _string(item.entry, "kind")
        candidate = _string(item.entry, "to_state") if kind == "incident.transition" else None
        if candidate is None and kind == "incident.open":
            candidate = _string(item.entry, "state")
        if candidate in _LIFECYCLE_STATES:
            return candidate
    return None


def _status_from_lifecycle(state: str) -> IncidentStatus:
    if state in {"resolved", "closed"}:
        return "resolved"
    if state in {"triaging", "mitigated"}:
        return "in_progress"
    return "open"


def _status_from_audit(items: Sequence[AuditItem]) -> IncidentStatus:
    if any(_has_resolution_evidence(item) for item in items):
        return "resolved"
    if len(items) > 1 or any(_is_in_progress(item) for item in items):
        return "in_progress"
    return "open"


def _has_resolution_evidence(item: AuditItem) -> bool:
    outcome = (_string(item.entry, "outcome") or "").lower()
    return outcome in {
        "resolved",
        "remediated",
        "mitigated",
        "rollback_succeeded",
        "rollback_completed",
    }


def _is_in_progress(item: AuditItem) -> bool:
    entry = item.entry
    stage = (_string(entry, "pipeline_stage") or _string(entry, "stage") or "").lower()
    decision = (_string(entry, "decision") or _string(entry, "gate_decision") or "").lower()
    return stage in {"verify", "gate", "execute", "escalate", "hil"} or decision == "hil"


def _disposition(items: Sequence[AuditItem], status: IncidentStatus) -> str:
    for item in items:
        values = _tokens(item)
        if values & {"rolled_back", "rollback_completed", "rollback_succeeded"}:
            return "rolled_back"
        if values & {"hil", "awaiting_hil", "hil_pending", "escalated"}:
            return "awaiting_hil"
        if values & {"published", "dispatched", "already_existed", "already_applied", "pr_opened"}:
            return "action_delivered"
        if any(token.endswith("_pr_opened") for token in values):
            return "action_delivered"
        if values & {"deny", "denied", "reject", "rejected", "timeout", "abstain", "abstained"}:
            return "no_action"
        if values & {"failed", "error", "stopped", "rejected_mode"}:
            return "failed"
    if status == "resolved" and _latest_lifecycle_state(items) in {"resolved", "closed"}:
        return "resolved"
    return "resolved" if status == "resolved" else "pending"


def _verdict(items: Sequence[AuditItem]) -> str:
    for item in items:
        values = _tokens(item)
        for verdict in ("auto", "hil", "deny", "abstain"):
            if verdict in values or (verdict == "abstain" and "abstained" in values):
                return verdict
    return "unknown"


def _tokens(item: AuditItem) -> set[str]:
    entry = item.entry
    action_kind = item.action_kind.lower()
    values = {
        action_kind,
        *action_kind.replace(".", "_").split("_"),
        (_string(entry, "decision") or "").lower(),
        (_string(entry, "gate_decision") or "").lower(),
        (_string(entry, "outcome") or "").lower(),
        (_string(entry, "status") or "").lower(),
        (_string(entry, "phase") or "").lower(),
    }
    return {value for value in values if value}


def _title(items: Sequence[AuditItem]) -> str:
    for keys in (("title",), ("summary",), ("rule_id", "rule")):
        value = _first_string(items, *keys)
        if value:
            return value
    return items[0].event_id


def _opened_at(items: Sequence[AuditItem]) -> str | None:
    for item in items:
        if _string(item.entry, "kind") == "incident.open":
            opened_at = _string(item.entry, "opened_at")
            if opened_at:
                return opened_at
    return None


def _vertical(items: Sequence[AuditItem]) -> str:
    for item in items:
        for key in ("vertical", "category"):
            value = _nested_string(item.entry, key)
            if value and value.lower() in _VERTICALS:
                return _VERTICALS[value.lower()]
    return "unknown"


def _metadata_value(
    items: Sequence[AuditItem], keys: Sequence[str], allowed: frozenset[str]
) -> str:
    for item in items:
        for key in keys:
            value = _nested_string(item.entry, key)
            if value:
                normalized = _INCIDENT_SEVERITIES.get(value.lower(), value.lower())
                if normalized in allowed:
                    return normalized
    return "unknown"


def _first_string(items: Sequence[AuditItem], *keys: str) -> str | None:
    for item in items:
        for key in keys:
            value = _string(item.entry, key)
            if value:
                return value
    return None


def _nested_string(entry: Mapping[str, Any], key: str) -> str | None:
    value = _string(entry, key)
    if value:
        return value
    outputs = entry.get("outputs")
    return _string(outputs, key) if isinstance(outputs, Mapping) else None


def _correlation_key(entry: Mapping[str, Any]) -> str | None:
    return _correlation_key_state(entry)[1]


def _correlation_key_state(entry: Mapping[str, Any]) -> tuple[str, str | None]:
    values = entry.get("correlation_keys")
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        candidates = {
            value[5:]
            for value in values
            if isinstance(value, str) and value.startswith("corr:") and len(value) > 5
        }
        if len(candidates) == 1:
            return "unique", next(iter(candidates))
        if len(candidates) > 1:
            return "ambiguous", None
    return "absent", None


def _is_incident_lifecycle(entry: Mapping[str, Any]) -> bool:
    kind = _string(entry, "kind")
    return bool(kind and kind.startswith("incident."))


def _string(entry: Mapping[str, Any], key: str) -> str | None:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = ["correlate_audit_items", "project_incidents"]
