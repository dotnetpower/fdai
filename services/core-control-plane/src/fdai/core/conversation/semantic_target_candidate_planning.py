"""Discover verified Resource candidates before an exact-target read."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryTargetCardinality,
    query_signal_matches,
    query_target_cardinality,
)

from .semantic_current_state_planning import exact_target_from_constraints
from .semantic_planning_frame import (
    build_semantic_frame,
    is_configuration_drift_evidence_frame,
    is_historical_topology_clarification_frame,
    is_network_path_clarification_frame,
)
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_planning_value_filters import stated_subject_fragment, stated_value_filters
from .semantic_resource_state_planning import resource_collection_definition

_TARGET_SCOPED_OUTPUTS = frozenset(
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
_CANDIDATE_RESOLVABLE_REQUIREMENTS = frozenset(
    {
        ClarificationRequirement.MEASURE,
        ClarificationRequirement.RESOURCE_IDENTITY,
        ClarificationRequirement.SUBJECT,
    }
)
_TARGET_BOUND_OPERATING_INTENT_TYPES = frozenset(
    {
        "ArchitectureConstraint",
        "ChangeWindow",
        "CostObjective",
        "Ownership",
        "RecoveryObjective",
        "ServiceObjective",
    }
)
_DECISION_OUTCOME_LINEAGE_TYPES = (
    "DecisionCase",
    "ActionOption",
    "ActionRun",
    "ObservedOutcome",
)


def build_stated_resource_filter_frame(
    *,
    semantic_judgment: Mapping[str, Any] | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build a filtered collection from one source-grounded judgment facet."""

    if semantic_judgment is None or semantic_judgment.get("action_posture") != "advise_only":
        return None
    primary_intent = semantic_judgment.get("primary_intent")
    if not isinstance(primary_intent, str) or not (
        primary_intent in {"query.contextual_resources", "query.ontology_relationships"}
        or primary_intent.startswith("query.resource_")
    ):
        return None
    raw_facets = semantic_judgment.get("requested_facets")
    if (
        not isinstance(raw_facets, Sequence)
        or isinstance(raw_facets, (str, bytes))
        or any(not isinstance(facet, str) for facet in raw_facets)
    ):
        return None
    filters = stated_value_filters(utterance, descriptors)
    if not filters.get(("Resource", "type")):
        return None
    targets = semantic_judgment.get("targets")
    target_values = (
        [
            target["value"]
            for target in targets
            if isinstance(target, Mapping)
            and isinstance(target.get("kind"), str)
            and (target["kind"] == "affected_target" or target["kind"].endswith("_filter"))
            and isinstance(target.get("value"), str)
            and target.get("canonical_value") is None
        ]
        if isinstance(targets, Sequence) and not isinstance(targets, (str, bytes))
        else []
    )
    unique_target_values = tuple(
        dict.fromkeys(
            value for value in target_values if utterance.casefold().count(value.casefold()) == 1
        )
    )
    fragment = (
        unique_target_values[0]
        if len(unique_target_values) == 1
        else stated_subject_fragment(utterance, raw_facets, descriptors)
    )
    if fragment is None:
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource", fragment),
        measure_concepts=("name", "type"),
        temporal_scope={},
        output_shape=SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        evidence_requirements=("authoritative_inventory",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=float(semantic_judgment.get("confidence", 0.0)),
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_resource_target_candidates_fallback(
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    confidence: float,
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
    temporal_scope: dict[str, str] | None = None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build a server-owned candidate frame from a verified Resource type only."""

    filters = stated_value_filters(utterance, descriptors)
    if not filters.get(("Resource", "type")):
        return None
    if (
        query_target_cardinality(utterance, inventory_query_language)
        is QueryTargetCardinality.COLLECTION
    ):
        return None
    if (
        exact_target_from_constraints(
            (),
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=(),
        temporal_scope=temporal_scope or {},
        output_shape=SemanticOutputShape.RESOURCE_TARGET_CANDIDATES,
        evidence_requirements=("authoritative_inventory",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=confidence,
    )
    return proposal, build_semantic_frame(
        proposal,
        utterance=utterance,
        context=context,
    )


def build_non_resource_target_clarification(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve an operating-object subject instead of substituting Resource candidates."""

    cardinality = query_target_cardinality(utterance, inventory_query_language)
    subject_types = _non_resource_object_subjects(proposal.subject_constraints, descriptors)
    subject_types = _expand_operating_intent_subjects(subject_types, descriptors)
    allow_unknown_cardinality = bool(
        _TARGET_BOUND_OPERATING_INTENT_TYPES.intersection(subject_types)
    )
    if (
        cardinality is QueryTargetCardinality.COLLECTION
        or (cardinality is not QueryTargetCardinality.SINGULAR and not allow_unknown_cardinality)
        or not stated_value_filters(utterance, descriptors).get(("Resource", "type"))
    ):
        return None
    if not subject_types:
        return None
    if (
        exact_target_from_constraints(
            proposal.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return None
    target_type = subject_types[0]
    korean = re.search(r"[가-힣]", utterance) is not None
    resolved = proposal.model_copy(
        update={
            "operation": SemanticOperation.SELECT,
            "subject_constraints": subject_types,
            "temporal_scope": {"kind": "current"},
            "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            "unresolved_terms": (f"{target_type} identity",),
            "clarification_requirements": (ClarificationRequirement.SUBJECT,),
            "clarification": (
                f"확인할 정확한 {target_type} 이름 또는 ID를 알려주세요?"
                if korean
                else f"Provide the exact {target_type} name or ID?"
            ),
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def _expand_operating_intent_subjects(
    subject_types: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    selected = set(subject_types)
    if not _TARGET_BOUND_OPERATING_INTENT_TYPES.intersection(selected) and selected != {
        "BusinessService"
    }:
        return subject_types
    for descriptor in descriptors:
        if descriptor.get("kind") != "link":
            continue
        source_type = descriptor.get("from_type")
        target_type = descriptor.get("to_type")
        if (
            isinstance(source_type, str)
            and isinstance(target_type, str)
            and target_type in _TARGET_BOUND_OPERATING_INTENT_TYPES
            and (source_type in selected or target_type in selected)
        ):
            selected.update((source_type, target_type))
    return tuple(
        name
        for descriptor in descriptors
        if descriptor.get("kind") == "object"
        if isinstance((name := descriptor.get("name")), str)
        if name in selected
    )


def resource_target_candidates_apply_to_utterance(
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
) -> bool:
    """Apply recovery only to a target-scoped or grounded residual subject."""

    if property_filter_has_stated_subject(
        frame,
        utterance=utterance,
        descriptors=descriptors,
    ):
        return False
    if _has_non_resource_object_subject(frame.subject_constraints, descriptors):
        return False
    cardinality = query_target_cardinality(utterance, inventory_query_language)
    if cardinality is QueryTargetCardinality.COLLECTION:
        return False
    if cardinality is QueryTargetCardinality.SINGULAR:
        return True
    if frame.output_shape in _TARGET_SCOPED_OUTPUTS:
        return True
    residual_subject = stated_subject_fragment(
        utterance,
        frame.subject_constraints,
        descriptors,
    )
    return residual_subject is not None and bool(frame.measure_concepts)


def resource_target_candidates_apply_to_proposal(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
) -> bool:
    """Gate frame recovery to structured target intent without phrase routing."""

    if _has_non_resource_object_subject(proposal.subject_constraints, descriptors):
        return False
    cardinality = query_target_cardinality(utterance, inventory_query_language)
    if cardinality is QueryTargetCardinality.COLLECTION:
        return False
    if cardinality is QueryTargetCardinality.SINGULAR:
        return True
    if proposal.output_shape in _TARGET_SCOPED_OUTPUTS:
        return True
    if ClarificationRequirement.RESOURCE_IDENTITY in proposal.clarification_requirements:
        return True
    residual_subject = stated_subject_fragment(
        utterance,
        proposal.subject_constraints,
        descriptors,
    )
    return residual_subject is not None and bool(proposal.measure_concepts)


def resolve_resource_target_candidates(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Replace a first-turn exact-target hold with bounded subtype discovery."""

    if property_filter_has_stated_subject(
        proposal,
        utterance=utterance,
        descriptors=descriptors,
    ):
        return proposal, frame
    if (
        frame.output_shape == SemanticOutputShape.TARGET_CURRENT_STATE
        and "active_revision" not in frame.measure_concepts
    ):
        return proposal, frame
    if frame.output_shape == SemanticOutputShape.TOPOLOGY_GRAPH:
        return proposal, frame
    if is_configuration_drift_evidence_frame(frame):
        return proposal, frame
    if is_network_path_clarification_frame(frame):
        return proposal, frame
    if is_historical_topology_clarification_frame(frame):
        return proposal, frame
    if _has_non_resource_object_subject(proposal.subject_constraints, descriptors):
        return proposal, frame
    cardinality = query_target_cardinality(utterance, inventory_query_language)
    if cardinality is QueryTargetCardinality.COLLECTION:
        return proposal, frame
    residual_subject = stated_subject_fragment(
        utterance,
        frame.subject_constraints,
        descriptors,
    )
    requirements = frozenset(proposal.clarification_requirements)
    target_scoped = (
        cardinality is QueryTargetCardinality.SINGULAR
        or frame.output_shape in _TARGET_SCOPED_OUTPUTS
        or (residual_subject is not None and bool(frame.measure_concepts))
        or bool(
            requirements
            & {
                ClarificationRequirement.RESOURCE_IDENTITY,
                ClarificationRequirement.SUBJECT,
            }
        )
    )
    if not target_scoped:
        return proposal, frame
    if not requirements <= _CANDIDATE_RESOLVABLE_REQUIREMENTS:
        return proposal, frame
    filters = stated_value_filters(utterance, descriptors)
    if not filters.get(("Resource", "type")):
        return proposal, frame
    if (
        exact_target_from_constraints(
            frame.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return proposal, frame
    fallback = build_resource_target_candidates_fallback(
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        confidence=proposal.confidence,
        inventory_query_language=inventory_query_language,
    )
    if fallback is None:
        return proposal, frame
    temporal_scope = frame.temporal_scope
    if not temporal_scope and frame.output_shape == SemanticOutputShape.TARGET_CURRENT_STATE:
        temporal_scope = {"kind": "current"}
    if not temporal_scope:
        return fallback
    candidate, _candidate_frame = fallback
    candidate = candidate.model_copy(update={"temporal_scope": temporal_scope})
    return candidate, build_semantic_frame(candidate, utterance=utterance, context=context)


def normalize_operating_relationship_temporal_scope(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Bind runtime operating-object relationships to the current data plane."""

    subject_types = _non_resource_object_subjects(proposal.subject_constraints, descriptors)
    measures = set(proposal.measure_concepts)
    schema_trace = (
        set(proposal.subject_constraints) == {"ActionType", "ResourceType", "Rule", "SignalType"}
        and {"resource_type", "signal_type"} <= measures
        and any("action_type" in measure for measure in measures)
        and (
            bool(
                {"explore", "relationships", "trace", "trace_relationships"}.intersection(measures)
            )
            or "controlled_action_type" in measures
        )
    )
    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        or not subject_types
        or proposal.temporal_scope
        or is_exact_schema_relationship(
            proposal,
            utterance=utterance,
            descriptors=descriptors,
        )
        or schema_trace
    ):
        return proposal, frame
    resolved = proposal.model_copy(update={"temporal_scope": {"kind": "current"}})
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def is_exact_schema_relationship(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    """Return whether an atemporal frame names exact ObjectType declarations."""

    subject_types = _non_resource_object_subjects(proposal.subject_constraints, descriptors)
    utterance_tokens = set(re.findall(r"[a-z0-9]+", utterance.casefold()))
    return (
        proposal.operation is SemanticOperation.SELECT
        and proposal.output_shape is SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and proposal.temporal_scope == {}
        and 1 <= len(subject_types) <= 2
        and len(subject_types) == len(proposal.subject_constraints)
        and all(subject.casefold() in utterance_tokens for subject in subject_types)
    )


def normalize_decision_outcome_relationship(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Restore the canonical historical decision-to-outcome relationship path."""

    subject_types = set(_non_resource_object_subjects(proposal.subject_constraints, descriptors))
    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        or not {"DecisionCase", "ObservedOutcome"} <= subject_types
        or not {"ActionOption", "ActionRun"}.intersection(subject_types)
    ):
        return proposal, frame
    declared_types = {
        name
        for descriptor in descriptors
        if descriptor.get("kind") == "object"
        if isinstance((name := descriptor.get("name")), str)
    }
    exact_target = exact_target_from_constraints(
        proposal.subject_constraints,
        utterance=utterance,
        descriptors=descriptors,
    )
    target_constraints = tuple(
        constraint
        for constraint in proposal.subject_constraints
        if constraint not in declared_types
    )
    if exact_target is not None and exact_target not in target_constraints:
        target_constraints = (*target_constraints, exact_target)
    needs_target = exact_target is None
    korean = re.search(r"[가-힣]", utterance) is not None
    resolved = proposal.model_copy(
        update={
            "subject_constraints": (*_DECISION_OUTCOME_LINEAGE_TYPES, *target_constraints),
            "temporal_scope": {"kind": "historical"},
            "unresolved_terms": ("DecisionCase identity",) if needs_target else (),
            "clarification_requirements": (
                (ClarificationRequirement.SUBJECT,) if needs_target else ()
            ),
            "clarification": (
                (
                    "추적할 정확한 DecisionCase 이름 또는 ID를 알려주세요?"
                    if korean
                    else "Provide the exact DecisionCase name or ID?"
                )
                if needs_target
                else None
            ),
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


_RESOURCE_IDENTITY_TERMS = frozenset({"resource_identity", "resource identity"})


def resolve_stated_resource_identity(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> SemanticFrameProposal:
    """Clear a resource-identity hold the utterance already answers exactly."""

    if proposal.clarification_requirements != (ClarificationRequirement.RESOURCE_IDENTITY,):
        return proposal
    if not proposal.unresolved_terms or any(
        term.casefold() not in _RESOURCE_IDENTITY_TERMS for term in proposal.unresolved_terms
    ):
        return proposal
    if _has_non_resource_object_subject(proposal.subject_constraints, descriptors):
        return proposal
    if (
        proposal.operation is SemanticOperation.SELECT
        and proposal.output_shape is SemanticOutputShape.RESOURCE_LIST
    ):
        return proposal.model_copy(
            update={
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
            }
        )
    if (
        exact_target_from_constraints(
            proposal.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is None
    ):
        return proposal
    return proposal.model_copy(
        update={
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
        }
    )


def normalize_resource_list_temporal_scope(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> SemanticFrameProposal:
    """Remove a model-invented history axis from a current resource listing."""

    if (
        proposal.operation is not SemanticOperation.SELECT
        or proposal.output_shape
        not in {
            SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST,
            SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
            SemanticOutputShape.RESOURCE_LIST,
        }
        or not proposal.temporal_scope
        or query_signal_matches(utterance, inventory_query_language, "temporal")
    ):
        return proposal
    return proposal.model_copy(update={"temporal_scope": {}})


def property_filter_omits_stated_relation(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> bool:
    """Reject a filtered-resource frame that drops its stated relation target."""

    return (
        proposal.output_shape == SemanticOutputShape.PROPERTY_FILTERED_RESOURCES
        and query_signal_matches(
            utterance,
            inventory_query_language,
            "resource_name_relation",
        )
        and len(proposal.subject_constraints) < 2
    )


def property_filter_has_stated_subject(
    proposal: SemanticFrameProposal | SemanticProblemFrame,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    """Return whether a property filter retains one exact free-text subject."""

    return (
        proposal.output_shape == SemanticOutputShape.PROPERTY_FILTERED_RESOURCES
        and "name" in proposal.measure_concepts
        and set(proposal.measure_concepts) <= {"name", "type"}
        and stated_subject_fragment(
            utterance,
            proposal.subject_constraints,
            descriptors,
        )
        is not None
    )


def _has_non_resource_object_subject(
    constraints: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    return bool(_non_resource_object_subjects(constraints, descriptors))


def _non_resource_object_subjects(
    constraints: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    object_types = {
        name
        for descriptor in descriptors
        if descriptor.get("kind") == "object"
        if isinstance((name := descriptor.get("name")), str)
        if name != "Resource"
    }
    return tuple(constraint for constraint in constraints if constraint in object_types)


def compile_resource_target_candidates_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build one secured current-inventory query for exact target candidates."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_TARGET_CANDIDATES
    ):
        return None
    definition = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
    )
    node = OntologyQueryNode(
        node_id="resource-target-candidates",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
        output_kind="query.table",
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json")],
        "output_node_ids": [node.node_id],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=(node,),
        output_node_ids=(node.node_id,),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


__all__ = [
    "build_non_resource_target_clarification",
    "build_resource_target_candidates_fallback",
    "compile_resource_target_candidates_plan",
    "is_exact_schema_relationship",
    "normalize_decision_outcome_relationship",
    "normalize_operating_relationship_temporal_scope",
    "normalize_resource_list_temporal_scope",
    "resource_target_candidates_apply_to_proposal",
    "resource_target_candidates_apply_to_utterance",
    "resolve_resource_target_candidates",
    "resolve_stated_resource_identity",
]
