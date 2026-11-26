"""Semantic progress vocabulary for read investigations."""

from __future__ import annotations

from enum import StrEnum

from fdai.shared.providers.read_investigation import ReadToolId


class ReadInvestigationProgressKind(StrEnum):
    PLANNED = "investigation.planned"
    RESOURCE_RESOLVING = "resource.resolving"
    RESOURCE_RESOLVED = "resource.resolved"
    RESOURCE_NOT_FOUND = "resource.not-found"
    RESOURCE_AMBIGUOUS = "resource.ambiguous"
    RESOURCE_UNAVAILABLE = "resource.unavailable"
    STATE_QUERYING = "state.querying"
    STATE_COMPLETED = "state.completed"
    STATE_UNAVAILABLE = "state.unavailable"
    ACTIVITY_QUERYING = "activity.querying"
    ACTIVITY_COMPLETED = "activity.completed"
    ACTIVITY_UNAVAILABLE = "activity.unavailable"
    HEALTH_QUERYING = "health.querying"
    HEALTH_COMPLETED = "health.completed"
    HEALTH_UNAVAILABLE = "health.unavailable"
    GUEST_QUERYING = "guest-log.querying"
    GUEST_COMPLETED = "guest-log.completed"
    GUEST_UNAVAILABLE = "guest-log.unavailable"
    NETWORK_SECURITY_QUERYING = "network-security.querying"
    NETWORK_SECURITY_COMPLETED = "network-security.completed"
    NETWORK_SECURITY_UNAVAILABLE = "network-security.unavailable"
    NETWORK_PEERING_QUERYING = "network-peering.querying"
    NETWORK_PEERING_COMPLETED = "network-peering.completed"
    NETWORK_PEERING_UNAVAILABLE = "network-peering.unavailable"
    EVIDENCE_CORRELATING = "evidence.correlating"
    DELAYED = "investigation.delayed"
    COMPLETED = "investigation.completed"


_QUERYING = {
    ReadToolId.GET_RESOURCE_STATE: ReadInvestigationProgressKind.STATE_QUERYING,
    ReadToolId.QUERY_RESOURCE_ACTIVITY: ReadInvestigationProgressKind.ACTIVITY_QUERYING,
    ReadToolId.QUERY_RESOURCE_HEALTH: ReadInvestigationProgressKind.HEALTH_QUERYING,
    ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS: ReadInvestigationProgressKind.GUEST_QUERYING,
    ReadToolId.QUERY_NETWORK_SECURITY: ReadInvestigationProgressKind.NETWORK_SECURITY_QUERYING,
    ReadToolId.QUERY_NETWORK_PEERINGS: ReadInvestigationProgressKind.NETWORK_PEERING_QUERYING,
}
_COMPLETED = {
    ReadToolId.GET_RESOURCE_STATE: ReadInvestigationProgressKind.STATE_COMPLETED,
    ReadToolId.QUERY_RESOURCE_ACTIVITY: ReadInvestigationProgressKind.ACTIVITY_COMPLETED,
    ReadToolId.QUERY_RESOURCE_HEALTH: ReadInvestigationProgressKind.HEALTH_COMPLETED,
    ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS: ReadInvestigationProgressKind.GUEST_COMPLETED,
    ReadToolId.QUERY_NETWORK_SECURITY: ReadInvestigationProgressKind.NETWORK_SECURITY_COMPLETED,
    ReadToolId.QUERY_NETWORK_PEERINGS: ReadInvestigationProgressKind.NETWORK_PEERING_COMPLETED,
}
_UNAVAILABLE = {
    ReadToolId.GET_RESOURCE_STATE: ReadInvestigationProgressKind.STATE_UNAVAILABLE,
    ReadToolId.QUERY_RESOURCE_ACTIVITY: ReadInvestigationProgressKind.ACTIVITY_UNAVAILABLE,
    ReadToolId.QUERY_RESOURCE_HEALTH: ReadInvestigationProgressKind.HEALTH_UNAVAILABLE,
    ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS: ReadInvestigationProgressKind.GUEST_UNAVAILABLE,
    ReadToolId.QUERY_NETWORK_SECURITY: ReadInvestigationProgressKind.NETWORK_SECURITY_UNAVAILABLE,
    ReadToolId.QUERY_NETWORK_PEERINGS: ReadInvestigationProgressKind.NETWORK_PEERING_UNAVAILABLE,
}


def querying_progress(tool_id: ReadToolId) -> ReadInvestigationProgressKind:
    return _QUERYING[tool_id]


def completed_progress(tool_id: ReadToolId) -> ReadInvestigationProgressKind:
    return _COMPLETED[tool_id]


def unavailable_progress(tool_id: ReadToolId) -> ReadInvestigationProgressKind:
    return _UNAVAILABLE[tool_id]


__all__ = [
    "ReadInvestigationProgressKind",
    "completed_progress",
    "querying_progress",
    "unavailable_progress",
]
