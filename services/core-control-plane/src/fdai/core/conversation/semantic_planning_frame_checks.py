"""Deterministic semantic frame checks and normalization helpers.

This module preserves ordering and outcomes from SemanticPlanningService while
keeping planning orchestration in separate modules.
"""

from __future__ import annotations

from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation

from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .semantic_governed_document_planning import apply_document_evidence_requirement
from .semantic_investigation import VerifiedInvestigationIntent
from .semantic_manifest_planning import normalize_ontology_manifest_count_frame
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
from .semantic_planning_frame import (
    is_completed_change_outcome_frame as _is_completed_change_outcome_frame,
)
from .semantic_planning_frame import (
    is_configuration_drift_evidence_frame as _is_configuration_drift_evidence_frame,
)
from .semantic_planning_frame import (
    is_incident_triage_frame as _is_incident_triage_frame,
)
from .semantic_planning_frame import (
    is_resource_classification_frame as _is_resource_classification_frame,
)
from .semantic_planning_frame import (
    normalize_action_draft_temporal_scope as _normalize_action_draft_temporal_scope,
)
from .semantic_planning_frame import (
    normalize_historical_topology_clarification as _normalize_historical_topology_clarification,
)
from .semantic_planning_frame import (
    normalize_named_resource_group_membership as _normalize_named_resource_group_membership,
)
from .semantic_planning_frame import (
    normalize_network_path_clarification as _normalize_network_path_clarification,
)
from .semantic_planning_frame import (
    normalize_ontology_trace_frame as _normalize_ontology_trace_frame,
)
from .semantic_planning_frame import (
    normalize_operating_objectives_frame as _normalize_operating_objectives_frame,
)
from .semantic_planning_frame import (
    normalize_resource_classification_frame as _normalize_resource_classification_frame,
)
from .semantic_planning_frame import (
    resolve_bound_incident_action_subject as _resolve_bound_incident_action_subject,
)
from .semantic_planning_frame import (
    resolve_default_action_draft_subject as _resolve_default_action_draft_subject,
)
from .semantic_planning_frame import (
    resolve_incident_reference as _resolve_incident_reference,
)
from .semantic_planning_frame import (
    resolve_principal_scope_evidence_subject as _resolve_principal_scope_evidence_subject,
)
from .semantic_planning_frame import (
    resolve_semantic_judgment_action_draft as _resolve_semantic_judgment_action_draft,
)
from .semantic_planning_frame import (
    resolve_semantic_judgment_bound_read as _resolve_semantic_judgment_bound_read,
)
from .semantic_planning_frame import (
    resource_target_clarification as _resource_target_clarification,
)
from .semantic_planning_frame_core import build_semantic_frame
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
from .semantic_target_candidate_planning import (
    normalize_decision_outcome_relationship,
    normalize_operating_relationship_temporal_scope,
    property_filter_has_stated_subject,
    property_filter_omits_stated_relation,
    resolve_resource_target_candidates,
)


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
        and judgment.action_posture == "advise_only"
        and not judgment.ambiguous
        and not judgment.unresolved_terms
        and not any(target.kind in {"resource", "resource_id"} for target in judgment.targets)
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


