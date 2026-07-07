"""Incident lifecycle - first-class correlation entity.

Design contract: ``docs/roadmap/sre-agent-scope.md § 3.1``.

Public surface:

- :class:`IncidentRegistry` - deterministic incident id + idempotent
  member-event append; the only in-process authority that constructs
  or mutates an :class:`~fdai.shared.contracts.models.Incident`.
- :class:`IncidentStateMachine` - encodes the legal state graph
  (``open → triaging → mitigated → resolved → closed`` + re-open); raises
  :class:`IncidentTransitionError` on any illegal edge.
- :class:`IncidentTransition` - the record persisted per transition; a
  concrete :class:`~fdai.shared.providers.state_store.StateStore` writes
  each one to the append-only audit chain via
  :meth:`~fdai.shared.providers.state_store.StateStore.append_incident_transition`.

Every method is deterministic and side-effect-free at the pure level;
persistence goes through the injected ``StateStore`` seam so a fork can
replace the backend without touching this module.
"""

from __future__ import annotations

from .registry import IncidentRegistry, incident_id_for
from .state_machine import (
    LEGAL_TRANSITIONS,
    IncidentStateMachine,
    IncidentTransition,
    IncidentTransitionError,
)

__all__ = [
    "LEGAL_TRANSITIONS",
    "IncidentRegistry",
    "IncidentStateMachine",
    "IncidentTransition",
    "IncidentTransitionError",
    "incident_id_for",
]
