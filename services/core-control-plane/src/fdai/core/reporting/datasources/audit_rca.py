"""Correlation-scoped RCA dossier projections over audit rows.

These transforms only expose recorded facts. Optional analysis sections stay
empty until an audit producer records their bounded ``rca_*`` fields.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from fdai.core.reporting.models import DataSet


class RcaAuditRow(Protocol):
    seq: int
    event_id: str
    correlation_id: str | None
    actor: str
    action_kind: str
    mode: str
    recorded_at: str
    entry: Mapping[str, Any]


def project_rca_report(projection: str, rows: Sequence[RcaAuditRow]) -> DataSet | None:
    """Return one RCA dossier dataset, or ``None`` for a non-RCA projection."""
    handlers: dict[str, Callable[[Sequence[RcaAuditRow]], DataSet]] = {
        "rca_incident_profile": _incident_profile,
        "rca_impact": lambda items: _list_projection(
            items,
            "rca_impact",
            ("metric", "baseline", "observed", "threshold", "unit", "impact", "evidence_ref"),
        ),
        "rca_milestones": _milestones,
        "rca_hypotheses": _hypotheses,
        "rca_citations": _citations,
        "rca_causal_hops": _causal_hops,
        "rca_contributing_factors": lambda items: _list_projection(
            items,
            "rca_contributing_factors",
            ("category", "factor", "effect", "confidence", "evidence_ref"),
        ),
        "rca_alternative_hypotheses": lambda items: _list_projection(
            items,
            "rca_alternative_hypotheses",
            ("hypothesis", "status", "support", "contradiction", "reason", "evidence_refs"),
        ),
        "rca_response_plan": _response_plan,
        "rca_recovery_validation": lambda items: _list_projection(
            items,
            "rca_recovery_validation",
            ("metric", "before", "after", "target", "status", "evidence_ref"),
        ),
        "rca_control_gaps": lambda items: _list_projection(
            items,
            "rca_control_gaps",
            ("control", "expected", "observed", "gap", "evidence_ref"),
        ),
        "rca_recommendations": lambda items: _list_projection(
            items,
            "rca_recommendations",
            ("priority", "action", "owner_role", "due", "verification", "status", "evidence_refs"),
        ),
        "rca_limitations": lambda items: _list_projection(
            items,
            "rca_limitations",
            ("limitation", "effect", "next_evidence", "status"),
        ),
    }
    handler = handlers.get(projection)
    return handler(rows) if handler else None


def _incident_profile(rows: Sequence[RcaAuditRow]) -> DataSet:
    if not rows:
        return DataSet(columns=_PROFILE_COLUMNS)
    ordered = sorted(rows, key=lambda row: row.recorded_at)
    first, last = ordered[0], ordered[-1]
    entries = [_entry(row) for row in ordered]
    opened_at = first.recorded_at
    updated_at = last.recorded_at
    return DataSet(
        columns=_PROFILE_COLUMNS,
        rows=(
            {
                "correlation_id": first.correlation_id,
                "incident_id": _first(entries, "incident_id"),
                "ticket_id": _first(entries, "ticket_id"),
                "title": _first(entries, "incident_title", "title"),
                "severity": _first(entries, "severity"),
                "status": _last(entries, "incident_status", "status"),
                "vertical": _first(entries, "vertical"),
                "opened_at": opened_at,
                "last_updated_at": updated_at,
                "duration_seconds": _duration_seconds(opened_at, updated_at),
                "audit_records": len(rows),
                "actors": sorted({row.actor for row in rows}),
                "modes": sorted({row.mode for row in rows}),
            },
        ),
    )


_PROFILE_COLUMNS = (
    "correlation_id",
    "incident_id",
    "ticket_id",
    "title",
    "severity",
    "status",
    "vertical",
    "opened_at",
    "last_updated_at",
    "duration_seconds",
    "audit_records",
    "actors",
    "modes",
)


def _milestones(rows: Sequence[RcaAuditRow]) -> DataSet:
    columns = (
        "recorded_at",
        "phase",
        "actor",
        "action_kind",
        "decision",
        "outcome",
        "mode",
        "summary",
        "rollback_reference",
    )
    return DataSet(
        columns=columns,
        rows=tuple(
            {
                "recorded_at": row.recorded_at,
                "phase": _phase(row.action_kind),
                "actor": row.actor,
                "action_kind": row.action_kind,
                "decision": _entry(row).get("decision") or _entry(row).get("gate_decision"),
                "outcome": _entry(row).get("outcome") or _entry(row).get("status"),
                "mode": row.mode,
                "summary": _first((_entry(row),), "summary", "detail", "reason"),
                "rollback_reference": _entry(row).get("rollback_reference")
                or _entry(row).get("rollback_ref"),
            }
            for row in sorted(rows, key=lambda item: item.recorded_at)
        ),
    )


def _hypotheses(rows: Sequence[RcaAuditRow]) -> DataSet:
    columns = (
        "tier",
        "outcome",
        "cause",
        "confidence",
        "reason",
        "remediation_ref",
        "mode",
        "recorded_at",
    )
    return DataSet(
        columns=columns,
        rows=tuple(
            {
                "tier": _entry(row).get("rca_tier"),
                "outcome": _entry(row).get("rca_outcome"),
                "cause": _entry(row).get("rca_cause"),
                "confidence": _entry(row).get("rca_confidence"),
                "reason": _entry(row).get("rca_reason"),
                "remediation_ref": _entry(row).get("rca_remediation_ref"),
                "mode": row.mode,
                "recorded_at": row.recorded_at,
            }
            for row in rows
            if row.action_kind == "rca.hypothesis"
        ),
    )


def _citations(rows: Sequence[RcaAuditRow]) -> DataSet:
    projected: list[Mapping[str, Any]] = []
    for row in rows:
        if row.action_kind != "rca.hypothesis":
            continue
        raw = _entry(row).get("rca_citations")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            continue
        for citation in raw:
            if isinstance(citation, Mapping) and citation.get("kind") and citation.get("ref"):
                projected.append(
                    {
                        "tier": _entry(row).get("rca_tier"),
                        "kind": citation["kind"],
                        "ref": citation["ref"],
                        "summary": citation.get("summary"),
                        "source_at": citation.get("source_at"),
                        "freshness": citation.get("freshness"),
                        "recorded_at": row.recorded_at,
                    }
                )
    columns = ("tier", "kind", "ref", "summary", "source_at", "freshness", "recorded_at")
    return DataSet(columns=columns, rows=tuple(projected))


def _causal_hops(rows: Sequence[RcaAuditRow]) -> DataSet:
    projected: list[Mapping[str, Any]] = []
    for row in rows:
        chain = _entry(row).get("rca_causal_chain")
        if not isinstance(chain, Mapping):
            continue
        raw_hops = chain.get("hops")
        if not isinstance(raw_hops, Sequence) or isinstance(raw_hops, (str, bytes)):
            continue
        for index, hop in enumerate(raw_hops, start=1):
            if not isinstance(hop, Mapping):
                continue
            projected.append(
                {
                    "hop": index,
                    "cause_event_id": hop.get("cause_event_id"),
                    "cause_resource_ref": hop.get("cause_resource_ref"),
                    "relationship": hop.get("relationship"),
                    "effect_event_id": hop.get("effect_event_id"),
                    "effect_resource_ref": hop.get("effect_resource_ref"),
                    "lead_seconds": hop.get("lead_seconds"),
                    "confidence": hop.get("confidence"),
                }
            )
    columns = (
        "hop",
        "cause_event_id",
        "cause_resource_ref",
        "relationship",
        "effect_event_id",
        "effect_resource_ref",
        "lead_seconds",
        "confidence",
    )
    return DataSet(columns=columns, rows=tuple(projected))


def _response_plan(rows: Sequence[RcaAuditRow]) -> DataSet:
    columns = (
        "action_kind",
        "decision",
        "outcome",
        "mode",
        "rollback_reference",
        "actor",
        "recorded_at",
    )
    return DataSet(
        columns=columns,
        rows=tuple(
            {
                "action_kind": row.action_kind,
                "decision": _entry(row).get("decision") or _entry(row).get("gate_decision"),
                "outcome": _entry(row).get("outcome") or _entry(row).get("status"),
                "mode": row.mode,
                "rollback_reference": _entry(row).get("rollback_reference")
                or _entry(row).get("rollback_ref"),
                "actor": row.actor,
                "recorded_at": row.recorded_at,
            }
            for row in reversed(rows)
            if row.action_kind != "rca.hypothesis"
        ),
    )


def _list_projection(
    rows: Sequence[RcaAuditRow],
    key: str,
    columns: tuple[str, ...],
) -> DataSet:
    projected: list[Mapping[str, Any]] = []
    for row in rows:
        raw = _entry(row).get(key)
        if isinstance(raw, Mapping):
            raw = (raw,)
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            continue
        for item in raw:
            if isinstance(item, Mapping):
                projected.append({column: item.get(column) for column in columns})
    return DataSet(columns=columns, rows=tuple(projected))


def _entry(row: RcaAuditRow) -> Mapping[str, Any]:
    value = getattr(row, "entry", {})
    return value if isinstance(value, Mapping) else {}


def _first(entries: Sequence[Mapping[str, Any]], *keys: str) -> Any:
    for entry in entries:
        for key in keys:
            value = entry.get(key)
            if value is not None and value != "":
                return value
    return None


def _last(entries: Sequence[Mapping[str, Any]], *keys: str) -> Any:
    return _first(tuple(reversed(entries)), *keys)


def _duration_seconds(start: str, end: str) -> float | None:
    try:
        duration = datetime.fromisoformat(end) - datetime.fromisoformat(start)
        return max(0.0, duration.total_seconds())
    except ValueError:
        return None


def _phase(action_kind: str) -> str:
    lowered = action_kind.lower()
    for token, phase in (
        ("detect", "detection"),
        ("ingest", "detection"),
        ("rca", "analysis"),
        ("risk", "decision"),
        ("quality", "decision"),
        ("approve", "approval"),
        ("hil", "approval"),
        ("rollback", "recovery"),
        ("execute", "response"),
        ("deliver", "response"),
        ("audit", "audit"),
    ):
        if token in lowered:
            return phase
    return "processing"


__all__ = ["project_rca_report"]
