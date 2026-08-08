"""Read-only audit console tools and projections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import (
    SideEffectClass,
    ToolResult,
    _optional_int,
    _optional_str,
    _require_str,
    _summary,
)


@runtime_checkable
class AuditReader(Protocol):
    """Minimal read-only audit surface used by console tools."""

    audit_entries: Iterable[Mapping[str, Any]]


class ExplainVerdictTool:
    """Read the audit trail for one event id and summarize the outcome."""

    name = "explain_verdict"
    description = (
        "Return the audit-trail projection for one event_id: tier, decision, "
        "citing rule ids, and mode. Read-only."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, audit_reader: AuditReader) -> None:
        self._audit = audit_reader

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        raw_event_id = _require_str(arguments, "event_id").strip()
        if not raw_event_id:
            return ToolResult(
                status="error",
                preview="explain_verdict requires a non-empty 'event_id'",
            )
        try:
            UUID(raw_event_id)
        except ValueError:
            return ToolResult(
                status="error",
                preview=f"explain_verdict 'event_id' must be a UUID, got {raw_event_id!r}",
            )
        matched = _select_audit(self._audit, event_id=raw_event_id)
        projections = [_project_audit_entry(entry) for entry in matched]
        return ToolResult(
            status="ok" if projections else "abstain",
            data={"event_id": raw_event_id, "entries": projections},
            preview=f"explain_verdict[{raw_event_id[:8]}...]: {len(projections)} entry(ies)",
            evidence_refs=tuple(
                f"audit:{projection['audit_id']}"
                for projection in projections
                if projection.get("audit_id")
            ),
        )


class QueryAuditTool:
    """Filter the audit log by structured fields."""

    name = "query_audit"
    description = (
        "Filter the audit log by any of event_id / actor / decision / "
        "action_kind / since. Paginated (limit)."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, audit_reader: AuditReader) -> None:
        self._audit = audit_reader

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        limit = _optional_int(arguments, "limit", default=20, minimum=1, maximum=200)
        filters = {
            "event_id": _optional_str(arguments, "event_id", default="").strip(),
            "actor": _optional_str(arguments, "actor", default="").strip(),
            "decision": _optional_str(arguments, "decision", default="").strip(),
            "action_kind": _optional_str(arguments, "action_kind", default="").strip(),
            "since": _optional_str(arguments, "since", default="").strip(),
        }
        if not any(filters.values()):
            return ToolResult(
                status="error",
                preview=(
                    "query_audit requires at least one filter "
                    "(event_id / actor / decision / action_kind / since)"
                ),
            )
        since_dt: datetime | None = None
        if filters["since"]:
            try:
                since_dt = datetime.fromisoformat(filters["since"].replace("Z", "+00:00"))
            except ValueError:
                return ToolResult(
                    status="error",
                    preview=f"query_audit 'since' MUST be RFC 3339; got {filters['since']!r}",
                )
        entries = _select_audit(
            self._audit,
            event_id=filters["event_id"] or None,
            actor_substring=filters["actor"] or None,
            decision=filters["decision"] or None,
            action_kind=filters["action_kind"] or None,
            since=since_dt,
        )
        projections = [_project_audit_entry(entry) for entry in entries[:limit]]
        return ToolResult(
            status="ok" if projections else "abstain",
            data={"filters": filters, "total_matched": len(entries), "entries": projections},
            preview=(
                f"query_audit: {len(projections)} of {len(entries)} entry(ies) "
                f"(filters={_filter_summary(filters)})"
            ),
            evidence_refs=tuple(
                f"audit:{projection['audit_id']}"
                for projection in projections
                if projection.get("audit_id")
            ),
        )


def _unwrap_audit_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        return {}
    inner = record.get("entry")
    if isinstance(inner, Mapping) and ("previous_hash" in record or "entry_hash" in record):
        return inner
    return record


def _select_audit(
    audit_reader: AuditReader,
    *,
    event_id: str | None = None,
    actor_substring: str | None = None,
    decision: str | None = None,
    action_kind: str | None = None,
    since: datetime | None = None,
) -> list[Mapping[str, Any]]:
    matched: list[tuple[datetime | None, Mapping[str, Any]]] = []
    for record in audit_reader.audit_entries:
        entry = _unwrap_audit_record(record)
        if event_id and entry.get("event_id") != event_id:
            continue
        if actor_substring and actor_substring not in str(entry.get("actor", "")):
            continue
        if decision and entry.get("decision") != decision:
            continue
        if action_kind and entry.get("action_kind") != action_kind:
            continue
        recorded_raw = entry.get("recorded_at")
        recorded_dt: datetime | None = None
        if isinstance(recorded_raw, str):
            try:
                recorded_dt = datetime.fromisoformat(recorded_raw.replace("Z", "+00:00"))
            except ValueError:
                recorded_dt = None
        if since is not None and recorded_dt is not None and recorded_dt < since:
            continue
        matched.append((recorded_dt, entry))
    matched.sort(key=lambda pair: (pair[0] is None, pair[0] or datetime.min.replace(tzinfo=UTC)))
    return [entry for _, entry in matched]


def _project_audit_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    stable = {
        "audit_id": entry.get("audit_id") or entry.get("id"),
        "event_id": entry.get("event_id"),
        "action_kind": entry.get("action_kind"),
        "actor": entry.get("actor"),
        "decision": entry.get("decision"),
        "mode": entry.get("mode"),
        "stage": entry.get("stage"),
        "recorded_at": entry.get("recorded_at"),
        "citing_rule_ids": list(
            entry.get("candidate_rule_ids") or entry.get("citing_rule_ids") or []
        ),
        "reason": _summary(str(entry.get("reason", ""))) or None,
    }
    known_keys = set(stable) | {"idempotency_key", "resource_type"}
    extra = {key: value for key, value in entry.items() if key not in known_keys}
    if extra:
        stable["extra"] = extra
    return {key: value for key, value in stable.items() if value is not None}


def _filter_summary(filters: Mapping[str, str]) -> str:
    return ", ".join(f"{key}={value!r}" for key, value in filters.items() if value)
