"""Discover verified Resource candidates before an exact-target read."""

from __future__ import annotations

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
    query_target_cardinality,
)

from .semantic_current_state_planning import exact_target_from_constraints
from .semantic_planning_frame import build_semantic_frame
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


def build_resource_target_candidates_fallback(
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    confidence: float,
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
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
        temporal_scope={},
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


def resource_target_candidates_apply_to_utterance(
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
) -> bool:
    """Apply recovery only to a target-scoped or grounded residual subject."""

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
    return fallback if fallback is not None else (proposal, frame)


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
    "build_resource_target_candidates_fallback",
    "compile_resource_target_candidates_plan",
    "resource_target_candidates_apply_to_proposal",
    "resource_target_candidates_apply_to_utterance",
    "resolve_resource_target_candidates",
]
