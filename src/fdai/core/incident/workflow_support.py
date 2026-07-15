"""Pure helper functions for incident workflow authorization and anchors."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import NAMESPACE_URL, UUID, uuid5

from .lifecycle import IncidentOperatorPrincipal, IncidentWorkflowForbiddenError

_CREATE_FLOOR = "contributor"
_ROLE_RANK = {"reader": 0, "contributor": 1, "approver": 2, "owner": 3}


def require_incident_operator(principal: IncidentOperatorPrincipal) -> None:
    role_value = str(getattr(principal.role, "value", principal.role)).lower()
    if _ROLE_RANK.get(role_value, -1) < _ROLE_RANK[_CREATE_FLOOR]:
        raise IncidentWorkflowForbiddenError(
            f"incident workflow requires role>={_CREATE_FLOOR}; principal role={role_value}"
        )


def manual_incident_event_id(correlation_keys: Iterable[str]) -> UUID:
    canonical = "|".join(sorted(set(correlation_keys)))
    return uuid5(NAMESPACE_URL, "fdai.incident.manual://" + canonical)


__all__ = ["manual_incident_event_id", "require_incident_operator"]
