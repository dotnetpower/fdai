"""Incident state-machine.

Encodes the legal state graph declared in the
:class:`~fdai.shared.contracts.models.IncidentState` docstring and
the schema at ``shared/contracts/incident/schema.json``:

- ``open`` -> ``triaging`` | ``mitigated``
- ``triaging`` -> ``mitigated`` | ``resolved``
- ``mitigated`` -> ``resolved``
- ``resolved`` -> ``closed`` | ``triaging`` (re-open)
- ``closed`` -> terminal

Illegal transitions raise :class:`IncidentTransitionError`. The state
machine is a pure function of the current state + the target state; it
does NOT mutate the incident record itself - that is the registry's job
(``core/incident/registry.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from fdai.shared.contracts.models import IncidentState

# Legal outgoing edges per state. Kept as ``frozenset`` per source state
# so the container itself signals "these are exhaustive" and mutation
# raises at runtime.
LEGAL_TRANSITIONS: Final[Mapping[IncidentState, frozenset[IncidentState]]] = {
    IncidentState.OPEN: frozenset({IncidentState.TRIAGING, IncidentState.MITIGATED}),
    IncidentState.TRIAGING: frozenset({IncidentState.MITIGATED, IncidentState.RESOLVED}),
    IncidentState.MITIGATED: frozenset({IncidentState.RESOLVED}),
    IncidentState.RESOLVED: frozenset({IncidentState.CLOSED, IncidentState.TRIAGING}),
    IncidentState.CLOSED: frozenset(),
}


class IncidentTransitionError(ValueError):
    """Raised on an illegal state transition.

    Fail-closed: the caller MUST NOT proceed to persist a rejected
    transition; the exception is the audit trail entry (a caller that
    catches it and continues is bypassing the safety invariant).
    """


@dataclass(frozen=True, slots=True)
class IncidentTransition:
    """One recorded transition.

    Persisted verbatim by the concrete ``StateStore`` adapter into the
    append-only audit chain; the ``(incident_id, from_state, to_state,
    actor_oid, at)`` tuple is the idempotency key so a re-delivery of the
    same transition intent (which carries the same ``at``) does not create
    a duplicate audit row, while a genuinely distinct later transition on
    the same edge (a repeated reopen, with its own ``at``) is audited.
    """

    incident_id: UUID
    from_state: IncidentState
    to_state: IncidentState
    actor_oid: str
    at: datetime
    reason: str | None = None

    def idempotency_key(self) -> str:
        """Stable de-dupe key for the ``StateStore``.

        Format:
        ``<incident_id>::<from>-><to>::<actor_oid>::<at ISO-8601>``. The
        transition timestamp ``at`` is part of the key so a **legal
        repeated edge** - e.g. a second ``resolved->triaging`` reopen by
        the same actor - does not collide with the first and get silently
        swallowed by the store's UNIQUE dedup (which would drop an audit
        row and diverge audit-replay from live state). A true re-delivery
        of one intent carries the same ``at``, so it still dedups; callers
        MUST pass the originating event's timestamp (not a fresh clock
        read) for that idempotency to hold under redelivery.
        """
        return (
            f"{self.incident_id}::{self.from_state.value}->{self.to_state.value}"
            f"::{self.actor_oid}::{self.at.isoformat()}"
        )


class IncidentStateMachine:
    """Pure evaluator of legal transitions.

    Stateless by design (all data is on the incident + the caller's
    request) so a single instance is shared across the process without
    concurrency concerns.
    """

    def validate(self, *, current: IncidentState, target: IncidentState) -> None:
        """Raise :class:`IncidentTransitionError` if the edge is illegal.

        A same-state "transition" (``current == target``) is treated
        as illegal; callers that need re-emission for idempotency
        route through :meth:`IncidentRegistry.transition` which
        short-circuits before invoking the state machine.
        """
        allowed = LEGAL_TRANSITIONS[current]
        if target not in allowed:
            raise IncidentTransitionError(
                f"illegal transition {current.value!r} -> {target.value!r}: "
                f"allowed from {current.value!r} = "
                f"{sorted(s.value for s in allowed) or ['<terminal>']}"
            )


__all__ = [
    "LEGAL_TRANSITIONS",
    "IncidentStateMachine",
    "IncidentTransition",
    "IncidentTransitionError",
]
