"""Routes each event to T0 | T1 | T2 by computed confidence.

P1 W-3 Step 3f scope
--------------------

The router selects the lowest tier with enough information to decide:

- **T0** when the event's derived ``resource_type`` matches a rule in
  the loaded :class:`RuleIndex`.
- **T1** when the resource type is known but no deterministic rule matches.
- **abstain** only when the resource type is missing and no safe tier input
    can be constructed.

The router does NOT invoke the tier; it returns a
:class:`RoutingDecision` that the caller (:class:`ControlLoop`) acts on.
This keeps the router a pure function of the event + index.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.shared.contracts.models import Event


class RoutingTier(StrEnum):
    """Trust-router outcome."""

    T0 = "t0"
    T1 = "t1"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """The trust-router's verdict for one event.

    ``resource_type`` is the CSP-neutral type the router derived from
    the event (via payload key or resource_ref). ``candidate_rule_ids``
    is what T0 would evaluate - precomputed so the caller can log it
    even when the tier itself abstains.
    """

    tier: RoutingTier
    resource_type: str | None
    candidate_rule_ids: tuple[str, ...] = ()
    reason: str | None = None


class TrustRouter:
    """Compute a :class:`RoutingDecision` for one event."""

    def __init__(self, *, index: RuleIndex) -> None:
        self._index = index

    def route(self, event: Event) -> RoutingDecision:
        """Return the P1 routing decision.

        Derivation of ``resource_type``:

        1. ``event.payload['resource'].get('type')`` - the ingested
           inventory adapter's Resource record embedded in the event.
        2. ``event.payload.get('resource_type')`` - a legacy flat form.
        3. Otherwise abstain - the router refuses to guess.
        """
        resource_type = _extract_resource_type(event.payload)
        if resource_type is None:
            return RoutingDecision(
                tier=RoutingTier.ABSTAIN,
                resource_type=None,
                candidate_rule_ids=(),
                reason="event_payload_missing_resource_type",
            )

        candidates = self._index.rules_for_type(resource_type)
        if not candidates:
            return RoutingDecision(
                tier=RoutingTier.T1,
                resource_type=resource_type,
                candidate_rule_ids=(),
                reason="no_rule_matches_resource_type",
            )

        return RoutingDecision(
            tier=RoutingTier.T0,
            resource_type=resource_type,
            candidate_rule_ids=tuple(r.id for r in candidates),
        )


def _extract_resource_type(payload: dict[str, Any]) -> str | None:
    resource = payload.get("resource")
    if isinstance(resource, dict):
        rt = _normalized_resource_type(resource.get("type"))
        if rt is not None:
            return rt
    return _normalized_resource_type(payload.get("resource_type"))


def _normalized_resource_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = ["RoutingDecision", "RoutingTier", "TrustRouter"]
