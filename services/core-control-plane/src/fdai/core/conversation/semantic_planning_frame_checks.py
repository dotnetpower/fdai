"""Deterministic semantic frame checks and normalization helpers.

This module preserves ordering and outcomes from SemanticPlanningService while
keeping planning orchestration in separate modules.
"""

from __future__ import annotations

from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation

from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .conversation_preflight import (
    operational_target_is_generic,
    operational_time_is_past_hour,
)
from .semantic_investigation import VerifiedInvestigationIntent
from .semantic_operational_summary_planning import build_function_backed_summary_frame
from .semantic_planning_frame import (
    build_bound_incident_metric_comparison_frame as _build_bound_incident_metric_comparison_frame,
)
from .semantic_planning_frame import (
    build_business_capability_mapping_frame as _build_business_capability_mapping_frame,
)
from .semantic_planning_frame import (
    build_configuration_drift_clarification as _build_configuration_drift_clarification,
)
from .semantic_planning_frame import (
    build_document_draft_frame as _build_document_draft_frame,
)
from .semantic_planning_frame import (
    build_historical_topology_clarification as _build_historical_topology_clarification,
)
from .semantic_planning_frame import (
    build_named_resource_group_membership_frame as _build_named_resource_group_membership_frame,
)
from .semantic_planning_frame import (
    build_network_path_clarification as _build_network_path_clarification,
)
from .semantic_planning_frame import (
    build_ontology_release_health_frame as _build_ontology_release_health_frame,
)
from .semantic_planning_frame import (
    build_ontology_trace_frame as _build_ontology_trace_frame,
)
from .semantic_planning_frame import (
    build_operating_objectives_frame as _build_operating_objectives_frame,
)
from .semantic_planning_frame import (
    build_private_connectivity_clarification as _build_private_connectivity_clarification,
)
from .semantic_planning_frame import (
    build_recovery_plan_clarification as _build_recovery_plan_clarification,
)
from .semantic_planning_frame import (
    build_resource_activity_clarification as _build_resource_activity_clarification,
)
from .semantic_planning_frame import (
    build_resource_classification_frame as _build_resource_classification_frame,
)
from .semantic_planning_frame import (
    build_resource_current_state_clarification as _build_resource_current_state_clarification,
)
from .semantic_planning_frame import (
    build_resource_event_history_clarification as _build_resource_event_history_clarification,
)
from .semantic_planning_frame import (
    build_resource_relationship_clarification as _build_resource_relationship_clarification,
)
from .semantic_planning_frame import build_rule_state_frame as _build_rule_state_frame
from .semantic_planning_frame import (
    build_service_agent_ownership_frame as _build_service_agent_ownership_frame,
)
from .semantic_planning_frame import (
    build_service_current_health_clarification as _build_service_current_health_clarification,
)
from .semantic_planning_frame import (
    build_unbound_change_correlation_frame as _build_unbound_change_correlation_frame,
)
from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_frame_gate import (
    _gateway_target_shape_issue,
    _normalize_gateway_diagnostic_time_scope,
    normalize_and_gate_frame,
)
from .semantic_planning_frame_normalization import (
    build_inventory_document_frame as _build_inventory_document_frame,
)
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
)
from .semantic_planning_support import _clarification, _outcome
from .semantic_resource_configuration_planning import build_resource_configuration_frame


