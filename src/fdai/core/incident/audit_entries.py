"""Canonical append-only audit row builders for incident lifecycle writes."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState

from .lifecycle import IncidentTicketLink
from .state_machine import IncidentTransition


def open_audit_entry(*, incident: Incident, actor_oid: str) -> Mapping[str, object]:
    return {
        "kind": "incident.open",
        "idempotency_key": f"{incident.incident_id}::open",
        "correlation_id": str(incident.incident_id),
        "incident_id": str(incident.incident_id),
        "severity": incident.severity.value,
        "state": IncidentState.OPEN.value,
        "actor_oid": actor_oid,
        "opened_at": incident.opened_at.isoformat(),
        "assignee_oid": incident.assignee_oid,
        "correlation_keys": list(incident.correlation_keys),
        "member_event_ids": [str(event_id) for event_id in incident.member_event_ids],
    }


def transition_audit_entry(
    transition: IncidentTransition,
    *,
    incident: Incident,
    target_severity: IncidentSeverity,
) -> Mapping[str, object]:
    return {
        "kind": "incident.transition",
        "idempotency_key": transition.idempotency_key(),
        "correlation_id": str(transition.incident_id),
        "incident_id": str(transition.incident_id),
        "from_state": transition.from_state.value,
        "to_state": transition.to_state.value,
        "from_severity": incident.severity.value,
        "severity": target_severity.value,
        "actor_oid": transition.actor_oid,
        "at": transition.at.isoformat(),
        "reason": transition.reason,
    }


def members_audit_entry(
    *,
    incident: Incident,
    added_member_event_ids: tuple[UUID, ...],
    actor_oid: str,
    at: datetime,
) -> Mapping[str, object]:
    canonical_members = "|".join(sorted(str(member) for member in added_member_event_ids))
    member_digest = hashlib.sha256(canonical_members.encode()).hexdigest()
    return {
        "kind": "incident.members",
        "idempotency_key": f"{incident.incident_id}::members::{member_digest}",
        "correlation_id": str(incident.incident_id),
        "incident_id": str(incident.incident_id),
        "severity": incident.severity.value,
        "state": incident.state.value,
        "actor_oid": actor_oid,
        "at": at.isoformat(),
        "member_event_ids": [str(member) for member in added_member_event_ids],
    }


def assignment_audit_entry(
    *,
    incident: Incident,
    assignee_oid: str | None,
    actor_oid: str,
    at: datetime,
) -> Mapping[str, object]:
    target = assignee_oid or "unassigned"
    return {
        "kind": "incident.assigned",
        "idempotency_key": f"{incident.incident_id}::assigned::{target}::{at.isoformat()}",
        "correlation_id": str(incident.incident_id),
        "incident_id": str(incident.incident_id),
        "severity": incident.severity.value,
        "state": incident.state.value,
        "from_assignee_oid": incident.assignee_oid,
        "assignee_oid": assignee_oid,
        "actor_oid": actor_oid,
        "at": at.isoformat(),
    }


def ticket_audit_entry(link: IncidentTicketLink) -> Mapping[str, object]:
    fingerprint = hashlib.sha256(f"{link.provider}\0{link.ticket_id}".encode()).hexdigest()
    return {
        "kind": "incident.ticket",
        "idempotency_key": f"{link.incident_id}::ticket::{fingerprint}",
        "correlation_id": str(link.incident_id),
        "incident_id": str(link.incident_id),
        "provider": link.provider,
        "ticket_id": link.ticket_id,
        "ticket_url": link.ticket_url,
        "actor_oid": link.linked_by,
        "at": link.linked_at.isoformat(),
    }


__all__ = [
    "assignment_audit_entry",
    "members_audit_entry",
    "open_audit_entry",
    "ticket_audit_entry",
    "transition_audit_entry",
]
