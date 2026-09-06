"""Normalize semantic frames and apply ordered fail-closed gates."""

from __future__ import annotations

from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation

from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .conversation_preflight import (
    operational_target_is_exact,
    operational_target_is_generic,
    operational_time_is_past_hour,
)
from .semantic_governed_document_planning import apply_document_evidence_requirement
from .semantic_investigation import VerifiedInvestigationIntent
from .semantic_manifest_planning import normalize_ontology_manifest_count_frame
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
from .semantic_planning_models import (
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


def _normalize_gateway_diagnostic_time_scope(
    proposal: SemanticFrameProposal,
    frame: Any,
    *,
    judgment: Any,
    judgment_accepted: bool,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, Any]:
    """Bind an accepted exact gateway diagnostic request to its typed scope."""

    if (
        not judgment_accepted
        or judgment is None
        or judgment.primary_intent != "query.gateway_diagnostic_evidence"
        or proposal.output_shape is not SemanticOutputShape.GATEWAY_DIAGNOSTIC_EVIDENCE
        or _gateway_target_shape_issue(judgment) is not None
        or not any(
            target.kind == "time_range"
            and target.canonical_value == "duration.PT1H"
            and operational_time_is_past_hour(target.value)
            for target in judgment.targets
        )
    ):
        return proposal, frame
    resource_targets = tuple(
        target
        for target in judgment.targets
        if target.kind in {"resource", "resource_id"}
        and not operational_target_is_generic(target.value)
    )
    backend_targets = tuple(
        target
        for target in judgment.targets
        if target.kind in {"backend", "backend_id", "backend_name", "model"}
    )
    if len(resource_targets) != 1 or len(backend_targets) > 1:
        return proposal, frame
    resource = resource_targets[0]
    resource_field = (
        "id" if resource.kind == "resource_id" or resource.value.startswith("/") else "name"
    )
    constraints = ["Resource", f"Resource.{resource_field}={resource.value}"]
    if backend_targets:
        backend = backend_targets[0]
        backend_field = {
            "backend": "id" if backend.value.startswith("/") else "name",
            "backend_id": "id",
            "backend_name": "name",
            "model": "model_name",
        }[backend.kind]
        constraints.append(f"Backend.{backend_field}={backend.value}")
    normalized = proposal.model_copy(
        update={
            "subject_constraints": tuple(constraints),
            "temporal_scope": {"window_seconds": 3_600},
        }
    )
    return normalized, build_semantic_frame(normalized, utterance=utterance, context=context)


def _gateway_target_shape_issue(judgment: Any) -> str | None:
    """Return the first invalid exact-target dimension for gateway diagnostics."""

    allowed = {
        "resource",
        "resource_id",
        "time_range",
        "backend",
        "backend_id",
        "backend_name",
        "model",
    }
    if any(target.kind not in allowed for target in judgment.targets):
        return "subject"
    resources = tuple(
        target for target in judgment.targets if target.kind in {"resource", "resource_id"}
    )
    if len(resources) != 1 or not operational_target_is_exact(resources[0].value):
        return "subject"
    times = tuple(target for target in judgment.targets if target.kind == "time_range")
    if (
        len(times) != 1
        or times[0].canonical_value != "duration.PT1H"
        or not operational_time_is_past_hour(times[0].value)
    ):
        return "temporal_scope"
    backend_targets = tuple(
        target
        for target in judgment.targets
        if target.kind in {"backend", "backend_id", "backend_name", "model"}
    )
    if len(backend_targets) > 1 or (
        backend_targets and not operational_target_is_exact(backend_targets[0].value)
    ):
        return "subject"
    return None


def normalize_and_gate_frame(
    *,
    proposal: SemanticFrameProposal,
    frame: Any,
    investigation_intent: VerifiedInvestigationIntent | None,
    judgment: Any,
    judgment_accepted: bool,
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

    judgment = judgment if judgment_accepted else None
    proposal, frame = _resolve_semantic_judgment_action_draft(
        proposal,
        frame,
        judgment=judgment,
        utterance=utterance,
        context=context,
    )
    proposal, frame = _normalize_gateway_diagnostic_time_scope(
        proposal,
        frame,
        judgment=judgment,
        judgment_accepted=judgment_accepted,
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
