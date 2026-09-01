"""Construct resource, network, historical, and relationship semantic frames."""

from __future__ import annotations

import re
from typing import Any

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_frame_facets import (
    _facets_describe_business_capability_mapping,
    _facets_describe_configuration_drift_evidence,
    _facets_describe_historical_relationship_change,
    _facets_describe_historical_topology,
    _facets_describe_incident_metric_comparison,
    _facets_describe_network_path,
    _facets_describe_ontology_release_health,
    _facets_describe_ontology_trace,
    _facets_describe_operating_objectives,
    _facets_describe_private_connectivity,
    _facets_describe_recovery_plan,
    _facets_describe_resource_activity,
    _facets_describe_resource_activity_types,
    _facets_describe_resource_classification,
    _facets_describe_resource_relationships,
    _facets_describe_service_agent_ownership,
    _facets_describe_service_current_health,
)
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)

_CHANGE_CORRELATION_FACETS = frozenset(
    {
        "approved_windows",
        "change",
        "incident",
        "service_paths",
        "target_resources",
        "without_current_finding",
    }
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


def build_configuration_drift_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve configuration-drift meaning until one exact Resource is supplied."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {"query.ontology_relationships", "query.resource_change_activity"}
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_configuration_drift_evidence(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.VALIDATE,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.EVIDENCE_VALIDATION,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "구성 드리프트를 확인할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else (
                "Provide the exact Resource name or ID whose configuration drift should be checked?"
            )
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_unbound_change_correlation_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    bound_incident: bool,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame | None:
    """Preserve the typed comparison contract when its incident binding is absent."""

    if (
        bound_incident
        or judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.ontology_relationships"
        or judgment.targets
        or frozenset(facet.replace("-", "_") for facet in judgment.requested_facets)
        != _CHANGE_CORRELATION_FACETS
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.COMPARE,
        subject_constraints=(
            "BusinessService",
            "Change",
            "ChangeWindow",
            "Resource",
            "Workload",
        ),
        measure_concepts=tuple(sorted(_CHANGE_CORRELATION_FACETS)),
        temporal_scope={"kind": "windowed"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=("bound_incident",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return build_semantic_frame(proposal, utterance=utterance, context=context)


def build_rule_state_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame | None:
    """Build the exact declaration frame for collected-versus-active Rule state."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.ontology_declaration"
        or any(target.canonical_value not in {None, "Rule"} for target in judgment.targets)
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if "rule_state" not in facets or not {
        "collected_reference",
        "not_active_policy",
        "no_current_violation",
    }.intersection(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Rule",),
        measure_concepts=("rule_state",),
        temporal_scope={},
        output_shape=SemanticOutputShape.ONTOLOGY_DECLARATION,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return build_semantic_frame(proposal, utterance=utterance, context=context)


def build_service_current_health_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve service-to-resource health meaning until one service is identified."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.ontology_relationships"
        or any(
            target.canonical_value not in {None, "BusinessService", "Resource", "Workload"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_service_current_health(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("BusinessService", "Resource", "Workload"),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=(),
        unresolved_terms=("BusinessService identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "현재 상태를 확인할 정확한 BusinessService 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else (
                "Provide the exact BusinessService name or ID whose current state "
                "should be checked?"
            )
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_business_capability_mapping_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame | None:
    """Build the unsupported boundary for current business capability mappings."""

    expected_subjects = {"BusinessCapability", "BusinessService"}
    observed_targets = (
        {target.canonical_value for target in judgment.targets} if judgment else set()
    )
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets} if judgment else set()
    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.ontology_relationships"
        or not observed_targets <= expected_subjects | {"delivered_by"}
        or (
            not expected_subjects <= observed_targets
            and not _facets_describe_business_capability_mapping(facets)
        )
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("BusinessCapability", "BusinessService"),
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


def build_resource_current_state_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Clarify an unresolved current-state target before candidate execution."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {"query.ontology_relationships", "query.resource_current_state"}
        or any(target.canonical_value not in {None, "Resource"} for target in judgment.targets)
    ):
        return None
    facets = tuple(sorted(facet.replace("-", "_") for facet in judgment.requested_facets))
    if "current_state" not in facets or (
        judgment.primary_intent == "query.ontology_relationships" and len(judgment.targets) != 1
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=facets,
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.TARGET_CURRENT_STATE,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=judgment.clarification
        or (
            "현재 상태를 확인할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact Resource name or ID whose current state should be checked?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


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
    if observed_targets == expected_targets:
        facets.update({"resource_type", "signal_type", "action_type"})
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
        or any(
            target.canonical_value not in {None, "Resource"}
            and not (
                target.kind == "time_range"
                and target.canonical_value is not None
                and target.canonical_value.startswith("duration.")
            )
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    has_duration_target = any(
        target.kind == "time_range"
        and target.canonical_value is not None
        and target.canonical_value.startswith("duration.")
        for target in judgment.targets
    )
    if not _facets_describe_resource_activity(facets) and not (
        has_duration_target and _facets_describe_resource_activity_types(facets)
    ):
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


def build_resource_event_history_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve event-history meaning until one exact Resource is supplied."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.resource_event_history"
        or any(
            target.canonical_value not in {None, "Resource"}
            and not (
                target.kind == "time_range"
                and target.canonical_value is not None
                and target.canonical_value.startswith("duration.")
            )
            for target in judgment.targets
        )
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
        output_shape=SemanticOutputShape.RESOURCE_EVENT_HISTORY,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "이벤트를 조회할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact Resource name or ID whose events should be queried?"
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