def deterministic_pre_frame_outcome(
    *,
    judgment: Any,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    manifest_digest: str,
    bound_incident: bool,
) -> SemanticPlanningOutcome | None:
    """Return deterministic short-circuit outcomes before model frame proposal."""

    if (
        judgment is not None
        and judgment.primary_intent
        in {"query.gateway_diagnostic_evidence", "query.resource_configuration_changes"}
        and any(
            target.kind in {"resource", "resource_id"}
            and not operational_target_is_generic(target.value)
            for target in judgment.targets
        )
        and any(
            target.kind == "time_range"
            and target.canonical_value == "duration.PT1H"
            and not operational_time_is_past_hour(target.value)
            for target in judgment.targets
        )
    ):
        output_shape = (
            SemanticOutputShape.GATEWAY_DIAGNOSTIC_EVIDENCE
            if judgment.primary_intent == "query.gateway_diagnostic_evidence"
            else SemanticOutputShape.RESOURCE_CONFIGURATION_CHANGES
        )
        proposal = SemanticFrameProposal(
            operation=SemanticOperation.COMPARE,
            subject_constraints=("Resource",),
            measure_concepts=(),
            temporal_scope={},
            output_shape=output_shape,
            evidence_requirements=(),
            unresolved_terms=("temporal_scope",),
            clarification_requirements=(ClarificationRequirement.TEMPORAL_SCOPE,),
            clarification=_clarification(("temporal_scope",)),
            investigation=None,
            confidence=judgment.confidence,
        )
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=build_semantic_frame(proposal, utterance=utterance, context=context),
            clarification=proposal.clarification,
        )
    gateway_shape_issue = (
        _gateway_target_shape_issue(judgment)
        if judgment is not None
        and judgment.primary_intent == "query.gateway_diagnostic_evidence"
        and any(
            target.kind in {"resource", "resource_id"}
            and not operational_target_is_generic(target.value)
            for target in judgment.targets
        )
        else None
    )
    if gateway_shape_issue is not None:
        requirement = (
            ClarificationRequirement.TEMPORAL_SCOPE
            if gateway_shape_issue == "temporal_scope"
            else ClarificationRequirement.SUBJECT
        )
        proposal = SemanticFrameProposal(
            operation=SemanticOperation.COMPARE,
            subject_constraints=("Resource",),
            measure_concepts=(),
            temporal_scope={},
            output_shape=SemanticOutputShape.GATEWAY_DIAGNOSTIC_EVIDENCE,
            evidence_requirements=(),
            unresolved_terms=(gateway_shape_issue,),
            clarification_requirements=(requirement,),
            clarification=_clarification((gateway_shape_issue,)),
            investigation=None,
            confidence=judgment.confidence,
        )
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=build_semantic_frame(proposal, utterance=utterance, context=context),
            clarification=proposal.clarification,
        )
    if (
        judgment is not None
        and judgment.primary_intent == "query.resource_configuration_changes"
        and any(
            target.kind in {"resource", "resource_id"}
            and not operational_target_is_generic(target.value)
            for target in judgment.targets
        )
        and not any(
            target.kind == "time_range"
            and target.canonical_value == "duration.PT1H"
            and operational_time_is_past_hour(target.value)
            for target in judgment.targets
        )
    ):
        proposal = SemanticFrameProposal(
            operation=SemanticOperation.COMPARE,
            subject_constraints=("Resource",),
            measure_concepts=(),
            temporal_scope={},
            output_shape=SemanticOutputShape.RESOURCE_CONFIGURATION_CHANGES,
            evidence_requirements=(),
            unresolved_terms=("temporal_scope",),
            clarification_requirements=(ClarificationRequirement.TEMPORAL_SCOPE,),
            clarification=_clarification(("temporal_scope",)),
            investigation=None,
            confidence=judgment.confidence,
        )
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=build_semantic_frame(proposal, utterance=utterance, context=context),
            clarification=proposal.clarification,
        )
    if (
        judgment is not None
        and judgment.primary_intent
        in {"query.gateway_diagnostic_evidence", "query.resource_configuration_changes"}
        and judgment.action_posture == "advise_only"
        and not any(
            target.kind in {"resource", "resource_id"}
            and not operational_target_is_generic(target.value)
            for target in judgment.targets
        )
    ):
        output_shape = (
            SemanticOutputShape.GATEWAY_DIAGNOSTIC_EVIDENCE
            if judgment.primary_intent == "query.gateway_diagnostic_evidence"
            else SemanticOutputShape.RESOURCE_CONFIGURATION_CHANGES
        )
        proposal = SemanticFrameProposal(
            operation=SemanticOperation.COMPARE,
            subject_constraints=("Resource",),
            measure_concepts=(),
            temporal_scope={},
            output_shape=output_shape,
            evidence_requirements=(),
            unresolved_terms=("resource_identity",),
            clarification_requirements=(ClarificationRequirement.RESOURCE_IDENTITY,),
            clarification=_clarification(("resource_identity",)),
            investigation=None,
            confidence=judgment.confidence,
        )
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=build_semantic_frame(proposal, utterance=utterance, context=context),
            clarification=proposal.clarification,
        )
    incident_metric_comparison = _build_bound_incident_metric_comparison_frame(
        judgment,
        bound_incident=bound_incident,
        utterance=utterance,
        context=context,
    )
    if incident_metric_comparison is not None:
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_incident_metric_comparison_unavailable",
            manifest_digest=manifest_digest,
            frame=incident_metric_comparison,
        )
    change_correlation = _build_unbound_change_correlation_frame(
        judgment,
        bound_incident=bound_incident,
        utterance=utterance,
        context=context,
    )
    if change_correlation is not None:
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_change_correlation_incident_binding_unavailable",
            manifest_digest=manifest_digest,
            frame=change_correlation,
        )
    network_path_clarification = _build_network_path_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if network_path_clarification is not None:
        network_proposal, network_frame = network_path_clarification
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=network_frame,
            clarification=network_proposal.clarification,
        )
    private_connectivity_clarification = _build_private_connectivity_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if private_connectivity_clarification is not None:
        connectivity_proposal, connectivity_frame = private_connectivity_clarification
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=connectivity_frame,
            clarification=connectivity_proposal.clarification,
        )
    recovery_plan_clarification = _build_recovery_plan_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if recovery_plan_clarification is not None:
        recovery_proposal, recovery_frame = recovery_plan_clarification
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=recovery_frame,
            clarification=recovery_proposal.clarification,
        )
    resource_relationship_clarification = _build_resource_relationship_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if resource_relationship_clarification is not None:
        relationship_proposal, relationship_frame = resource_relationship_clarification
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=relationship_frame,
            clarification=relationship_proposal.clarification,
        )
    resource_current_state = _build_resource_current_state_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if resource_current_state is not None:
        current_proposal, current_frame = resource_current_state
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=current_frame,
            clarification=current_proposal.clarification,
        )
    configuration_drift = _build_configuration_drift_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if configuration_drift is not None:
        drift_proposal, drift_frame = configuration_drift
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=drift_frame,
            clarification=drift_proposal.clarification,
        )
    service_current_health = _build_service_current_health_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if service_current_health is not None:
        service_proposal, service_frame = service_current_health
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=service_frame,
            clarification=service_proposal.clarification,
        )
    business_capability_mapping = _build_business_capability_mapping_frame(
        judgment,
        utterance=utterance,
        context=context,
    )
    if business_capability_mapping is not None:
        return _outcome(
            SemanticPlanningDisposition.UNSUPPORTED,
            "semantic_business_capability_mapping_unsupported",
            manifest_digest=manifest_digest,
            frame=business_capability_mapping,
        )
    rule_state = _build_rule_state_frame(
        judgment,
        utterance=utterance,
        context=context,
    )
    if rule_state is not None:
        return _outcome(
            SemanticPlanningDisposition.UNSUPPORTED,
            "semantic_rule_state_unsupported",
            manifest_digest=manifest_digest,
            frame=rule_state,
        )
    resource_classification = _build_resource_classification_frame(
        judgment,
        utterance=utterance,
        context=context,
    )
    if resource_classification is not None:
        return _outcome(
            SemanticPlanningDisposition.UNSUPPORTED,
            "semantic_resource_classification_unsupported",
            manifest_digest=manifest_digest,
            frame=resource_classification,
        )
    historical_topology_clarification = _build_historical_topology_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if historical_topology_clarification is not None:
        historical_proposal, historical_frame = historical_topology_clarification
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=historical_frame,
            clarification=historical_proposal.clarification,
        )
    resource_activity_clarification = _build_resource_activity_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if resource_activity_clarification is not None:
        activity_proposal, activity_frame = resource_activity_clarification
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=activity_frame,
            clarification=activity_proposal.clarification,
        )
    resource_event_history = _build_resource_event_history_clarification(
        judgment,
        utterance=utterance,
        context=context,
    )
    if resource_event_history is not None:
        event_proposal, event_frame = resource_event_history
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=event_frame,
            clarification=event_proposal.clarification,
        )
    ontology_release_health = _build_ontology_release_health_frame(
        judgment,
        utterance=utterance,
        context=context,
    )
    if ontology_release_health is not None:
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_ontology_release_evidence_health_unavailable",
            manifest_digest=manifest_digest,
            frame=ontology_release_health,
        )
    operating_objectives = _build_operating_objectives_frame(
        judgment,
        utterance=utterance,
        context=context,
    )
    if operating_objectives is not None:
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_operating_objectives_unavailable",
            manifest_digest=manifest_digest,
            frame=operating_objectives,
        )
    return None


