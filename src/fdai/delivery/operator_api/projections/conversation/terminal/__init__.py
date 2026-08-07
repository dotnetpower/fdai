"""Terminal projections for Operator conversations.

Responsibility:
Assemble bounded request-local terminal context and payload projections.

Boundary:
Accept verified conversation evidence and return transport-neutral values. HTTP
and SSE sequencing, authentication, cancellation, history, and delivery stay
route-owned.

Authority and state:
Read-only and request-local. This package cannot approve, execute, persist
conversation history, or receive an executor identity.

Dependencies:
Application conversation contracts and sibling read projections. Route modules
are outside this dependency boundary.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from fdai.delivery.operator_api.projections.conversation.terminal.llm_usage import (
    llm_usage_evidence_refs,
    parse_llm_usage_analysis_context,
    render_llm_usage_answer,
    response_llm_usage_analysis_context,
    response_llm_usage_chart_artifact,
)
from fdai.delivery.operator_api.projections.conversation.terminal.payload import (
    TurnTimingRecorder,
    TurnTimingStatus,
    TurnTimingToken,
    assurance_policy_summary,
    build_done_payload,
    public_intent_graph_evidence,
    response_incident_candidates,
    verification_events,
)
from fdai.delivery.operator_api.projections.conversation.terminal.resource_context import (
    ambiguous_resource_candidates,
    ordinal_inventory_arguments,
    parse_resource_result_context,
    response_resource_result_context,
)
from fdai.delivery.operator_api.projections.conversation.terminal.source_failure import (
    parse_source_failure_context,
    response_source_failure_context,
    source_failure_evidence_refs,
)

__all__ = [
    "TurnTimingRecorder",
    "TurnTimingStatus",
    "TurnTimingToken",
    "ambiguous_resource_candidates",
    "assurance_policy_summary",
    "build_done_payload",
    "llm_usage_evidence_refs",
    "ordinal_inventory_arguments",
    "parse_llm_usage_analysis_context",
    "parse_resource_result_context",
    "parse_source_failure_context",
    "public_intent_graph_evidence",
    "render_llm_usage_answer",
    "response_llm_usage_analysis_context",
    "response_llm_usage_chart_artifact",
    "response_incident_candidates",
    "response_resource_result_context",
    "response_source_failure_context",
    "source_failure_evidence_refs",
    "verification_events",
]
