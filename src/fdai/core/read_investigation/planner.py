"""Pure exact-resolution-first planning for read investigations."""

from __future__ import annotations

from fdai.core.read_investigation.catalog import read_tool_spec
from fdai.core.read_investigation.intent_spec import read_investigation_intent_spec
from fdai.core.read_investigation.models import (
    ReadInvestigationPlan,
    ReadInvestigationRequest,
    ReadInvestigationStep,
)
from fdai.shared.providers.read_investigation import ReadInvestigationIntent, ReadToolId


def plan_read_investigation(request: ReadInvestigationRequest) -> ReadInvestigationPlan:
    requested = (
        request.requested_evidence or read_investigation_intent_spec(request.intent).default_tools
    )
    if request.explicit_deep and request.intent not in {
        ReadInvestigationIntent.NETWORK_SECURITY,
        ReadInvestigationIntent.NETWORK_PEERING,
    }:
        requested = (
            ReadToolId.GET_RESOURCE_STATE,
            ReadToolId.QUERY_RESOURCE_ACTIVITY,
            ReadToolId.QUERY_RESOURCE_HEALTH,
            ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
        )
    tool_ids = (ReadToolId.RESOLVE_RESOURCE, *requested)
    steps = tuple(
        _step(tool_id, request=request, fallback_rank=index if len(requested) > 1 else 0)
        for index, tool_id in enumerate(tool_ids)
    )
    return ReadInvestigationPlan(request=request, steps=steps)


def _step(
    tool_id: ReadToolId,
    *,
    request: ReadInvestigationRequest,
    fallback_rank: int,
) -> ReadInvestigationStep:
    spec = read_tool_spec(tool_id)
    return ReadInvestigationStep(
        tool_id=tool_id,
        timeout_seconds=min(spec.timeout_seconds, float(request.budget.max_wall_seconds)),
        max_results=min(spec.max_results, request.budget.max_results),
        max_output_bytes=min(spec.max_output_bytes, request.budget.max_output_bytes),
        fallback_rank=fallback_rank,
    )


__all__ = ["plan_read_investigation"]