def normalize_and_gate_frame(
    *,
    proposal: SemanticFrameProposal,
    frame: Any,
    investigation_intent: VerifiedInvestigationIntent | None,
    judgment: Any,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    manifest_digest: str,
    bound_incident: bool,
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> (
    tuple[SemanticFrameProposal, Any, VerifiedInvestigationIntent | None] | SemanticPlanningOutcome
):
    """Apply deterministic frame normalization and early-return gates in order."""

    proposal, frame = _resolve_semantic_judgment_action_draft(
        proposal,
        frame,
        judgment=judgment,
        utterance=utterance,
        context=context,
    )
    if (
        judgment is not None
        and judgment.action_posture == "advise_only"
        and frame.operation is SemanticOperation.ACTION_DRAFT
    ):
        return _outcome(
            SemanticPlanningDisposition.UNSUPPORTED,
            "semantic_action_posture_mismatch",
            manifest_digest=manifest_digest,
            frame=frame,
        )
    proposal, frame = _normalize_named_resource_group_membership(
        proposal,
        frame,
        judgment=judgment,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    proposal, frame = apply_document_evidence_requirement(
        proposal,
        frame,
        judgment=judgment,
        utterance=utterance,
        context=context,
    )
    if property_filter_has_stated_subject(
        proposal,
        utterance=utterance,
        descriptors=descriptors,
    ):
        return proposal, frame, investigation_intent
    proposal, frame = normalize_ontology_manifest_count_frame(
        proposal,
        frame,
        judgment=judgment,
        utterance=utterance,
        context=context,
    )
    proposal, frame = _resolve_semantic_judgment_bound_read(
        proposal,
        frame,
        judgment=judgment,
        bound_incident=bound_incident,
        utterance=utterance,
        context=context,
    )
    if bound_incident:
        proposal, frame = _resolve_incident_reference(
            proposal,
            frame,
            utterance=utterance,
            context=context,
        )
        proposal, frame = _resolve_bound_incident_action_subject(
            proposal,
            frame,
            utterance=utterance,
            context=context,
        )
    proposal, frame = _resolve_default_action_draft_subject(
        proposal,
        frame,
        utterance=utterance,
        context=context,
    )
    proposal, frame = _normalize_action_draft_temporal_scope(
        proposal,
        frame,
        utterance=utterance,
        context=context,
    )
    proposal, frame = _resolve_principal_scope_evidence_subject(
        proposal,
        frame,
        utterance=utterance,
        context=context,
    )
    proposal, frame = _normalize_network_path_clarification(
        proposal,
        frame,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    proposal, frame = _normalize_operating_objectives_frame(
        proposal,
        frame,
        utterance=utterance,
        context=context,
    )
    proposal, frame = _normalize_resource_classification_frame(
        proposal,
        frame,
        utterance=utterance,
        context=context,
    )
    proposal, frame = _normalize_ontology_trace_frame(
        proposal,
        frame,
        judgment=judgment,
        utterance=utterance,
        context=context,
    )
    proposal, frame = _normalize_historical_topology_clarification(
        proposal,
        frame,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    proposal, frame = normalize_decision_outcome_relationship(
        proposal,
        frame,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    proposal, frame = normalize_operating_relationship_temporal_scope(
        proposal,
        frame,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    if property_filter_omits_stated_relation(
        proposal,
        utterance=utterance,
        inventory_query_language=inventory_query_language,
    ):
        korean = any("가" <= character <= "힣" for character in utterance)
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=frame,
            clarification=(
                "FDAI가 이름이나 태그에 포함된 리소스 그룹을 찾을까요, "
                "아니면 FDAI가 관리하는 전체 범위의 리소스 그룹을 볼까요?"
                if korean
                else (
                    "Should I find resource groups whose name or tags contain FDAI, "
                    "or list every resource group in FDAI's managed scope?"
                )
            ),
        )
    proposal, frame = resolve_resource_target_candidates(
        proposal,
        frame,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        inventory_query_language=inventory_query_language,
    )
    proposal, frame = apply_document_evidence_requirement(
        proposal,
        frame,
        judgment=judgment,
        utterance=utterance,
        context=context,
    )
    if frame.output_shape == SemanticOutputShape.RESOURCE_TARGET_CANDIDATES:
        investigation_intent = None
    resource_clarification = _resource_target_clarification(
        frame,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    if resource_clarification is not None:
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=frame,
            clarification=resource_clarification,
        )
    if frame.unresolved_terms:
        clarification = proposal.clarification or _clarification(frame.unresolved_terms)
        return _outcome(
            SemanticPlanningDisposition.CLARIFICATION,
            "semantic_clarification_required",
            manifest_digest=manifest_digest,
            frame=frame,
            clarification=clarification,
        )
    if frame.operation is SemanticOperation.ACTION_DRAFT:
        return _outcome(
            SemanticPlanningDisposition.ACTION_DRAFT,
            "governed_action_draft_required",
            manifest_digest=manifest_digest,
            frame=frame,
        )
    if _is_completed_change_outcome_frame(frame):
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_change_outcome_unavailable",
            manifest_digest=manifest_digest,
            frame=frame,
        )
    if _is_configuration_drift_evidence_frame(frame):
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_configuration_drift_evidence_unavailable",
            manifest_digest=manifest_digest,
            frame=frame,
        )
    if _is_resource_classification_frame(frame):
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_resource_classification_unavailable",
            manifest_digest=manifest_digest,
            frame=frame,
        )
    if _is_incident_triage_frame(frame):
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_incident_triage_unavailable",
            manifest_digest=manifest_digest,
            frame=frame,
        )
    if (
        frame.operation is SemanticOperation.COMPARE
        and frame.output_shape == SemanticOutputShape.INCIDENT_EVIDENCE
        and frame.temporal_scope == {"kind": "historical"}
    ):
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_incident_recurrence_comparison_unavailable",
            manifest_digest=manifest_digest,
            frame=frame,
        )
    if frame.output_shape == SemanticOutputShape.EVIDENCE_VALIDATION:
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_evidence_validation_unavailable",
            manifest_digest=manifest_digest,
            frame=frame,
        )
    return proposal, frame, investigation_intent


__all__ = [
    "deterministic_pre_frame_outcome",
    "deterministic_pre_frame_selection",
    "normalize_and_gate_frame",
]