def deterministic_pre_frame_selection(
    *,
    judgment: Any,
    judgment_accepted: bool = False,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    manifest_descriptors: tuple[dict[str, Any], ...] | None = None,
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
) -> tuple[SemanticFrameProposal, Any, VerifiedInvestigationIntent | None] | None:
    """Build accepted typed function or relationship frames before model proposal."""

    inventory_document = _build_inventory_document_frame(
        judgment=judgment if judgment_accepted else None,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    if inventory_document is not None:
        proposal, frame = inventory_document
        return proposal, frame, None
    resource_configuration = build_resource_configuration_frame(
        judgment=judgment if judgment_accepted else None,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    if resource_configuration is not None:
        proposal, frame = resource_configuration
        return proposal, frame, None
    document_draft = _build_document_draft_frame(
        judgment=judgment,
        utterance=utterance,
        context=context,
    )
    if document_draft is not None:
        proposal, frame = document_draft
        return proposal, frame, None
    named_resource_group = _build_named_resource_group_membership_frame(
        judgment=judgment,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    if named_resource_group is not None:
        proposal, frame = named_resource_group
        return proposal, frame, None
    summary = build_function_backed_summary_frame(
        judgment,
        utterance=utterance,
        context=context,
        descriptors=manifest_descriptors or descriptors,
        inventory_query_language=inventory_query_language,
    )
    if summary is not None:
        proposal, frame = summary
        return proposal, frame, None
    trace_frame = _build_ontology_trace_frame(judgment, utterance=utterance, context=context)
    selected_frame = (
        trace_frame
        if trace_frame is not None
        else _build_service_agent_ownership_frame(
            judgment,
            utterance=utterance,
            context=context,
            descriptors=descriptors,
        )
    )
    if selected_frame is None or judgment is None:
        return None
    proposal = SemanticFrameProposal(
        operation=selected_frame.operation,
        subject_constraints=selected_frame.subject_constraints,
        measure_concepts=selected_frame.measure_concepts,
        temporal_scope=selected_frame.temporal_scope,
        output_shape=SemanticOutputShape(selected_frame.output_shape),
        evidence_requirements=selected_frame.evidence_requirements,
        unresolved_terms=selected_frame.unresolved_terms,
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, selected_frame, None


__all__ = [
    "_normalize_gateway_diagnostic_time_scope",
    "deterministic_pre_frame_outcome",
    "deterministic_pre_frame_selection",
    "normalize_and_gate_frame",
]
