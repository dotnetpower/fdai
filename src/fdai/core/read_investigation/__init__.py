"""Bounded, provider-neutral read-investigation planning."""

from fdai.core.read_investigation.catalog import (
    READ_TOOL_SPECS,
    LatencyClass,
    ReadToolSpec,
    read_tool_spec,
)
from fdai.core.read_investigation.execution_policy import (
    InvestigationExecutionPolicy,
    ReadInvestigationExecutionMode,
)
from fdai.core.read_investigation.latency import (
    PlanLatencyEstimate,
    ReadLatencyProfile,
    estimate_parallel_p95,
    estimate_plan_latency,
    estimate_sequential_p95,
    latency_profile,
)
from fdai.core.read_investigation.models import (
    ReadInvestigationBudget,
    ReadInvestigationOutcome,
    ReadInvestigationPlan,
    ReadInvestigationRequest,
    ReadInvestigationResult,
    ReadInvestigationStep,
)
from fdai.core.read_investigation.planner import plan_read_investigation
from fdai.core.read_investigation.progress import ReadInvestigationProgressKind
from fdai.core.read_investigation.routing import (
    classify_read_investigation_intent,
    resource_name_from_question,
)
from fdai.core.read_investigation.service import ReadInvestigationService

__all__ = [
    "READ_TOOL_SPECS",
    "LatencyClass",
    "InvestigationExecutionPolicy",
    "PlanLatencyEstimate",
    "ReadInvestigationExecutionMode",
    "ReadInvestigationBudget",
    "ReadInvestigationOutcome",
    "ReadInvestigationPlan",
    "ReadInvestigationProgressKind",
    "ReadInvestigationRequest",
    "ReadInvestigationResult",
    "ReadInvestigationService",
    "ReadInvestigationStep",
    "ReadLatencyProfile",
    "ReadToolSpec",
    "classify_read_investigation_intent",
    "estimate_parallel_p95",
    "estimate_plan_latency",
    "estimate_sequential_p95",
    "latency_profile",
    "plan_read_investigation",
    "read_tool_spec",
    "resource_name_from_question",
]
