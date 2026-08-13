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

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai.shared.contracts.models import (
    Incident,
    IncidentSeverity,
    IncidentState,
)
from fdai.shared.providers.state_store import (
    IncidentAppendStatus,
    IncidentWriteConflictError,
    StateStore,
)

from .audit_entries import (
    assignment_audit_entry,
    members_audit_entry,
    open_audit_entry,
    severity_audit_entry,
    ticket_audit_entry,
    transition_audit_entry,
)
from .lifecycle import IncidentTicketLink
from .replay import (
    IncidentReplayError,
    apply_incident_transition,
    rehydrate_incidents,
)
from .state_machine import IncidentStateMachine, IncidentTransition
from .workflow_support import canonical_incident_correlation_keys

_SCHEMA_VERSION = "1.0.0"
_SEVERITY_RANK = {
    IncidentSeverity.SEV1: 1,
    IncidentSeverity.SEV2: 2,
    IncidentSeverity.SEV3: 3,
    IncidentSeverity.SEV4: 4,
    IncidentSeverity.SEV5: 5,
}


@dataclass(frozen=True, slots=True)
class IncidentOpenResult:
    """Incident returned by open plus whether this registry created it."""

    incident: Incident
    created: bool
    severity_changed: bool = False
    previous_severity: IncidentSeverity | None = None


@dataclass(frozen=True, slots=True)
class IncidentMutationResult:
    """Canonical incident plus whether this registry applied the mutation."""

    incident: Incident
    changed: bool


class IncidentProjection(Protocol):
    """Current-state read-model sink for canonical Incident revisions."""

    async def project(
        self,
        incident: Incident,
        *,
        updated_at: datetime,
    ) -> object: ...


def incident_id_for(correlation_keys: Iterable[str]) -> UUID:
    """Deterministic id from correlation keys.

    Canonicalizes the key set (sort + de-dup) before hashing so
    ``{"a", "b"}`` and ``["b", "a", "a"]`` produce the same id.
    Empty input raises ``ValueError`` (a correlation-less incident has
    no anchor).
    """
    canonical = canonical_incident_correlation_keys(correlation_keys)
    if not canonical:
        raise ValueError("incident_id_for requires at least one correlation key")
    name = "fdai.incident://" + "|".join(canonical)
    return uuid5(NAMESPACE_URL, name)


