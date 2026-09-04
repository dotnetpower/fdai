"""Build verified semantic frames and resolve server-owned clarification context.

This module acts as a compatibility facade exposing split sub-modules.
"""

from __future__ import annotations

# Import all from builders
from .semantic_planning_frame_builders import (
    build_bound_incident_metric_comparison_frame,
    build_business_capability_mapping_frame,
    build_configuration_drift_clarification,
    build_historical_topology_clarification,
    build_network_path_clarification,
    build_operating_objectives_frame,
    build_resource_current_state_clarification,
    build_resource_event_history_clarification,
    build_rule_state_frame,
    build_service_agent_ownership_frame,
    build_service_current_health_clarification,
    build_unbound_change_correlation_frame,
)
from .semantic_planning_frame_builders import (
    build_ontology_release_health_frame as build_ontology_release_health_frame,
)
from .semantic_planning_frame_builders import (
    build_ontology_trace_frame as build_ontology_trace_frame,
)
from .semantic_planning_frame_builders import (
    build_private_connectivity_clarification as build_private_connectivity_clarification,
)
from .semantic_planning_frame_builders import (
    build_recovery_plan_clarification as build_recovery_plan_clarification,
)
from .semantic_planning_frame_builders import (
    build_resource_activity_clarification as build_resource_activity_clarification,
)
from .semantic_planning_frame_builders import (
    build_resource_classification_frame as build_resource_classification_frame,
)
from .semantic_planning_frame_builders import (
    build_resource_relationship_clarification as build_resource_relationship_clarification,
)

# Import from core
from .semantic_planning_frame_core import build_semantic_frame

# Import all from normalization
from .semantic_planning_frame_normalization import (
    CHANGE_ACTIVITY_COMPARISON_MEASURE as CHANGE_ACTIVITY_COMPARISON_MEASURE,
)
from .semantic_planning_frame_normalization import (
    build_document_draft_frame,
    build_named_resource_group_membership_frame,
    canonicalize_semantic_judgment_frame_proposal,
    normalize_action_draft_temporal_scope,
    normalize_historical_topology_clarification,
    normalize_named_resource_group_membership,
    normalize_network_path_clarification,
    normalize_operating_objectives_frame,
    resolve_bound_incident_action_subject,
    resolve_default_action_draft_subject,
)
from .semantic_planning_frame_normalization import (
    normalize_ontology_trace_frame as normalize_ontology_trace_frame,
)
from .semantic_planning_frame_normalization import (
    normalize_resource_classification_frame as normalize_resource_classification_frame,
)
from .semantic_planning_frame_normalization import (
    resolve_semantic_judgment_action_draft as resolve_semantic_judgment_action_draft,
)
from .semantic_planning_frame_normalization import (
    resolve_semantic_judgment_bound_read as resolve_semantic_judgment_bound_read,
)

# Import all from queries
from .semantic_planning_frame_queries import (
    is_completed_change_outcome_frame,
    is_configuration_drift_evidence_frame,
    is_historical_topology_clarification_frame,
    is_incident_triage_frame,
    is_network_path_clarification_frame,
    resolve_incident_reference,
    resolve_principal_scope_evidence_subject,
    resource_target_clarification,
)
from .semantic_planning_frame_queries import (
    is_ontology_trace_frame as is_ontology_trace_frame,
)
from .semantic_planning_frame_queries import (
    is_resource_classification_frame as is_resource_classification_frame,
)

__all__ = [
    "build_bound_incident_metric_comparison_frame",
    "build_business_capability_mapping_frame",
    "build_document_draft_frame",
    "build_configuration_drift_clarification",
    "build_historical_topology_clarification",
    "build_network_path_clarification",
    "build_named_resource_group_membership_frame",
    "build_ontology_release_health_frame",
    "build_ontology_trace_frame",
    "build_operating_objectives_frame",
    "build_private_connectivity_clarification",
    "build_recovery_plan_clarification",
    "build_resource_current_state_clarification",
    "build_resource_event_history_clarification",
    "build_resource_activity_clarification",
    "build_resource_classification_frame",
    "build_resource_relationship_clarification",
    "build_rule_state_frame",
    "build_service_agent_ownership_frame",
    "build_service_current_health_clarification",
    "build_unbound_change_correlation_frame",
    "build_semantic_frame",
    "canonicalize_semantic_judgment_frame_proposal",
    "is_completed_change_outcome_frame",
    "is_configuration_drift_evidence_frame",
    "is_incident_triage_frame",
    "is_historical_topology_clarification_frame",
    "is_network_path_clarification_frame",
    "is_ontology_trace_frame",
    "is_resource_classification_frame",
    "normalize_action_draft_temporal_scope",
    "normalize_named_resource_group_membership",
    "normalize_ontology_trace_frame",
    "normalize_network_path_clarification",
    "normalize_operating_objectives_frame",
    "normalize_historical_topology_clarification",
    "normalize_resource_classification_frame",
    "resource_target_clarification",
    "resolve_bound_incident_action_subject",
    "resolve_default_action_draft_subject",
    "resolve_incident_reference",
    "resolve_principal_scope_evidence_subject",
    "resolve_semantic_judgment_action_draft",
    "resolve_semantic_judgment_bound_read",
]
