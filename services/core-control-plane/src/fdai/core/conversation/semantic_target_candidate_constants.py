"""Typed output and lineage sets used by target-candidate planning."""

from __future__ import annotations

from .semantic_planning_models import ClarificationRequirement, SemanticOutputShape

CANDIDATE_RESOLVABLE_REQUIREMENTS = frozenset(
    {
        ClarificationRequirement.MEASURE,
        ClarificationRequirement.RESOURCE_IDENTITY,
        ClarificationRequirement.SUBJECT,
    }
)
COLLECTION_FILTER_KINDS = frozenset(
    {
        "resource_state_exclusion_filter",
        "resource_state_filter",
        "resource_type_filter",
    }
)
DECISION_OUTCOME_LINEAGE_TYPES = (
    "DecisionCase",
    "ActionOption",
    "ActionRun",
    "ObservedOutcome",
)
TARGET_BOUND_OPERATING_INTENT_TYPES = frozenset(
    {
        "ArchitectureConstraint",
        "ChangeWindow",
        "CostObjective",
        "Ownership",
        "RecoveryObjective",
        "ServiceObjective",
    }
)
TARGET_SCOPED_OUTPUTS = frozenset(
    {
        SemanticOutputShape.CAUSAL_EVIDENCE,
        SemanticOutputShape.INVENTORY_IMPACT,
        SemanticOutputShape.TARGET_ACTIVITY,
        SemanticOutputShape.TARGET_CURRENT_STATE,
        SemanticOutputShape.TARGET_ERROR_ACTIVITY_CORRELATION,
        SemanticOutputShape.TARGET_HEALTH_ASSESSMENT,
        SemanticOutputShape.TARGET_INGRESS_CONFIGURATION,
        SemanticOutputShape.TARGET_RESOURCE_METRIC,
        SemanticOutputShape.TARGET_RESOURCE_METRIC_SERIES,
        SemanticOutputShape.TEMPORAL_COMPARISON,
        SemanticOutputShape.TOPOLOGY_GRAPH,
    }
)

__all__ = [
    "CANDIDATE_RESOLVABLE_REQUIREMENTS",
    "COLLECTION_FILTER_KINDS",
    "DECISION_OUTCOME_LINEAGE_TYPES",
    "TARGET_BOUND_OPERATING_INTENT_TYPES",
    "TARGET_SCOPED_OUTPUTS",
]
