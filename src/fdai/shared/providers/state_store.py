"""State store - Postgres-backed by default; DI seam for alternate backends.

Async by contract - real backends (asyncpg on PostgreSQL) are I/O bound and
would otherwise block the event loop. Only CPU / startup-only seams
(SchemaRegistry, ContractValidator, ConfigProvider) stay sync.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class IncidentAppendStatus(StrEnum):
    """Atomic incident persistence result."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"


class IncidentWriteConflictError(RuntimeError):
    """Raised when a lifecycle write's expected state is no longer current."""


@runtime_checkable
class StateStore(Protocol):
    """Append-only audit + tracked state + KPI emission."""

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        """Append a single audit record.

        Real backends hash-chain the entry to the previous one (see
        ``security-and-identity.md § Auditability``). The Protocol only fixes
        the boundary; the chaining rule is a contract on implementations.
        """
        ...

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        """Return the tracked state for ``key`` or ``None`` when absent."""
        ...

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        """Persist ``value`` under ``key``.

        Semantics are idempotent by key: re-applying the same ``(key, value)``
        pair MUST NOT create duplicate history - the value replaces the prior
        state atomically.
        """
        ...

    async def append_incident_transition(self, entry: Mapping[str, Any]) -> IncidentAppendStatus:
        """Append one incident lifecycle transition.

        Semantically an ``append_audit_entry`` restricted to incident
        events (``kind`` is one of ``incident.open``, ``incident.members``,
        ``incident.assigned``, ``incident.ticket``, or
        ``incident.transition``); kept as a distinct method so a fork MAY route
        incident audit to a separate stream / topic without touching the
        general audit surface.

        Idempotency is on the caller: the ``core/incident`` registry
        derives ``idempotency_key`` from ``(incident_id, target_state,
        actor_oid)`` and re-delivery of the same key MUST NOT create a
        duplicate row. Real backends enforce this with a UNIQUE
        constraint on ``idempotency_key``.
        """
        ...

    async def read_incident_transitions(self) -> tuple[Mapping[str, Any], ...]:
        """Return ordered lifecycle rows for replay and canonical reload."""
        ...


def classify_incident_append(
    history: tuple[Mapping[str, Any], ...],
    entry: Mapping[str, Any],
) -> IncidentAppendStatus:
    """Validate one append against the persisted incident history."""
    key = _required(entry, "idempotency_key")
    duplicate = next(
        (row for row in history if row.get("idempotency_key") == key),
        None,
    )
    if duplicate is not None:
        if not _same_incident_intent(duplicate, entry):
            raise IncidentWriteConflictError(f"idempotency key payload conflict: {key}")
        return IncidentAppendStatus.DUPLICATE

    incident_id = _required(entry, "incident_id")
    incident_history = tuple(row for row in history if row.get("incident_id") == incident_id)
    kind = _required(entry, "kind")
    opened = next(
        (row for row in incident_history if row.get("kind") == "incident.open"),
        None,
    )
    if kind == "incident.open":
        if opened is None:
            return IncidentAppendStatus.APPLIED
        if not _same_incident_intent(opened, entry):
            raise IncidentWriteConflictError(f"conflicting incident.open: {incident_id}")
        return IncidentAppendStatus.DUPLICATE
    if opened is None:
        raise IncidentWriteConflictError(f"{kind} precedes incident.open: {incident_id}")

    if kind == "incident.transition":
        current_state = str(opened.get("state") or "")
        for row in incident_history:
            if row.get("kind") == "incident.transition":
                current_state = str(row.get("to_state") or current_state)
        target_state = _required(entry, "to_state")
        if current_state == target_state:
            return IncidentAppendStatus.DUPLICATE
        expected_state = _required(entry, "from_state")
        if current_state != expected_state:
            raise IncidentWriteConflictError(
                f"incident state conflict for {incident_id}: "
                f"expected={expected_state}, current={current_state}"
            )
    elif kind == "incident.assigned":
        current_assignee = opened.get("assignee_oid")
        for row in incident_history:
            if row.get("kind") == "incident.assigned":
                current_assignee = row.get("assignee_oid")
        target_assignee = entry.get("assignee_oid")
        if current_assignee == target_assignee:
            return IncidentAppendStatus.DUPLICATE
        if current_assignee != entry.get("from_assignee_oid"):
            raise IncidentWriteConflictError(f"incident assignee conflict: {incident_id}")
    return IncidentAppendStatus.APPLIED


def _same_incident_intent(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> bool:
    kind = str(incoming.get("kind") or "")
    if kind == "incident.members":
        existing_members = existing.get("member_event_ids")
        incoming_members = incoming.get("member_event_ids")
        return (
            existing.get("incident_id") == incoming.get("incident_id")
            and isinstance(existing_members, list)
            and isinstance(incoming_members, list)
            and sorted(existing_members) == sorted(incoming_members)
        )
    fields = {
        "incident.open": (
            "incident_id",
            "state",
            "severity",
            "assignee_oid",
            "correlation_keys",
        ),
        "incident.transition": (
            "incident_id",
            "from_state",
            "to_state",
            "from_severity",
            "severity",
            "actor_oid",
            "at",
            "reason",
        ),
        "incident.assigned": (
            "incident_id",
            "from_assignee_oid",
            "assignee_oid",
            "actor_oid",
            "at",
        ),
        "incident.ticket": ("incident_id", "provider", "ticket_id", "ticket_url"),
    }.get(kind)
    return fields is not None and all(
        existing.get(field) == incoming.get(field) for field in fields
    )


def _required(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise IncidentWriteConflictError(f"incident entry {key} MUST be a non-empty string")
    return value


__all__ = [
    "IncidentAppendStatus",
    "IncidentWriteConflictError",
    "StateStore",
    "classify_incident_append",
]
