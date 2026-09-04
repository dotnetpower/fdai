"""Normalize action drafts, proposals, and temporal scopes for semantic planning frames."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.core.ontology_platform.resource_event_queries import KUBERNETES_EVENT_FAMILY

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_frame_facets import (
    _facet_affirms_concept,
    _facets_describe_configuration_drift_evidence,
    _facets_describe_historical_topology,
    _facets_describe_incident_triage,
    _facets_describe_operating_objectives,
    _facets_describe_resource_classification,
    _facets_describe_resource_evidence_health,
    _facets_describe_service_relationship_assessment,
    _facets_describe_service_relationship_evidence_gap,
)
from .semantic_planning_investigation_normalization import (
    normalize_bound_latency_recovery as _normalize_bound_latency_recovery,
)
from .semantic_planning_investigation_normalization import (
    normalize_missing_mysql_pressure_investigation as _mysql_pressure_investigation,
)
from .semantic_planning_investigation_normalization import (
    normalize_missing_resource_slowness_investigation as _resource_slowness_investigation,
)
from .semantic_planning_investigation_normalization import (
    normalize_missing_vm_cpu_investigation as _normalize_missing_vm_cpu_investigation,
)
from .semantic_planning_investigation_normalization import (
    normalize_network_application_latency_investigation as _network_latency_investigation,
)
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_target_identity import exact_target_from_constraints

_ACTION_DRAFT_TEMPORAL_SCOPE = {
    "ActionType": {},
    "Change": {"kind": "historical"},
    "Document": {},
    "Incident": {"kind": "current"},
    "RecoveryPlan": {"kind": "current"},
    "Rule": {},
}

normalize_bound_latency_recovery = _normalize_bound_latency_recovery
normalize_missing_mysql_pressure_investigation = _mysql_pressure_investigation
normalize_missing_resource_slowness_investigation = _resource_slowness_investigation
normalize_missing_vm_cpu_investigation = _normalize_missing_vm_cpu_investigation
normalize_network_application_latency_investigation = _network_latency_investigation


def _resolved_proposal(proposal: SemanticFrameProposal, **updates: object) -> SemanticFrameProposal:
    return proposal.model_copy(
        update={
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
            **updates,
        }
    )


def build_document_draft_frame(
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build a no-authority document draft frame from one exact typed judgment."""

    if (
        judgment is None
        or judgment.primary_intent != "create.document"
        or judgment.action_posture != "draft_only"
        or judgment.action_subject != "Document"
        or judgment.targets
        or set(judgment.requested_facets) != {"complete_content", "download"}
        or judgment.ambiguous
        or judgment.unresolved_terms
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.ACTION_DRAFT,
        subject_constraints=("Document",),
        measure_concepts=("complete_content", "download"),
        temporal_scope={},
        output_shape=SemanticOutputShape.ACTION_DRAFT,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def _action_draft_subject_types(constraints: tuple[str, ...]) -> set[str]:
    return {
        constraint.split(":", 1)[0]
        for constraint in constraints
        if constraint.split(":", 1)[0] in _ACTION_DRAFT_TEMPORAL_SCOPE
    }


def resolve_bound_incident_action_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Bind the trusted Incident type to an otherwise subject-empty action draft."""

    if (
        frame.operation is not SemanticOperation.ACTION_DRAFT
        or frame.output_shape != SemanticOutputShape.ACTION_DRAFT
        or _action_draft_subject_types(proposal.subject_constraints)
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={"subject_constraints": ("Incident", *proposal.subject_constraints)}
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def resolve_semantic_judgment_action_draft(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Rebuild a candidate-only action frame from one accepted draft judgment."""

    judgment_facets = (
        {facet.replace("-", "_") for facet in judgment.requested_facets}
        if judgment is not None
        else set()
    )
    trace_axes = all(
        any(_facet_affirms_concept(facet, concept) for facet in judgment_facets)
        for concept in ("resource_type", "signal_type", "action_type", "trace")
    )
    trace_posture = "governed" in judgment_facets or bool(
        {
            "no_current_finding",
            "without_asserting_current_finding",
            "without_current_finding",
        }.intersection(judgment_facets)
    )
    if (
        judgment is not None
        and judgment.action_posture == "advise_only"
        and frame.operation is SemanticOperation.ACTION_DRAFT
        and frame.output_shape == SemanticOutputShape.ACTION_DRAFT
        and set(proposal.subject_constraints)
        == {"ActionType", "ResourceType", "Rule", "SignalType"}
        and trace_axes
        and trace_posture
    ):
        resolved = _resolved_proposal(
            proposal,
            operation=SemanticOperation.SELECT,
            subject_constraints=("ActionType", "ResourceType", "Rule", "SignalType"),
            measure_concepts=tuple(sorted(judgment_facets)),
            temporal_scope={},
            output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    if judgment is None or judgment.action_posture != "draft_only":
        return proposal, frame
    frame_subjects = _action_draft_subject_types(proposal.subject_constraints)
    preserve_frame_subject = (
        frame.operation is SemanticOperation.ACTION_DRAFT
        and frame.output_shape == SemanticOutputShape.ACTION_DRAFT
        and frame_subjects == {judgment.action_subject}
        and not proposal.unresolved_terms
        and not proposal.clarification_requirements
    )
    subject_constraints = (
        proposal.subject_constraints if preserve_frame_subject else (judgment.action_subject,)
    )
    resolved = _resolved_proposal(
        proposal,
        operation=SemanticOperation.ACTION_DRAFT,
        subject_constraints=subject_constraints,
        measure_concepts=(),
        temporal_scope={},
        output_shape=SemanticOutputShape.ACTION_DRAFT,
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def resolve_default_action_draft_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Use ActionType for an action draft with no narrower typed subject."""

    if (
        frame.operation is not SemanticOperation.ACTION_DRAFT
        or frame.output_shape != SemanticOutputShape.ACTION_DRAFT
        or _action_draft_subject_types(proposal.subject_constraints)
        or proposal.subject_constraints
        or proposal.unresolved_terms
        or proposal.clarification_requirements
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={"subject_constraints": ("ActionType", *proposal.subject_constraints)}
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_action_draft_temporal_scope(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Derive an action draft's temporal scope from its canonical subject type."""

    if (
        frame.operation is not SemanticOperation.ACTION_DRAFT
        or frame.output_shape != SemanticOutputShape.ACTION_DRAFT
    ):
        return proposal, frame
    subject_types = _action_draft_subject_types(proposal.subject_constraints)
    if len(subject_types) != 1:
        return proposal, frame
    temporal_scope = _ACTION_DRAFT_TEMPORAL_SCOPE[next(iter(subject_types))]
    if temporal_scope is None or proposal.temporal_scope == temporal_scope:
        return proposal, frame
    resolved = proposal.model_copy(update={"temporal_scope": temporal_scope})
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


CHANGE_ACTIVITY_COMPARISON_MEASURE = "change_activity_correlation"


def canonicalize_semantic_judgment_frame_proposal(
    proposal: SemanticFrameProposal,
    *,
    judgment: Mapping[str, Any] | None,
) -> SemanticFrameProposal:
    """Preserve one accepted typed draft before validating the model frame."""

    if (
        judgment is None
        or judgment.get("action_posture") != "draft_only"
        or judgment.get("authority") != "candidate_only"
        or judgment.get("execution_authority") is not False
    ):
        return proposal
    action_subject = judgment.get("action_subject")
    if not isinstance(action_subject, str) or action_subject not in _ACTION_DRAFT_TEMPORAL_SCOPE:
        return proposal
    frame_subjects = _action_draft_subject_types(proposal.subject_constraints)
    preserve_subject = (
        frame_subjects == {action_subject}
        and not proposal.unresolved_terms
        and not proposal.clarification_requirements
    )
    return _resolved_proposal(
        proposal,
        operation=SemanticOperation.ACTION_DRAFT,
        subject_constraints=(
            proposal.subject_constraints if preserve_subject else (action_subject,)
        ),
        measure_concepts=(),
        temporal_scope=_ACTION_DRAFT_TEMPORAL_SCOPE[action_subject],
        output_shape=SemanticOutputShape.ACTION_DRAFT,
    )


def build_named_resource_group_membership_frame(
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build one parent-scoped frame from an accepted resource-group judgment."""

    if (
        judgment is None
        or judgment.primary_intent != "query.contextual_resources"
        or judgment.action_posture != "advise_only"
        or judgment.ambiguous
        or judgment.unresolved_terms
        or len(judgment.targets) != 1
        or not _resource_parent_id_available(descriptors)
    ):
        return None
    target = judgment.targets[0]
    if (
        target.kind != "resource_group"
        or utterance[target.source_start : target.source_end] != target.value
    ):
        return None
    resolved = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource", target.value),
        measure_concepts=("parent_id", "type"),
        temporal_scope={},
        output_shape=SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_named_resource_group_membership(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Normalize a grounded named-group member request to its parent identity axis."""

    if proposal.operation is not SemanticOperation.SELECT or proposal.output_shape not in {
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST,
    }:
        return proposal, frame
    resolved = build_named_resource_group_membership_frame(
        judgment=judgment,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
    )
    return resolved if resolved is not None else (proposal, frame)


def _resource_parent_id_available(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "object"
        and descriptor.get("name") == "Resource"
        and isinstance((properties := descriptor.get("properties")), Mapping)
        and isinstance(properties.get("parent_id"), Mapping)
        for descriptor in descriptors
    )


def resolve_semantic_judgment_bound_read(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    bound_incident: bool,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Preserve validated bound read intent when the candidate frame drifts."""

    if judgment is None or judgment.action_posture != "advise_only":
        return proposal, frame
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    lookback_seconds = proposal.temporal_scope.get("lookback_seconds")
    lookback_hours = proposal.temporal_scope.get("lookback_hours")
    resource_targets = tuple(target for target in judgment.targets if target.kind == "resource")
    time_range_targets = tuple(target for target in judgment.targets if target.kind == "time_range")
    event_type_targets = tuple(target for target in judgment.targets if target.kind == "event_type")
    temporal_keys = set(proposal.temporal_scope)
    bounded_event_window = temporal_keys == {"lookback_seconds"} or (
        temporal_keys
        in (
            {"kind", "lookback_seconds"},
            {"kind", "lookback_seconds", "order"},
            {"kind", "lookback_seconds", "ordering"},
        )
        and proposal.temporal_scope.get("kind") in {"historical", "windowed"}
    )
    if (
        temporal_keys == {"kind", "lookback_hours", "order"}
        and proposal.temporal_scope.get("kind") in {"historical", "windowed"}
        and isinstance(lookback_hours, int)
        and not isinstance(lookback_hours, bool)
        and 1 <= lookback_hours <= 24
    ):
        lookback_seconds = lookback_hours * 3_600
        bounded_event_window = True
    kubernetes_event_family = "kubernetes_events" in facets
    judgment_lookback_seconds = (
        _canonical_duration_seconds(time_range_targets[0].canonical_value)
        if len(time_range_targets) == 1
        else None
    )
    kubernetes_event_history = (
        judgment.primary_intent == "query.resource_event_history"
        and kubernetes_event_family
        and bool(facets & {"time_order", "chronological_order", "ordering"})
        and len(resource_targets) == 1
        and len(time_range_targets) == 1
        and len(event_type_targets) == 1
        and len(judgment.targets)
        == len(resource_targets) + len(time_range_targets) + len(event_type_targets)
        and resource_targets[0].canonical_value in {None, "Resource"}
        and proposal.operation is SemanticOperation.SELECT
        and proposal.output_shape == SemanticOutputShape.RESOURCE_EVENT_HISTORY
        and "Resource" in proposal.subject_constraints
        and bounded_event_window
        and isinstance(lookback_seconds, int)
        and not isinstance(lookback_seconds, bool)
        and 60 <= lookback_seconds <= 86_400
        and judgment_lookback_seconds == lookback_seconds
        and not proposal.unresolved_terms
        and not proposal.clarification_requirements
    )
    if kubernetes_event_history:
        resolved = proposal.model_copy(
            update={
                "measure_concepts": (KUBERNETES_EVENT_FAMILY,),
                "temporal_scope": {"lookback_seconds": lookback_seconds},
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    configuration_drift_evidence = _facets_describe_configuration_drift_evidence(facets)
    if configuration_drift_evidence:
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.VALIDATE,
                "subject_constraints": ("Resource",),
                "measure_concepts": tuple(sorted(facets)),
                "temporal_scope": {"kind": "current"},
                "output_shape": SemanticOutputShape.EVIDENCE_VALIDATION,
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    resource_evidence_health = (
        judgment.primary_intent
        in {"query.resource_health_inventory", "query.target_health_assessment"}
        and all(target.canonical_value in {None, "Resource"} for target in judgment.targets)
        and _facets_describe_resource_evidence_health(facets)
    )
    if resource_evidence_health:
        resolved = _resolved_proposal(
            proposal,
            operation=SemanticOperation.VALIDATE,
            subject_constraints=("Resource",),
            measure_concepts=tuple(sorted(facets)),
            temporal_scope={"kind": "current"},
            output_shape=SemanticOutputShape.EVIDENCE_VALIDATION,
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    service_relationship_evidence = (
        judgment.primary_intent == "query.resource_state_inventory"
        and _facets_describe_service_relationship_evidence_gap(facets)
    ) or (
        judgment.primary_intent == "query.target_health_assessment"
        and (
            _facets_describe_service_relationship_evidence_gap(facets)
            or _facets_describe_service_relationship_assessment(facets)
        )
    )
    if service_relationship_evidence:
        resolved = _resolved_proposal(
            proposal,
            operation=SemanticOperation.VALIDATE,
            subject_constraints=("BusinessService", "Workload", "Resource"),
            measure_concepts=tuple(sorted(facets)),
            temporal_scope={"kind": "current"},
            output_shape=SemanticOutputShape.EVIDENCE_VALIDATION,
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    if (
        bound_incident
        and judgment.primary_intent in {"query.incident_evidence", "query.target_health_assessment"}
        and _facets_describe_incident_triage(facets)
    ):
        resolved = _resolved_proposal(
            proposal,
            operation=SemanticOperation.VALIDATE,
            subject_constraints=("Incident",),
            measure_concepts=tuple(sorted(facets)),
            temporal_scope={"kind": "current"},
            output_shape=SemanticOutputShape.INCIDENT_EVIDENCE,
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    if not bound_incident:
        return proposal, frame
    non_causal_comparison = any(
        (facet.startswith("no_") and "caus" in facet)
        or ("without" in facet and "caus" in facet)
        or "not_caus" in facet
        for facet in facets
    ) and any("window" in facet for facet in facets)
    windowed_change_activity = any("window" in facet for facet in facets) and any(
        "change" in facet for facet in facets
    )
    windowed_incident_change_activity = any("window" in facet for facet in facets) and any(
        "incident" in facet for facet in facets
    )
    completed_change_outcome = any(
        _facet_affirms_concept(facet, "completed_change") for facet in facets
    ) and any(
        _facet_affirms_concept(facet, token)
        for facet in facets
        for token in (
            "recovery",
            "regression",
            "unresolved_outcome",
            "observed_result",
            "observed_results",
        )
    )
    update: dict[str, object] | None = None
    if judgment.primary_intent in {
        "query.incident_evidence",
        "query.resource_error_activity_correlation",
        "query.resource_event_history",
    } and any(_facet_affirms_concept(facet, "recurrence") for facet in facets):
        update = {
            "operation": SemanticOperation.COMPARE,
            "subject_constraints": ("Incident",),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "historical"},
            "output_shape": SemanticOutputShape.INCIDENT_EVIDENCE,
        }
    elif (
        judgment.primary_intent
        in {
            "query.incident_evidence",
            "query.resource_change_activity",
            "query.resource_event_history",
        }
        and completed_change_outcome
    ):
        update = {
            "operation": SemanticOperation.SELECT,
            "subject_constraints": ("Change",),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "historical"},
            "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        }
    elif judgment.primary_intent == "query.resource_change_activity" and (
        any("correlation" in facet for facet in facets)
        or any("temporal_order" in facet and "caus" in facet for facet in facets)
        or non_causal_comparison
        or windowed_change_activity
        or windowed_incident_change_activity
    ):
        update = {
            "operation": SemanticOperation.COMPARE,
            "subject_constraints": ("Change",),
            "measure_concepts": tuple(sorted({CHANGE_ACTIVITY_COMPARISON_MEASURE, *facets})),
            "temporal_scope": {"kind": "windowed"},
            "output_shape": SemanticOutputShape.TEMPORAL_COMPARISON,
        }
    if update is None:
        return proposal, frame
    resolved = _resolved_proposal(proposal, **update)
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def _canonical_duration_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"duration\.PT(?:(\d{1,2})H)?(?:(\d{1,2})M)?(?:(\d{1,2})S)?", value)
    if match is None or all(part is None for part in match.groups()):
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if minutes >= 60 or seconds >= 60:
        return None
    duration_seconds = hours * 3_600 + minutes * 60 + seconds
    return duration_seconds if 60 <= duration_seconds <= 86_400 else None


def normalize_resource_classification_frame(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Restore current Resource classification from complete candidate facets."""

    facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    if (
        frame.operation is not SemanticOperation.SELECT
        or not proposal.subject_constraints
        or any(
            subject not in {"Resource", "ResourceType"} for subject in proposal.subject_constraints
        )
        or not _facets_describe_resource_classification(facets)
    ):
        return proposal, frame
    resolved = _resolved_proposal(
        proposal,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_ontology_trace_frame(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Normalize an exact schema trace from complementary frame and judgment evidence."""

    candidate_facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    judgment_facets = (
        {facet.replace("-", "_") for facet in judgment.requested_facets}
        if judgment is not None
        else set()
    )

    def describes_trace(facets: set[str]) -> bool:
        axes = all(
            any(_facet_affirms_concept(facet, concept) for facet in facets)
            for concept in ("resource_type", "signal_type", "action_type")
        )
        relationship = bool({"explore", "relationships", "trace"}.intersection(facets)) or any(
            _facet_affirms_concept(facet, "controlled_action_type") for facet in facets
        )
        return axes and relationship

    judgment_trace = (
        judgment is not None
        and judgment.action_posture == "advise_only"
        and judgment.primary_intent == "query.ontology_relationships"
        and describes_trace(judgment_facets)
    )
    candidate_trace = describes_trace(candidate_facets)
    facets = judgment_facets if judgment_trace else candidate_facets
    if (
        (not judgment_trace and not candidate_trace)
        or proposal.operation is not SemanticOperation.SELECT
        or proposal.output_shape != SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        or set(proposal.subject_constraints) != {"ActionType", "ResourceType", "Rule", "SignalType"}
    ):
        return proposal, frame
    resolved = _resolved_proposal(
        proposal,
        subject_constraints=("ActionType", "ResourceType", "Rule", "SignalType"),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={},
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_operating_objectives_frame(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Restore scoped objective semantics from a valid evidence-validation proposal."""

    facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    if (
        frame.operation is not SemanticOperation.VALIDATE
        or frame.output_shape != SemanticOutputShape.EVIDENCE_VALIDATION
        or not _facets_describe_operating_objectives(facets)
    ):
        return proposal, frame
    resolved = _resolved_proposal(
        proposal,
        subject_constraints=(
            "BusinessService",
            "RecoveryObjective",
            "ServiceObjective",
        ),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_historical_topology_clarification(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Preserve retained topology comparison until one exact Resource is supplied."""

    facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    typed_topology_comparison = (
        frame.operation is SemanticOperation.COMPARE
        and frame.output_shape == SemanticOutputShape.TOPOLOGY_GRAPH
        and frame.temporal_scope in ({"kind": "historical"}, {"kind": "windowed"})
    )
    if (
        frame.operation is not SemanticOperation.COMPARE
        or not (typed_topology_comparison or _facets_describe_historical_topology(facets))
        or exact_target_from_constraints(
            frame.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return proposal, frame
    korean = re.search(r"[가-힣]", utterance) is not None
    resolved = _resolved_proposal(
        proposal,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "historical"},
        output_shape=SemanticOutputShape.TEMPORAL_COMPARISON,
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "비교할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if korean
            else "Provide the exact Resource name or ID to compare?"
        ),
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
