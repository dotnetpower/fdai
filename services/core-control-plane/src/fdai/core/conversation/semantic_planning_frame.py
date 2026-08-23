"""Build verified semantic frames and resolve server-owned clarification context."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from .semantic_investigation import VerifiedInvestigationIntent
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_planning_value_filters import stated_subject_fragment, stated_value_filters
from .semantic_target_identity import exact_target_from_constraints

_EXACT_RESOURCE_TARGET_OUTPUTS = frozenset(
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
_ACTION_DRAFT_TEMPORAL_SCOPE = {
    "ActionType": {},
    "Change": {"kind": "historical"},
    "Incident": {"kind": "current"},
    "RecoveryPlan": {"kind": "current"},
    "Rule": {},
}
CHANGE_ACTIVITY_COMPARISON_MEASURE = "change_activity_correlation"
_FACET_NEGATIONS = frozenset({"no", "non", "not", "without"})


def _facet_affirms_concept(facet: str, concept: str) -> bool:
    parts = tuple(part for part in facet.replace(".", "_").split("_") if part)
    if any(part in _FACET_NEGATIONS for part in parts):
        return False
    concept_parts = tuple(concept.split("_"))
    for index in range(len(parts) - len(concept_parts) + 1):
        if parts[index : index + len(concept_parts)] == concept_parts:
            return True
    return False


def _facets_describe_configuration_drift_evidence(facets: set[str]) -> bool:
    has_drift = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in ("configuration_drift", "drift_presence")
    )
    support_facets = {
        facet
        for facet in facets
        if any(
            _facet_affirms_concept(facet, token) for token in ("support", "supports", "supporting")
        )
    }
    refutation_facets = {
        facet
        for facet in facets
        if any(
            _facet_affirms_concept(facet, token)
            for token in ("refute", "refutes", "refuting", "refutation")
        )
    }
    return bool(
        has_drift
        and support_facets
        and refutation_facets
        and support_facets.isdisjoint(refutation_facets)
    )


def _facets_describe_service_resource_path(facets: set[str]) -> bool:
    has_combined_path = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in (
            "service_to_resource",
            "service_resource_relation",
            "service_resource_relationship",
        )
    )
    has_decomposed_path = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets)
        for concept in ("service", "resource", "relationship")
    )
    return has_combined_path or has_decomposed_path


def _facets_describe_service_relationship_evidence_gap(facets: set[str]) -> bool:
    has_evidence_gap = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in (
            "stale_relationship",
            "stale_relationships",
            "staleness",
            "incomplete_relationship",
            "incomplete_relationships",
            "incompleteness",
            "conflicting_relationship",
            "conflicting_relationships",
            "stale",
            "incomplete",
            "conflicting",
            "conflict",
        )
    )
    return _facets_describe_service_resource_path(facets) and has_evidence_gap


def _facets_describe_service_relationship_assessment(facets: set[str]) -> bool:
    has_conclusion_support = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in (
            "health_conclusion",
            "status_conclusion",
            "support",
            "supporting_evidence",
        )
    )
    return _facets_describe_service_resource_path(facets) and has_conclusion_support


def _facets_describe_incident_triage(facets: set[str]) -> bool:
    required_families = (
        ("verified_symptom", "verified_symptoms", "validated_symptom"),
        ("affected_scope", "impact_scope"),
        ("competing_hypotheses",),
        ("next_safe_diagnostic_step", "safest_next_diagnostic_step"),
    )
    return all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )


def _facets_describe_incident_metric_comparison(facets: set[str]) -> bool:
    has_comparison = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in ("compare", "comparison")
    )
    has_incident_scope = any(_facet_affirms_concept(facet, "incident") for facet in facets)
    return has_comparison and has_incident_scope


def _facets_describe_network_path(facets: set[str]) -> bool:
    required_families = (
        ("network_path", "request_path"),
        ("next_hop",),
        ("peering", "virtual_network_peering", "virtual_network_peering_relationship"),
    )
    return all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )


def _facets_describe_operating_objectives(facets: set[str]) -> bool:
    required_families = (
        ("service", "service_objective", "service_objectives"),
        ("recovery_objective", "recovery_objectives"),
        (
            "breach",
            "breaches",
            "measured_breach",
            "measured_breaches",
            "measured_violation",
            "violation",
        ),
        ("evidence_gap", "missing_evidence"),
    )
    return all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )


def _facets_describe_historical_topology(facets: set[str]) -> bool:
    has_boundaries = any(_facet_affirms_concept(facet, "before_after") for facet in facets) or all(
        any(_facet_affirms_concept(facet, boundary) for facet in facets)
        for boundary in ("before", "after")
    )
    has_comparison_window = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in ("compare", "comparison")
    ) and any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in (
            "cutoff",
            "requested_cutoff",
            "requested_time_reference",
            "requested_timeframe",
            "time_reference",
            "timeframe",
        )
    )
    required_families = (
        (
            "preservation_topology",
            "preserve_topology",
            "retained_topology",
            "retention_topology",
        ),
        (
            "cutoff",
            "requested_cutoff",
            "requested_time_reference",
            "requested_timeframe",
            "time_reference",
            "timeframe",
        ),
        ("relation_change", "relation_changes", "relationship_change", "relationship_changes"),
    )
    has_baseline_window = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in ("baseline_time_window", "baseline_timeframe")
    ) or (
        any(_facet_affirms_concept(facet, "baseline") for facet in facets)
        and any(_facet_affirms_concept(facet, "time_window") for facet in facets)
    )
    has_preservation_topology = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in (
            "preservation_topology",
            "preserve_topology",
            "retained_topology",
            "retention_topology",
        )
    )
    has_grounded_relationship_changes = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in (
            "evidence_backed_relationship_changes",
            "evidence_grounded_relationship_changes",
        )
    ) or (
        any(
            _facet_affirms_concept(facet, concept)
            for facet in facets
            for concept in ("evidence_backed", "evidence_grounded")
        )
        and any(_facet_affirms_concept(facet, "relationship_changes") for facet in facets)
    )
    standard_form = (has_boundaries or has_comparison_window) and all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )
    baseline_form = (
        any(
            _facet_affirms_concept(facet, concept)
            for facet in facets
            for concept in ("compare", "comparison")
        )
        and has_baseline_window
        and has_preservation_topology
        and has_grounded_relationship_changes
    )
    return standard_form or baseline_form


def _facets_describe_historical_relationship_change(facets: set[str]) -> bool:
    return (
        all(
            any(_facet_affirms_concept(facet, concept) for facet in facets)
            for concept in ("before_cutoff", "after_cutoff")
        )
        and any(_facet_affirms_concept(facet, "relationship_changes") for facet in facets)
        and any(_facet_affirms_concept(facet, "evidence_backed") for facet in facets)
    )


def _facets_describe_resource_activity(facets: set[str]) -> bool:
    required_families = (
        ("revision",),
        ("restart",),
        ("configuration", "configuration_activity"),
        ("last_30_minutes", "past_30_minutes", "time_window"),
    )
    detailed_form = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )
    abstract_families = (
        ("resource_change_activity",),
        ("time_window",),
        ("resource_kind",),
        ("activity_types",),
    )
    abstract_form = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in abstract_families
    )
    return detailed_form or abstract_form


def _facets_describe_ontology_release_health(facets: set[str]) -> bool:
    required_families = (
        ("declaration_change", "declaration_changes"),
        ("evidence_freshness",),
        ("completeness",),
        ("conflict", "conflicts"),
        ("unavailable_source", "unavailable_sources"),
    )
    return all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )


def _facets_describe_resource_evidence_health(facets: set[str]) -> bool:
    required_families = (
        ("freshness",),
        ("completeness",),
        ("conflict", "conflicts"),
        ("revision", "revisions"),
        ("evidence",),
        ("authorized_scope",),
    )
    required = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )
    healthy_conclusion = "avoid_healthy_result_inference" in facets or any(
        _facet_affirms_concept(facet, "healthy_result") for facet in facets
    )
    return required and healthy_conclusion


def _facets_describe_private_connectivity(facets: set[str]) -> bool:
    relationship_form = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets)
        for concept in ("attached_to", "routes_to", "workload_depends_on")
    )
    dependency_families = (
        ("connected_to", "observed_routing_relationship"),
        ("aks_pod_workload", "workload"),
        ("postgresql_dependency",),
        ("storage_dependency",),
    )
    dependency_form = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in dependency_families
    )
    return relationship_form or dependency_form


def _facets_describe_recovery_plan(facets: set[str]) -> bool:
    required_families = (
        ("causal_hypothesis",),
        ("resource", "resources", "resource_target", "resource_targets", "target_resources"),
        ("evidence_required", "evidence_still_required", "required_evidence"),
        ("approval",),
    )
    detailed_form = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )
    combined_form = (
        any(_facet_affirms_concept(facet, "causal_hypothesis") for facet in facets)
        and any(
            _facet_affirms_concept(facet, concept)
            for facet in facets
            for concept in ("resource", "resources")
        )
        and any(
            _facet_affirms_concept(facet, "evidence_required_before_approval") for facet in facets
        )
    )
    readiness_form = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets)
        for concept in ("review", "approval_readiness", "additional_evidence_needed")
    )
    return detailed_form or combined_form or readiness_form


def _facets_describe_resource_classification(facets: set[str]) -> bool:
    required_families = (
        ("resource_type_classification", "resource_type_classifications"),
        ("mapped_type", "mapped_types"),
        ("unmapped_native_type",),
        ("keep_unclassified",),
    )
    detailed_form = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )
    compact_form = any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in ("resource_type_classification", "resource_type_classifications")
    ) and any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in (
            "unclassified_native_type",
            "unclassified_native_types",
            "native_unmapped_types",
            "native_type_unclassified",
            "native_types_unclassified",
            "unmapped_native_type",
            "unmapped_native_types",
            "unmapped_native_type_unclassified",
        )
    )
    expanded_families = (
        ("reviewed_resource_type_classification", "reviewed_resourcetype_classification"),
        ("mapping",),
        ("native_unclassified_state", "unmapped_native_types"),
        ("explicit_unclassified_retention", "explicit_unclassified_state"),
    )
    expanded_form = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in expanded_families
    )
    decomposed_families = (
        ("resource_type_classification", "resourcetype_classification"),
        ("mapping",),
        ("native_type", "native_types"),
        ("unclassified_state",),
        ("reviewed",),
    )
    decomposed_form = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in decomposed_families
    )
    return detailed_form or compact_form or expanded_form or decomposed_form


def _facets_describe_resource_relationships(facets: set[str]) -> bool:
    required_families = (
        ("containing_parent", "containment_parent"),
        ("managed_disk", "managed_disks"),
        ("attached_network_interface", "attached_network_interfaces"),
    )
    required = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )
    direction = "non_reversed_ownership_direction" in facets or any(
        _facet_affirms_concept(facet, concept)
        for facet in facets
        for concept in ("preserve_ownership_direction", "stored_direction")
    )
    return required and direction


def _facets_describe_ontology_trace(facets: set[str]) -> bool:
    required = all(
        any(_facet_affirms_concept(facet, concept) for facet in facets)
        for concept in ("resource_type", "signal_type", "action_type")
    )
    relationship = bool(
        {"explore", "relationships", "trace", "trace_relationships"}.intersection(facets)
    ) or any(_facet_affirms_concept(facet, "controlled_action_type") for facet in facets)
    return required and relationship


def _facets_describe_service_agent_ownership(facets: set[str]) -> bool:
    required_families = (
        ("business_service", "business_services", "reviewed_business_services"),
        ("workload", "workloads"),
        ("resource", "resources"),
        ("declared_owning_agent", "owning_agent"),
    )
    no_execution_posture = bool(
        {
            "ownership_not_execution_permission",
            "ownership_without_execution_authority",
            "ownership_vs_execution_permission",
        }.intersection(facets)
    )
    return no_execution_posture and all(
        any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)
        for family in required_families
    )


def build_bound_incident_metric_comparison_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    bound_incident: bool,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame | None:
    """Build a no-authority frame for an unanchored metric comparison in a bound incident."""

    if (
        judgment is None
        or not bound_incident
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.resource_metric_series"
        or any(
            target.canonical_value not in {"Incident", "Observation", "Resource"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_incident_metric_comparison(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.COMPARE,
        subject_constraints=("Observation",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "windowed"},
        output_shape=SemanticOutputShape.TEMPORAL_COMPARISON,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return build_semantic_frame(proposal, utterance=utterance, context=context)


def build_network_path_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve a typed multi-endpoint network path until exact resource identity is supplied."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {"query.ontology_relationships", "query.resource_event_history"}
        or any(
            target.canonical_value not in {"Resource", "peered_with", "routes_to"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_network_path(facets):
        return None
    korean = re.search(r"[가-힣]", utterance) is not None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "추적할 정확한 시작 및 대상 Resource 이름 또는 ID를 알려주세요?"
            if korean
            else "Provide the exact source and target Resource names or IDs to trace?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_private_connectivity_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve private-connectivity relationships until exact endpoints are supplied."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {"query.ontology_relationships", "query.resource_ingress_configuration"}
        or any(
            target.canonical_value
            not in {
                None,
                "PostgreSQL",
                "Resource",
                "Storage",
                "Workload",
                "attached_to",
                "depends_on",
                "routes_to",
            }
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_private_connectivity(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "확인할 정확한 시작 및 대상 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact source and target Resource names or IDs to inspect?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_recovery_plan_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve RecoveryPlan validation until one exact plan identity is supplied."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {
            "query.linked_artifact_targets",
            "query.recovery_addresses_hypothesis",
            "query.recovery_targets_resource",
            "query.target_health_assessment",
        }
        or any(
            target.canonical_value
            not in {
                None,
                "Approval",
                "CausalHypothesis",
                "RecoveryPlan",
                "Resource",
                "recovery_addresses_hypothesis",
                "recovery_targets_resource",
            }
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_recovery_plan(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.VALIDATE,
        subject_constraints=("RecoveryPlan",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=(),
        unresolved_terms=("RecoveryPlan identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "검토할 정확한 RecoveryPlan 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact RecoveryPlan name or ID to review?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_resource_classification_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame | None:
    """Build a no-authority current Resource classification frame."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {
            "query.ontology_relationships",
            "query.resource_classified_as",
            "query.resource_state_inventory",
        }
        or any(
            target.canonical_value not in {None, "Resource", "ResourceType"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_resource_classification(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return build_semantic_frame(proposal, utterance=utterance, context=context)


def build_resource_relationship_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Request one exact Resource for a typed containment and attachment read."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {
            "query.ontology_relationships",
            "query.resource_current_state",
            "query.resource_relationships",
        }
        or any(
            target.canonical_value not in {None, "Resource", "attached_to", "contains", "owns"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_resource_relationships(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "관계를 확인할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact Resource name or ID whose relationships should be inspected?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_ontology_trace_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame | None:
    """Build a no-authority schema trace without materializing a current Finding."""

    expected_targets = {"ActionType", "ResourceType", "Rule", "SignalType"}
    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.ontology_relationships"
    ):
        return None
    observed_targets = {target.canonical_value for target in judgment.targets}
    allowed_targets: tuple[set[str], ...] = (
        set(),
        expected_targets,
        expected_targets | {"Resource", "Signal"},
    )
    if observed_targets not in allowed_targets:
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_ontology_trace(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("ActionType", "ResourceType", "Rule", "SignalType"),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return build_semantic_frame(proposal, utterance=utterance, context=context)


def build_service_agent_ownership_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> SemanticProblemFrame | None:
    """Build the exact read-only service-to-agent ownership path or abstain."""

    expected_subjects = {"Agent", "BusinessService", "Resource", "Workload"}
    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.ontology_relationships"
    ):
        return None
    declared_objects = {
        name
        for descriptor in descriptors
        if descriptor.get("kind") == "object"
        if isinstance((name := descriptor.get("name")), str)
    }
    if not expected_subjects <= declared_objects:
        return None
    expected_links = {
        "implemented_by": ("BusinessService", "Workload"),
        "owns": ("Agent", "Resource"),
        "workload_runs_on": ("Workload", "Resource"),
    }
    declared_links = {
        name: (descriptor.get("from_type"), descriptor.get("to_type"))
        for descriptor in descriptors
        if descriptor.get("kind") == "link"
        if isinstance((name := descriptor.get("name")), str)
        if name in expected_links
    }
    if declared_links != expected_links:
        return None
    observed_targets = {target.canonical_value for target in judgment.targets}
    allowed_targets = expected_subjects | {"AuthorizationPolicyAssignment"}
    if observed_targets and (
        "Agent" not in observed_targets or not observed_targets <= allowed_targets
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_service_agent_ownership(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Agent", "BusinessService", "Resource", "Workload"),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return build_semantic_frame(proposal, utterance=utterance, context=context)


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
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("Resource",),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "current"},
            "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
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
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("ActionType", "ResourceType", "Rule", "SignalType"),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {},
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def is_ontology_trace_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame is the bounded no-authority schema trace."""

    facets = set(frame.measure_concepts)
    return (
        frame.operation is SemanticOperation.SELECT
        and frame.subject_constraints == ("ActionType", "ResourceType", "Rule", "SignalType")
        and frame.temporal_scope == {}
        and frame.output_shape == SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and all(
            any(_facet_affirms_concept(facet, concept) for facet in facets)
            for concept in (
                "resource_type",
                "signal_type",
                "action_type",
            )
        )
        and (
            bool({"explore", "relationships", "trace", "trace_relationships"}.intersection(facets))
            or any(_facet_affirms_concept(facet, "controlled_action_type") for facet in facets)
        )
    )


def is_resource_classification_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame requests current Resource classification evidence."""

    return (
        frame.operation is SemanticOperation.SELECT
        and frame.subject_constraints == ("Resource",)
        and frame.temporal_scope == {"kind": "current"}
        and frame.output_shape == SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and _facets_describe_resource_classification(set(frame.measure_concepts))
    )


def build_operating_objectives_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame | None:
    """Build a no-authority frame for scoped objective evidence validation."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {
            "query.service_has_recovery_objective",
            "query.service_recovery_objectives",
            "query.target_health_assessment",
        }
        or any(
            target.canonical_value
            not in {"BusinessService", "RecoveryObjective", "ServiceObjective"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_operating_objectives(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.VALIDATE,
        subject_constraints=("BusinessService", "RecoveryObjective", "ServiceObjective"),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.EVIDENCE_VALIDATION,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return build_semantic_frame(proposal, utterance=utterance, context=context)


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
    resolved = proposal.model_copy(
        update={
            "subject_constraints": (
                "BusinessService",
                "RecoveryObjective",
                "ServiceObjective",
            ),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "current"},
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
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
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("Resource",),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "historical"},
            "output_shape": SemanticOutputShape.TEMPORAL_COMPARISON,
            "evidence_requirements": (),
            "unresolved_terms": ("Resource identity",),
            "clarification_requirements": (ClarificationRequirement.SUBJECT,),
            "clarification": (
                "비교할 정확한 Resource 이름 또는 ID를 알려주세요?"
                if korean
                else "Provide the exact Resource name or ID to compare?"
            ),
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def build_historical_topology_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build a retained-topology clarification from accepted candidate-only meaning."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {
            "query.ontology_relationships",
            "query.resource_change_activity",
            "query.resource_event_history",
        }
        or any(
            target.canonical_value not in {"ChangeWindow", "Resource"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not (
        _facets_describe_historical_topology(facets)
        or _facets_describe_historical_relationship_change(facets)
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.COMPARE,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "historical"},
        output_shape=SemanticOutputShape.TEMPORAL_COMPARISON,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "비교할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact Resource name or ID to compare?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_resource_activity_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve bounded Resource activity until one exact target is supplied."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.resource_change_activity"
        or any(target.canonical_value not in {None, "Resource"} for target in judgment.targets)
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_resource_activity(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "windowed"},
        output_shape=SemanticOutputShape.TARGET_ACTIVITY,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "활동을 조회할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact Resource name or ID whose activity should be queried?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_ontology_release_health_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame | None:
    """Build a no-authority historical release evidence-health frame."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {
            "query.ontology_declaration",
            "query.ontology_evidence_health",
            "query.ontology_relationships",
            "query.ontology_release_diff",
        }
        or any(
            target.canonical_value not in {None, "Ontology", "PolicyArtifact", "Resource", "Rule"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_ontology_release_health(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.VALIDATE,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "historical"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELEASE_EVIDENCE_HEALTH,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return build_semantic_frame(proposal, utterance=utterance, context=context)


def is_historical_topology_clarification_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether retained topology is waiting for one exact Resource identity."""

    return (
        frame.operation is SemanticOperation.COMPARE
        and frame.subject_constraints == ("Resource",)
        and frame.temporal_scope == {"kind": "historical"}
        and frame.output_shape == SemanticOutputShape.TEMPORAL_COMPARISON
        and _facets_describe_historical_topology(set(frame.measure_concepts))
        and frame.unresolved_terms == ("Resource identity",)
    )


def normalize_network_path_clarification(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Preserve a model-proposed network path until exact endpoint identities are supplied."""

    facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    targetless_topology = frame.output_shape == SemanticOutputShape.TOPOLOGY_GRAPH and (
        bool(stated_value_filters(utterance, descriptors).get(("Resource", "type")))
        or ("Resource" in frame.subject_constraints and len(frame.subject_constraints) > 1)
    )
    declared_object_types = {
        name
        for descriptor in descriptors
        if descriptor.get("kind") == "object"
        if isinstance((name := descriptor.get("name")), str)
    }
    frame_object_types = declared_object_types.intersection(frame.subject_constraints)
    multi_object_topology = (
        frame.output_shape
        in {
            SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            SemanticOutputShape.TOPOLOGY_GRAPH,
        }
        and "Resource" in frame_object_types
        and len(frame_object_types) > 1
    )
    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape
        not in {
            SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            SemanticOutputShape.TOPOLOGY_GRAPH,
        }
        or not (
            targetless_topology or multi_object_topology or _facets_describe_network_path(facets)
        )
        or exact_target_from_constraints(
            frame.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return proposal, frame
    korean = re.search(r"[가-힣]", utterance) is not None
    resolved_facets = {
        *facets,
        *(("topology_graph",) if targetless_topology or multi_object_topology else ()),
    }
    resolved = proposal.model_copy(
        update={
            "operation": SemanticOperation.SELECT,
            "subject_constraints": ("Resource",),
            "measure_concepts": tuple(sorted(resolved_facets)),
            "temporal_scope": {"kind": "current"},
            "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            "evidence_requirements": (),
            "unresolved_terms": ("Resource identity",),
            "clarification_requirements": (ClarificationRequirement.SUBJECT,),
            "clarification": (
                "추적할 정확한 시작 및 대상 Resource 이름 또는 ID를 알려주세요?"
                if korean
                else "Provide the exact source and target Resource names or IDs to trace?"
            ),
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def is_network_path_clarification_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame retains a network path pending exact endpoint identity."""

    return (
        frame.operation is SemanticOperation.SELECT
        and frame.subject_constraints == ("Resource",)
        and frame.temporal_scope == {"kind": "current"}
        and frame.output_shape == SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and (
            "topology_graph" in frame.measure_concepts
            or _facets_describe_network_path(set(frame.measure_concepts))
        )
        and frame.unresolved_terms == ("Resource identity",)
    )


def is_completed_change_outcome_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame requires unavailable historical effect closure."""

    facets = set(frame.measure_concepts)
    return (
        frame.operation is SemanticOperation.SELECT
        and frame.subject_constraints == ("Change",)
        and frame.temporal_scope == {"kind": "historical"}
        and frame.output_shape == SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and any(_facet_affirms_concept(facet, "completed_change") for facet in facets)
        and any(
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
    )


def is_configuration_drift_evidence_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame asks to validate configuration-drift evidence."""

    facets = set(frame.measure_concepts)
    return (
        frame.operation is SemanticOperation.VALIDATE
        and "Resource" in frame.subject_constraints
        and frame.temporal_scope == {"kind": "current"}
        and frame.output_shape == SemanticOutputShape.EVIDENCE_VALIDATION
        and _facets_describe_configuration_drift_evidence(facets)
    )


def is_incident_triage_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame requires unavailable structured incident triage."""

    return (
        frame.operation is SemanticOperation.VALIDATE
        and frame.subject_constraints == ("Incident",)
        and frame.temporal_scope == {"kind": "current"}
        and frame.output_shape == SemanticOutputShape.INCIDENT_EVIDENCE
        and _facets_describe_incident_triage(set(frame.measure_concepts))
    )


def _action_draft_subject_types(constraints: tuple[str, ...]) -> set[str]:
    return {
        constraint.split(":", 1)[0]
        for constraint in constraints
        if constraint.split(":", 1)[0] in _ACTION_DRAFT_TEMPORAL_SCOPE
    }


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
    return proposal.model_copy(
        update={
            "operation": SemanticOperation.ACTION_DRAFT,
            "subject_constraints": (
                proposal.subject_constraints if preserve_subject else (action_subject,)
            ),
            "measure_concepts": (),
            "temporal_scope": _ACTION_DRAFT_TEMPORAL_SCOPE[action_subject],
            "output_shape": SemanticOutputShape.ACTION_DRAFT,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )


def build_semantic_frame(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    context: tuple[str, ...],
    investigation_intent: VerifiedInvestigationIntent | None = None,
) -> SemanticProblemFrame:
    """Bind a candidate frame to exact input and investigation identities."""

    input_digest = content_digest({"utterance": utterance, "context": context})
    payload = {
        "schema_version": "1.0.0",
        "operation": proposal.operation.value,
        "subject_constraints": proposal.subject_constraints,
        "measure_concepts": proposal.measure_concepts,
        "temporal_scope": proposal.temporal_scope,
        "output_shape": proposal.output_shape.value,
        "evidence_requirements": proposal.evidence_requirements,
        "unresolved_terms": proposal.unresolved_terms,
        "input_digest": input_digest,
        "authority": "candidate_only",
        "execution_authority": False,
    }
    if investigation_intent is not None:
        payload["investigation_intent_digest"] = investigation_intent.intent_digest
    return SemanticProblemFrame(
        operation=proposal.operation,
        subject_constraints=proposal.subject_constraints,
        measure_concepts=proposal.measure_concepts,
        temporal_scope_json=canonical_json(proposal.temporal_scope),
        output_shape=proposal.output_shape.value,
        evidence_requirements=proposal.evidence_requirements,
        unresolved_terms=proposal.unresolved_terms,
        investigation_intent_digest=(
            investigation_intent.intent_digest if investigation_intent is not None else None
        ),
        input_digest=input_digest,
        frame_digest=content_digest(payload),
    )


def resolve_incident_reference(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Resolve the incident question only when the typed frame reads that incident."""

    requirements = proposal.clarification_requirements
    if (
        requirements != (ClarificationRequirement.INCIDENT_REFERENCE,)
        or frame.output_shape != SemanticOutputShape.INCIDENT_EVIDENCE
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


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
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.SELECT,
                "subject_constraints": ("ActionType", "ResourceType", "Rule", "SignalType"),
                "measure_concepts": tuple(sorted(judgment_facets)),
                "temporal_scope": {},
                "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
                "evidence_requirements": (),
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
                "investigation": None,
            }
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
    resolved = proposal.model_copy(
        update={
            "operation": SemanticOperation.ACTION_DRAFT,
            "subject_constraints": subject_constraints,
            "measure_concepts": (),
            "temporal_scope": {},
            "output_shape": SemanticOutputShape.ACTION_DRAFT,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


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
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.VALIDATE,
                "subject_constraints": ("Resource",),
                "measure_concepts": tuple(sorted(facets)),
                "temporal_scope": {"kind": "current"},
                "output_shape": SemanticOutputShape.EVIDENCE_VALIDATION,
                "evidence_requirements": (),
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
                "investigation": None,
            }
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
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.VALIDATE,
                "subject_constraints": ("BusinessService", "Workload", "Resource"),
                "measure_concepts": tuple(sorted(facets)),
                "temporal_scope": {"kind": "current"},
                "output_shape": SemanticOutputShape.EVIDENCE_VALIDATION,
                "evidence_requirements": (),
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
                "investigation": None,
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    if (
        bound_incident
        and judgment.primary_intent in {"query.incident_evidence", "query.target_health_assessment"}
        and _facets_describe_incident_triage(facets)
    ):
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.VALIDATE,
                "subject_constraints": ("Incident",),
                "measure_concepts": tuple(sorted(facets)),
                "temporal_scope": {"kind": "current"},
                "output_shape": SemanticOutputShape.INCIDENT_EVIDENCE,
                "evidence_requirements": (),
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
                "investigation": None,
            }
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
    resolved = proposal.model_copy(
        update={
            **update,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
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


def resolve_principal_scope_evidence_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Use server-owned Resource scope for an otherwise complete evidence frame."""

    if (
        frame.operation is not SemanticOperation.VALIDATE
        or frame.output_shape != SemanticOutputShape.EVIDENCE_VALIDATION
        or proposal.clarification_requirements
        not in {
            (ClarificationRequirement.SUBJECT,),
            (ClarificationRequirement.RESOURCE_IDENTITY,),
        }
        or proposal.subject_constraints not in {(), ("Resource",)}
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("Resource",),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def resource_target_clarification(
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> str | None:
    """Ask for one exact Resource before a target-scoped first-turn read."""
    if context or frame.output_shape in {
        SemanticOutputShape.RESOURCE_STATE_LIST,
        SemanticOutputShape.RESOURCE_TARGET_CANDIDATES,
    }:
        return None
    filters = stated_value_filters(utterance, descriptors)
    resource_filters = {
        property_name: values
        for (object_type, property_name), values in filters.items()
        if object_type == "Resource"
    }
    residual_subject = stated_subject_fragment(
        utterance,
        frame.subject_constraints,
        descriptors,
    )
    target_scoped = frame.output_shape in _EXACT_RESOURCE_TARGET_OUTPUTS or (
        residual_subject is not None and bool(frame.measure_concepts)
    )
    if (
        not resource_filters
        or not target_scoped
        or exact_target_from_constraints(
            frame.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return None
    korean = re.search(r"[가-힣]", utterance) is not None
    if frame.output_shape == SemanticOutputShape.TEMPORAL_COMPARISON:
        return (
            "확인할 리소스의 정확한 이름 또는 리소스 ID를 알려주세요. "
            "대상을 지정하면 요청한 기간의 변경 이력과 사용 가능한 근거를 검증하고, "
            "확인할 수 없는 항목은 한계로 구분하겠습니다."
            if korean
            else (
                "Provide the exact resource name or resource ID. Once identified, I will verify "
                "the change history for the requested period against available evidence and "
                "separate any unverified fields as limitations."
            )
        )
    return (
        "확인할 리소스의 정확한 이름 또는 리소스 ID를 알려주세요. "
        "대상을 지정하면 요청한 상태와 사용 가능한 근거를 검증하고, "
        "확인할 수 없는 항목은 한계로 구분하겠습니다."
        if korean
        else (
            "Provide the exact resource name or resource ID. Once identified, I will verify "
            "the requested state against available evidence and separate any unverified fields "
            "as limitations."
        )
    )


__all__ = [
    "build_bound_incident_metric_comparison_frame",
    "build_historical_topology_clarification",
    "build_network_path_clarification",
    "build_operating_objectives_frame",
    "build_service_agent_ownership_frame",
    "build_semantic_frame",
    "canonicalize_semantic_judgment_frame_proposal",
    "is_completed_change_outcome_frame",
    "is_configuration_drift_evidence_frame",
    "is_incident_triage_frame",
    "is_historical_topology_clarification_frame",
    "is_network_path_clarification_frame",
    "normalize_action_draft_temporal_scope",
    "normalize_network_path_clarification",
    "normalize_operating_objectives_frame",
    "normalize_historical_topology_clarification",
    "resource_target_clarification",
    "resolve_bound_incident_action_subject",
    "resolve_default_action_draft_subject",
    "resolve_incident_reference",
    "resolve_principal_scope_evidence_subject",
]