class IncidentRegistry:
    """In-process registry keyed by ``incident_id``.

    The registry is deliberately in-process: durability is delegated to
    the ``StateStore`` (each transition is a hash-chained audit row), so
    the audit chain - not this index - is the source of truth. The
    in-memory index is volatile and must be rebuilt with :meth:`rehydrate`
    before traffic after restart. Production composition replays ordered
    ``incident.open`` / ``incident.members`` / ``incident.transition`` rows
    at startup and fails closed on an invalid chain.
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
        self._projection: IncidentProjection | None = None
        self._write_lock = asyncio.Lock()

    async def bind_projection(
        self,
        projection: IncidentProjection,
        *,
        entries: Iterable[Mapping[str, object]],
    ) -> None:
        """Project rehydrated state, then keep later canonical mutations current."""
        ordered_entries = tuple(entries)
        async with self._write_lock:
            if self._projection is not None:
                raise RuntimeError("incident projection is already bound")
            updated_at = _latest_incident_updates(ordered_entries)
            for incident_id, incident in sorted(
                self._incidents.items(),
                key=lambda item: str(item[0]),
            ):
                await projection.project(
                    incident,
                    updated_at=updated_at.get(incident_id, incident.opened_at),
                )
            self._projection = projection

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
        result = await self.open_with_status(
            correlation_keys=correlation_keys,
            severity=severity,
            member_event_ids=member_event_ids,
            actor_oid=actor_oid,
            opened_at=opened_at,
            assignee_oid=assignee_oid,
        )
        return result.incident

    async def open_with_status(
        self,
        *,
        correlation_keys: Iterable[str],
        severity: IncidentSeverity,
        member_event_ids: Iterable[UUID],
        actor_oid: str,
        opened_at: datetime | None = None,
        assignee_oid: str | None = None,
    ) -> IncidentOpenResult:
        """Open an incident and decide ``created`` inside the write lock."""
        keys = tuple(correlation_keys)
        members = tuple(member_event_ids)
        incident_id = incident_id_for(keys)
        async with self._write_lock:
            existing = self._incidents.get(incident_id)
            if existing is not None:
                (
                    existing,
                    severity_changed,
                    previous_severity,
                ) = await self._escalate_severity_if_needed(
                    incident=existing,
                    target=severity,
                    actor_oid=actor_oid,
                    at=opened_at or datetime.now(tz=UTC),
                )
                added = tuple(
                    member for member in members if member not in existing.member_event_ids
                )
                merged = (*existing.member_event_ids, *added)
                if merged != existing.member_event_ids:
                    updated = existing.model_copy(update={"member_event_ids": merged})
                    status = await self._persist(
                        members_audit_entry(
                            incident=updated,
                            added_member_event_ids=added,
                            actor_oid=actor_oid,
                            at=opened_at or datetime.now(tz=UTC),
                        ),
                        incident_id=incident_id,
                    )
                    if status is IncidentAppendStatus.DUPLICATE:
                        existing = await self._reload_canonical(incident_id)
                    else:
                        self._incidents[incident_id] = updated
                        existing = updated
                return IncidentOpenResult(
                    incident=existing,
                    created=False,
                    severity_changed=severity_changed,
                    previous_severity=previous_severity,
                )

            opened = opened_at or datetime.now(tz=UTC)
            incident = Incident(
                schema_version=_SCHEMA_VERSION,
                incident_id=incident_id,
                state=IncidentState.OPEN,
                severity=severity,
                opened_at=opened,
                correlation_keys=tuple(sorted({k for k in keys if k})),
                member_event_ids=tuple(dict.fromkeys(members)),
                assignee_oid=assignee_oid,
            )
            status = await self._persist(
                open_audit_entry(incident=incident, actor_oid=actor_oid),
                incident_id=incident_id,
            )
            if status is IncidentAppendStatus.DUPLICATE:
                canonical = await self._reload_canonical(incident_id)
                added = tuple(
                    member for member in members if member not in canonical.member_event_ids
                )
                if added:
                    await self._persist(
                        members_audit_entry(
                            incident=canonical.model_copy(
                                update={
                                    "member_event_ids": (
                                        *canonical.member_event_ids,
                                        *added,
                                    )
                                }
                            ),
                            added_member_event_ids=added,
                            actor_oid=actor_oid,
                            at=opened,
                        ),
                        incident_id=incident_id,
                    )
                    canonical = await self._reload_canonical(incident_id)
                return IncidentOpenResult(incident=canonical, created=False)
            self._incidents[incident_id] = incident
            await self._project(incident, updated_at=opened)
            return IncidentOpenResult(incident=incident, created=True)

    async def _escalate_severity_if_needed(
        self,
        *,
        incident: Incident,
        target: IncidentSeverity,
        actor_oid: str,
        at: datetime,
    ) -> tuple[Incident, bool, IncidentSeverity | None]:
        canonical = incident
        for _attempt in range(2):
            if _SEVERITY_RANK[target] >= _SEVERITY_RANK[canonical.severity]:
                return canonical, False, None
            previous_severity = canonical.severity
            updated = canonical.model_copy(update={"severity": target})
            try:
                status = await self._persist(
                    severity_audit_entry(
                        incident=canonical,
                        target_severity=target,
                        actor_oid=actor_oid,
                        at=at,
                    ),
                    incident_id=canonical.incident_id,
                )
            except IncidentWriteConflictError:
                canonical = await self._reload_canonical(canonical.incident_id)
                continue
            if status is IncidentAppendStatus.DUPLICATE:
                canonical = await self._reload_canonical(canonical.incident_id)
                return canonical, False, None
            else:
                self._incidents[canonical.incident_id] = updated
                canonical = updated
                await self._project(canonical, updated_at=at)
            return canonical, True, previous_severity
        raise IncidentWriteConflictError(
            f"incident severity escalation did not converge: {canonical.incident_id}"
        )

    async def transition(
        self,
        *,
        incident_id: UUID,
        to_state: IncidentState,
        actor_oid: str,
        reason: str | None = None,
        severity: IncidentSeverity | None = None,
        at: datetime | None = None,
    ) -> Incident:
        """Transition an existing incident.

        Idempotent by ``(incident_id, to_state)`` - a re-delivery that
        targets the state the incident is already in returns the existing
        record without writing a duplicate audit row (``actor_oid`` is
        recorded on the transition but does not affect this short-circuit).
        """
        result = await self.transition_with_status(
            incident_id=incident_id,
            to_state=to_state,
            actor_oid=actor_oid,
            reason=reason,
            severity=severity,
            at=at,
        )
        return result.incident

    async def transition_with_status(
        self,
        *,
        incident_id: UUID,
        to_state: IncidentState,
        actor_oid: str,
        reason: str | None = None,
        severity: IncidentSeverity | None = None,
        at: datetime | None = None,
    ) -> IncidentMutationResult:
        """Transition and report whether this call applied the canonical row."""
        async with self._write_lock:
            incident = self._incidents.get(incident_id)
            if incident is None:
                raise KeyError(f"unknown incident_id: {incident_id}")

            # Idempotent same-state re-emission short-circuits before the
            # state machine (which would reject same-state as illegal).
            if incident.state is to_state:
                if severity is not None and severity is not incident.severity:
                    raise ValueError("severity cannot change on a same-state transition")
                canonical = await self._reload_canonical(incident_id)
                if canonical.state is not to_state:
                    raise IncidentWriteConflictError(
                        f"stale same-state transition for {incident_id}: "
                        f"canonical={canonical.state.value}"
                    )
                return IncidentMutationResult(incident=canonical, changed=False)

            self._state_machine.validate(current=incident.state, target=to_state)
            target_severity = severity or incident.severity
            if target_severity is not incident.severity and not (
                incident.state is IncidentState.RESOLVED and to_state is IncidentState.TRIAGING
            ):
                raise ValueError("severity can change only on resolved -> triaging reopen")
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
            status = await self._persist(
                transition_audit_entry(
                    transition,
                    incident=incident,
                    target_severity=target_severity,
                ),
                incident_id=incident_id,
            )
            if status is IncidentAppendStatus.DUPLICATE:
                canonical = await self._reload_canonical(incident_id)
                if canonical.state is not to_state or canonical.severity is not target_severity:
                    raise IncidentWriteConflictError(
                        f"canonical incident differs after duplicate transition: {incident_id}"
                    )
                return IncidentMutationResult(incident=canonical, changed=False)
            # Update the in-memory record only after the audit row is durable.
            updated = apply_incident_transition(
                incident,
                transition,
                severity=target_severity,
            )
            self._incidents[incident_id] = updated
            await self._project(updated, updated_at=moment)
            return IncidentMutationResult(incident=updated, changed=True)

    async def assign(
        self,
        *,
        incident_id: UUID,
        assignee_oid: str | None,
        actor_oid: str,
        at: datetime | None = None,
    ) -> Incident:
        """Assign or unassign an incident, persistence-first and idempotently."""
        result = await self.assign_with_status(
            incident_id=incident_id,
            assignee_oid=assignee_oid,
            actor_oid=actor_oid,
            at=at,
        )
        return result.incident

    async def assign_with_status(
        self,
        *,
        incident_id: UUID,
        assignee_oid: str | None,
        actor_oid: str,
        at: datetime | None = None,
    ) -> IncidentMutationResult:
        """Assign and report whether this call applied the canonical row."""
        target = (assignee_oid or "").strip() or None
        async with self._write_lock:
            incident = self._incidents.get(incident_id)
            if incident is None:
                raise KeyError(f"unknown incident_id: {incident_id}")
            if incident.assignee_oid == target:
                canonical = await self._reload_canonical(incident_id)
                if canonical.assignee_oid != target:
                    raise IncidentWriteConflictError(
                        f"stale same-assignee mutation for {incident_id}"
                    )
                return IncidentMutationResult(incident=canonical, changed=False)
            moment = at or datetime.now(tz=UTC)
            status = await self._persist(
                assignment_audit_entry(
                    incident=incident,
                    assignee_oid=target,
                    actor_oid=actor_oid,
                    at=moment,
                ),
                incident_id=incident_id,
            )
            if status is IncidentAppendStatus.DUPLICATE:
                return IncidentMutationResult(
                    incident=await self._reload_canonical(incident_id),
                    changed=False,
                )
            updated = incident.model_copy(update={"assignee_oid": target})
            self._incidents[incident_id] = updated
            return IncidentMutationResult(incident=updated, changed=True)

    async def link_ticket(
        self,
        *,
        incident_id: UUID,
        provider: str,
        ticket_id: str,
        actor_oid: str,
        ticket_url: str | None = None,
        at: datetime | None = None,
    ) -> IncidentTicketLink:
        """Append an idempotent external-ticket association audit row."""
        normalized_provider = provider.strip().lower()
        normalized_ticket = ticket_id.strip()
        normalized_url = (ticket_url or "").strip() or None
        if not normalized_provider:
            raise ValueError("ticket provider MUST be non-empty")
        if not normalized_ticket:
            raise ValueError("ticket_id MUST be non-empty")
        if normalized_url is not None and not normalized_url.startswith("https://"):
            raise ValueError("ticket_url MUST use https://")
        moment = at or datetime.now(tz=UTC)
        async with self._write_lock:
            if incident_id not in self._incidents:
                raise KeyError(f"unknown incident_id: {incident_id}")
            link = IncidentTicketLink(
                incident_id=incident_id,
                provider=normalized_provider,
                ticket_id=normalized_ticket,
                ticket_url=normalized_url,
                linked_at=moment,
                linked_by=actor_oid,
            )
            await self._persist(ticket_audit_entry(link), incident_id=incident_id)
            return link

    def get(self, incident_id: UUID) -> Incident | None:
        """Return the current in-memory record or ``None`` if unknown."""
        return self._incidents.get(incident_id)

    def snapshot(self) -> Mapping[UUID, Incident]:
        """Return a read-only view of every known incident.

        The mapping is a shallow copy; mutations do NOT propagate.
        """
        return dict(self._incidents)

    def rehydrate(self, entries: Iterable[Mapping[str, object]]) -> int:
        """Rebuild the in-memory index from ordered lifecycle audit rows.

        Validation happens against a temporary map. A malformed row leaves the
        live registry unchanged so startup fails closed without exposing a
        partially recovered incident roster.
        """
        restored = rehydrate_incidents(
            entries,
            state_machine=self._state_machine,
            incident_id_factory=incident_id_for,
            schema_version=_SCHEMA_VERSION,
        )
        self._incidents = restored
        return len(restored)

    async def _reload_canonical(self, incident_id: UUID) -> Incident:
        entries = await self._state_store.read_incident_transitions()
        restored = rehydrate_incidents(
            entries,
            state_machine=self._state_machine,
            incident_id_factory=incident_id_for,
            schema_version=_SCHEMA_VERSION,
        )
        self._incidents = {
            restored_id: (
                self._incidents[restored_id]
                if self._incidents.get(restored_id) == restored_incident
                else restored_incident
            )
            for restored_id, restored_incident in restored.items()
        }
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise IncidentWriteConflictError(
                f"canonical incident missing after duplicate: {incident_id}"
            )
        return incident

    async def _persist(
        self,
        entry: Mapping[str, object],
        *,
        incident_id: UUID,
    ) -> IncidentAppendStatus:
        try:
            return await self._state_store.append_incident_transition(entry)
        except IncidentWriteConflictError:
            await self._reload_canonical(incident_id)
            raise

    async def _project(self, incident: Incident, *, updated_at: datetime) -> None:
        if self._projection is not None:
            await self._projection.project(incident, updated_at=updated_at)


def _latest_incident_updates(
    entries: Iterable[Mapping[str, object]],
) -> dict[UUID, datetime]:
    latest: dict[UUID, datetime] = {}
    for entry in entries:
        raw_incident_id = entry.get("incident_id")
        raw_at = entry.get("at") or entry.get("opened_at")
        if not isinstance(raw_incident_id, str) or not isinstance(raw_at, str):
            continue
        incident_id = UUID(raw_incident_id)
        observed_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        previous = latest.get(incident_id)
        if previous is None or observed_at > previous:
            latest[incident_id] = observed_at
    return latest


__all__ = [
    "IncidentOpenResult",
    "IncidentMutationResult",
    "IncidentRegistry",
    "IncidentReplayError",
    "IncidentTicketLink",
    "incident_id_for",
]
