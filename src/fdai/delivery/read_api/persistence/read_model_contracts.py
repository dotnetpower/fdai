"""Audit, incident, KPI, and HIL read-model contracts."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
KPI_AUDIT_SAMPLE_LIMIT = 500


@dataclass(frozen=True, slots=True)
class AuditItem:
    seq: int
    event_id: str
    correlation_id: str | None
    actor: str
    action_kind: str
    mode: str
    entry: Mapping[str, Any]
    entry_hash: str
    previous_hash: str
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "actor": self.actor,
            "action_kind": self.action_kind,
            "mode": self.mode,
            "entry": dict(self.entry),
            "entry_hash": self.entry_hash,
            "previous_hash": self.previous_hash,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: Sequence[AuditItem]
    next_cursor: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "next_cursor": self.next_cursor,
        }


IncidentStatus = Literal["open", "in_progress", "resolved"]
IncidentStatusFilter = Literal["active", "resolved", "all"]


@dataclass(frozen=True, slots=True)
class AuditQueryFilters:
    mode: str | None = None
    tier: str | None = None
    action_kind: str | None = None
    outcome: str | None = None
    vertical: str | None = None
    window_days: int | None = None
    from_seq: int | None = None
    through_seq: int | None = None


@dataclass(frozen=True, slots=True)
class IncidentSummary:
    correlation_id: str
    incident_id: str | None
    ticket_id: str | None
    title: str
    severity: str
    status: IncidentStatus
    status_source: str
    disposition: str
    verdict: str
    vertical: str
    opened_at: str
    last_updated_at: str
    latest_mode: str
    history_count: int
    involved_agents: Sequence[str]
    last_seq: int

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("last_seq")
        return data


@dataclass(frozen=True, slots=True)
class IncidentPage:
    items: Sequence[IncidentSummary]
    next_cursor: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True, slots=True)
class IncidentCursor:
    snapshot_seq: int
    before_seq: int
    status: IncidentStatusFilter
    vertical: str | None = None


def encode_incident_cursor(cursor: IncidentCursor) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "snapshot_seq": cursor.snapshot_seq,
            "before_seq": cursor.before_seq,
            "status": cursor.status,
            "vertical": cursor.vertical,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_incident_cursor(
    value: str | None, *, status: IncidentStatusFilter, vertical: str | None = None
) -> IncidentCursor | None:
    if value is None or value == "":
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(raw, dict) or raw.get("v") != 1:
            raise ValueError
        snapshot_seq = raw["snapshot_seq"]
        before_seq = raw["before_seq"]
        cursor_status = raw["status"]
        cursor_vertical = raw.get("vertical")
        if (
            not isinstance(snapshot_seq, int)
            or isinstance(snapshot_seq, bool)
            or snapshot_seq < 0
            or not isinstance(before_seq, int)
            or isinstance(before_seq, bool)
            or before_seq < 1
            or cursor_status != status
            or cursor_vertical != vertical
        ):
            raise ValueError
    except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid incident cursor or status mismatch") from exc
    return IncidentCursor(
        snapshot_seq=snapshot_seq,
        before_seq=before_seq,
        status=status,
        vertical=vertical,
    )


@dataclass(frozen=True, slots=True)
class AuditSample:
    from_seq: int | None
    through_seq: int | None
    row_count: int
    limit: int


@dataclass(frozen=True, slots=True)
class DashboardKpi:
    event_count: int
    shadow_share: float
    enforce_share: float
    hil_pending: int
    by_action_kind: Mapping[str, int] = field(default_factory=dict)
    by_outcome: Mapping[str, int] = field(default_factory=dict)
    by_tier: Mapping[str, int] = field(default_factory=dict)
    last_recorded_at: str | None = None
    audit_sample: AuditSample | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["by_action_kind"] = dict(self.by_action_kind)
        data["by_outcome"] = dict(self.by_outcome)
        data["by_tier"] = dict(self.by_tier)
        return data


@dataclass(frozen=True, slots=True)
class HilQueueItem:
    idempotency_key: str
    event_id: str
    action_kind: str
    reason: str
    requested_at: str
    correlation_id: str | None = None
    approval_id: str = ""
    action_id: str = ""
    target_resource_ref: str = ""
    mode: str = ""
    stop_condition: str = ""
    rollback_kind: str = ""
    rollback_reference: str | None = None
    blast_radius_scope: str = ""
    blast_radius_count: int | None = None
    blast_radius_rate_per_minute: int | None = None
    blast_radius_summary: str = ""
    reasons: tuple[str, ...] = ()
    citing_rule_ids: tuple[str, ...] = ()
    ttl_expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        data["citing_rule_ids"] = list(self.citing_rule_ids)
        return data


@dataclass(frozen=True, slots=True)
class HilQueuePage:
    items: Sequence[HilQueueItem]
    total: int

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items], "total": self.total}


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        return 1
    if limit > MAX_LIMIT:
        return MAX_LIMIT
    return limit


__all__ = [
    "DEFAULT_LIMIT",
    "KPI_AUDIT_SAMPLE_LIMIT",
    "MAX_LIMIT",
    "AuditItem",
    "AuditPage",
    "AuditQueryFilters",
    "AuditSample",
    "DashboardKpi",
    "HilQueueItem",
    "HilQueuePage",
    "IncidentCursor",
    "IncidentPage",
    "IncidentStatus",
    "IncidentStatusFilter",
    "IncidentSummary",
    "clamp_limit",
    "decode_incident_cursor",
    "encode_incident_cursor",
]
