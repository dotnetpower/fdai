"""Incident member source - the seam that feeds T1 causal-chain RCA.

The T1 causal-chain engine (:mod:`fdai.core.rca.causal_chain`) reasons
over the events correlated into one incident, but the control loop
processes a single event at a time and does not hold the incident's
history. This Protocol is the boundary that supplies that history:
given an ``incident_id``, return the incident's member events already
shaped as :class:`CorrelatedEvent` (timestamp, generic ``resource_ref``,
and the ``is_change`` marker).

Design boundaries
-----------------

- **Core stays generic**: the classification of an event as a *change*
  (a mutation/deploy/config-change that can cause a failure) vs a symptom
  is the *source's* responsibility, not the loop's - a fork's adapter
  reads its event store and marks changes. Upstream ships this Protocol
  and a :class:`NoopIncidentMemberSource` default so the loop is
  backward-compatible when no source is wired.
- **Read-only, bounded, abstain-safe**: an implementation returns the
  known members or an empty sequence; it never mutates and never raises
  to block the control decision (the loop treats a failure as "no
  chain", best-effort).
- **No privileged identity in core**: a real store-backed adapter lives
  in ``delivery/`` and is fork-authored.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.core.rca.causal_chain import CorrelatedEvent


@runtime_checkable
class IncidentMemberSource(Protocol):
    """Return the correlated member events of one incident for T1 RCA."""

    async def members(self, *, incident_id: str) -> Sequence[CorrelatedEvent]:
        """Return the incident's member events as ``CorrelatedEvent``s.

        MAY return an empty sequence when the incident is unknown or has
        no other members; MUST NOT return the failure event's own record
        duplicated (the causal-chain engine drops self-events, so a
        duplicate is harmless but wasteful).
        """
        ...


@dataclass(frozen=True, slots=True)
class IncidentRcaContext:
    """Incident members and their exact-generation dependency graph."""

    members: tuple[CorrelatedEvent, ...]
    depends_on: Mapping[str, frozenset[str]]
    inventory_generation: str

    def __post_init__(self) -> None:
        if not self.inventory_generation.strip():
            raise ValueError("IncidentRcaContext.inventory_generation MUST be non-empty")


@runtime_checkable
class IncidentRcaContextSource(Protocol):
    """Load one time-consistent T1 context under an implementation deadline."""

    async def context(
        self,
        *,
        incident_id: str,
        resource_ref: str,
        event_type: str,
        correlation_id: str | None,
        detected_at: datetime,
    ) -> IncidentRcaContext | None: ...


class NoopIncidentMemberSource:
    """Default source that knows no members (feature-off, no behavior).

    Symmetric to the other upstream no-op providers: wiring the control
    loop without a real member source keeps T1 causal-chain RCA dark
    while T0 (and, when wired, T2) RCA still runs.
    """

    async def members(self, *, incident_id: str) -> Sequence[CorrelatedEvent]:  # noqa: ARG002
        return ()


__all__ = [
    "IncidentMemberSource",
    "IncidentRcaContext",
    "IncidentRcaContextSource",
    "NoopIncidentMemberSource",
]
