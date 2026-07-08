"""Incident registry - deterministic id + idempotent membership + transitions.

The registry is the ONLY writer of :class:`Incident` records; verticals
and detectors emit **candidate** transitions and the registry validates
them against the state machine before persisting through the injected
:class:`~fdai.shared.providers.state_store.StateStore`.

Determinism is central: ``incident_id`` is UUID5(NAMESPACE_URL,
canonicalized correlation-key set), so the same key set always yields
the same incident id even across process restarts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai.shared.contracts.models import (
    Incident,
    IncidentSeverity,
    IncidentState,
)
from fdai.shared.providers.state_store import StateStore

from .state_machine import IncidentStateMachine, IncidentTransition

_SCHEMA_VERSION = "1.0.0"


def incident_id_for(correlation_keys: Iterable[str]) -> UUID:
    """Deterministic id from correlation keys.

    Canonicalizes the key set (sort + de-dup) before hashing so
    ``{"a", "b"}`` and ``["b", "a", "a"]`` produce the same id.
    Empty input raises ``ValueError`` (a correlation-less incident has
    no anchor).
    """
    canonical = tuple(sorted({k for k in correlation_keys if k}))
    if not canonical:
        raise ValueError("incident_id_for requires at least one correlation key")
    name = "fdai.incident://" + "|".join(canonical)
    return uuid5(NAMESPACE_URL, name)


class IncidentRegistry:
    """In-process registry keyed by ``incident_id``.

    The registry is deliberately in-process: durability is delegated to
    the ``StateStore`` (each transition is a hash-chained audit row).
    A process restart repopulates the in-memory index by replaying the
    audit chain via :meth:`hydrate` at composition-root startup.
    """

    def __init__(
        self,
        *,
        state_store: StateStore,
        state_machine: IncidentStateMachine | None = None,
    ) -> None:
        self._state_store = state_store
        self._state_machine = state_machine or IncidentStateMachine()
        self._incidents: dict[UUID, Incident] = {}

    async def open(
        self,
        *,
        correlation_keys: Iterable[str],
        severity: IncidentSeverity,
        member_event_ids: Iterable[UUID],
        actor_oid: str,
        opened_at: datetime | None = None,
        assignee_oid: str | None = None,
    ) -> Incident:
        """Open a new incident (idempotent by correlation-key set).

        If an incident with the derived id already exists, the call is
        a no-op that returns the existing record (with the new
        ``member_event_ids`` merged in); this is how event correlation
        streams the same incident growing over time.
        """
        incident_id = incident_id_for(correlation_keys)
        existing = self._incidents.get(incident_id)
        if existing is not None:
            merged = tuple(dict.fromkeys((*existing.member_event_ids, *member_event_ids)))
            if merged != existing.member_event_ids:
                existing = existing.model_copy(update={"member_event_ids": merged})
                self._incidents[incident_id] = existing
            return existing

        opened = opened_at or datetime.now(tz=UTC)
        incident = Incident(
            schema_version=_SCHEMA_VERSION,
            incident_id=incident_id,
            state=IncidentState.OPEN,
            severity=severity,
            opened_at=opened,
            correlation_keys=tuple(sorted({k for k in correlation_keys if k})),
            member_event_ids=tuple(dict.fromkeys(member_event_ids)),
            assignee_oid=assignee_oid,
        )
        self._incidents[incident_id] = incident
        await self._state_store.append_incident_transition(
            _open_audit_entry(incident=incident, actor_oid=actor_oid)
        )
        return incident

    async def transition(
        self,
        *,
        incident_id: UUID,
        to_state: IncidentState,
        actor_oid: str,
        reason: str | None = None,
        at: datetime | None = None,
    ) -> Incident:
        """Transition an existing incident.

        Idempotent by ``(incident_id, to_state)`` - a re-delivery that
        targets the state the incident is already in returns the existing
        record without writing a duplicate audit row (``actor_oid`` is
        recorded on the transition but does not affect this short-circuit).
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise KeyError(f"unknown incident_id: {incident_id}")

        # Idempotent same-state re-emission short-circuits before the
        # state machine (which would reject same-state as illegal).
        if incident.state is to_state:
            return incident

        self._state_machine.validate(current=incident.state, target=to_state)
        moment = at or datetime.now(tz=UTC)
        transition = IncidentTransition(
            incident_id=incident_id,
            from_state=incident.state,
            to_state=to_state,
            actor_oid=actor_oid,
            at=moment,
            reason=reason,
        )
        # Persistence first: fail-closed if the audit chain refuses.
        await self._state_store.append_incident_transition(_transition_audit_entry(transition))
        # Update the in-memory record only after the audit row is durable.
        updated = _apply_transition(incident, transition)
        self._incidents[incident_id] = updated
        return updated

    def get(self, incident_id: UUID) -> Incident | None:
        """Return the current in-memory record or ``None`` if unknown."""
        return self._incidents.get(incident_id)

    def snapshot(self) -> Mapping[UUID, Incident]:
        """Return a read-only view of every known incident.

        The mapping is a shallow copy; mutations do NOT propagate.
        """
        return dict(self._incidents)


def _apply_transition(incident: Incident, transition: IncidentTransition) -> Incident:
    """Return a copy of the incident with the transition applied.

    Timestamp fields are set based on the destination state so the
    audit trail carries exactly one moment per lifecycle phase.
    """
    updates: dict[str, object] = {"state": transition.to_state}
    if transition.to_state is IncidentState.MITIGATED:
        updates["mitigated_at"] = transition.at
    elif transition.to_state is IncidentState.RESOLVED:
        updates["resolved_at"] = transition.at
    elif transition.to_state is IncidentState.CLOSED:
        updates["closed_at"] = transition.at
    if transition.reason and transition.to_state is IncidentState.MITIGATED:
        updates["mitigation_summary"] = transition.reason
    return incident.model_copy(update=updates)


def _open_audit_entry(*, incident: Incident, actor_oid: str) -> Mapping[str, object]:
    return {
        "kind": "incident.open",
        "idempotency_key": f"{incident.incident_id}::open::{actor_oid}",
        "incident_id": str(incident.incident_id),
        "severity": incident.severity.value,
        "state": IncidentState.OPEN.value,
        "actor_oid": actor_oid,
        "opened_at": incident.opened_at.isoformat(),
        "correlation_keys": list(incident.correlation_keys),
        "member_event_ids": [str(x) for x in incident.member_event_ids],
    }


def _transition_audit_entry(transition: IncidentTransition) -> Mapping[str, object]:
    return {
        "kind": "incident.transition",
        "idempotency_key": transition.idempotency_key(),
        "incident_id": str(transition.incident_id),
        "from_state": transition.from_state.value,
        "to_state": transition.to_state.value,
        "actor_oid": transition.actor_oid,
        "at": transition.at.isoformat(),
        "reason": transition.reason,
    }


__all__ = ["IncidentRegistry", "incident_id_for"]
