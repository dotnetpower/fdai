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


def detected_incident_event_id(evidence_key: str) -> UUID:
    """Derive the stable member-event id for one grounded detector candidate."""
    normalized = evidence_key.strip()
    if not normalized:
        raise ValueError("detected incident evidence_key MUST be non-empty")
    return uuid5(NAMESPACE_URL, f"fdai.incident.evidence://{normalized}")


def detected_incident_correlation_keys(
    *,
    resource_id: str,
    event_type: str,
    correlation_id: str = "",
) -> tuple[str, ...]:
    """Build bounded keys that separate independent anomaly investigations."""
    resource = resource_id.strip()
    signal = event_type.strip()
    if not resource or not signal:
        raise ValueError("detected incident requires resource_id and event_type")
    keys = [f"resource:{resource}", f"signal:{signal}"]
    correlation = correlation_id.strip()
    if correlation:
        keys.append(f"correlation:{correlation}")
    return tuple(keys)


__all__ = [
    "detected_incident_correlation_keys",
    "detected_incident_event_id",
    "manual_incident_event_id",
    "require_incident_operator",
]
