"""Deployment-backed incident member source for T1 causal-chain RCA.

A concrete :class:`~fdai.core.rca.member_source.IncidentMemberSource` that
supplies an incident's antecedent **changes** - the ``is_change=True``
events the multi-hop causal-chain engine roots a chain on - from a real
:class:`~fdai.shared.providers.observation.DeploymentHistoryProvider`
(e.g. the Azure Resource Graph adapter). This is the bridge that lets the
``ControlLoop`` reconstruct "a deploy went out, then the error rate rose"
from live estate-change data rather than a fake.

Design
------

- **CSP-neutral**: depends only on the ``DeploymentHistoryProvider``
  Protocol and the incident record - never a vendor SDK. A fork wires it
  with the Azure deployment adapter (or any other) at the composition
  root and passes it to the ``ControlLoop`` as ``incident_member_source``.
- **Incident -> resource + window**: the incident's ``correlation_keys``
  already carry the failing resource refs as ``res:<ref>`` entries (the
  ``EventCorrelator`` writes them), so the source derives which resources
  to pull change history for. The ``lookback`` bounds how far back to
  look for an antecedent change.
- **Best-effort, non-blocking**: per the ``IncidentMemberSource``
  contract, this never raises to block the control decision - an unknown
  incident, a resource-less incident, or a failing deployment query
  yields an empty (or partial) member set, and the causal-chain engine
  simply abstains when it finds no change-rooted chain.
- **Deterministic**: members are de-duplicated by deployment ref in a
  stable order, so the same incident + history always yields the same set.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Final

from fdai.core.rca.causal_chain import CorrelatedEvent
from fdai.shared.contracts.models import Incident
from fdai.shared.providers.observation import (
    DeploymentHistoryError,
    DeploymentHistoryProvider,
)

_LOGGER: Final = logging.getLogger(__name__)
_RES_PREFIX: Final = "res:"
_DEFAULT_LOOKBACK: Final = "P1D"


class DeploymentHistoryMemberSource:
    """Supply an incident's antecedent changes from deployment history.

    ``lookup`` maps an opaque incident id to its :class:`Incident` record
    (a fork wraps ``IncidentRegistry.get``); ``lookback`` is the ISO-8601
    duration window handed to the deployment provider (how far back to
    search for an antecedent change).
    """

    def __init__(
        self,
        *,
        lookup: Callable[[str], Incident | None],
        deployment_history: DeploymentHistoryProvider,
        lookback: str = _DEFAULT_LOOKBACK,
    ) -> None:
        if not lookback.strip():
            raise ValueError("DeploymentHistoryMemberSource.lookback MUST be non-empty")
        self._lookup: Final = lookup
        self._deployment_history: Final = deployment_history
        self._lookback: Final = lookback

    async def members(self, *, incident_id: str) -> tuple[CorrelatedEvent, ...]:
        """Return the incident's deployment/change events (``is_change=True``).

        Never raises: an unknown incident, a resource-less incident, or a
        failing / partial deployment query yields an empty or partial set.
        """
        incident = self._lookup(incident_id)
        if incident is None:
            return ()
        resource_refs = tuple(
            key[len(_RES_PREFIX) :]
            for key in incident.correlation_keys
            if key.startswith(_RES_PREFIX) and len(key) > len(_RES_PREFIX)
        )
        if not resource_refs:
            return ()

        seen: dict[str, CorrelatedEvent] = {}
        for ref in resource_refs:
            try:
                result = await self._deployment_history.query_deployments(
                    window=self._lookback, resource_ref=ref
                )
            except DeploymentHistoryError:
                # Best-effort: a failing leg contributes no changes but
                # never blocks the control decision.
                _LOGGER.warning(
                    "deployment_member_source_query_failed",
                    extra={"incident_id": incident_id, "resource_ref": ref},
                    exc_info=True,
                )
                continue
            for record in result.records:
                at = _parse_timestamp(record.timestamp)
                if at is None:
                    continue
                event = CorrelatedEvent(
                    event_id=record.deployment_ref,
                    at=at,
                    resource_ref=record.resource_refs[0] if record.resource_refs else ref,
                    is_change=True,
                    change_kind="deploy",
                )
                seen.setdefault(event.event_id, event)
        return tuple(seen.values())


def _parse_timestamp(raw: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, or ``None`` when unparseable.

    Best-effort: a malformed timestamp drops that one record rather than
    failing the whole member set (the source never blocks the loop).
    """
    if not raw:
        return None
    text = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


__all__ = ["DeploymentHistoryMemberSource"]
