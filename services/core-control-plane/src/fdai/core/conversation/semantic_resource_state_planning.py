"""Normalize and compile collection-scoped Resource state reads."""

from __future__ import annotations

from datetime import UTC, datetime
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

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanVerifier,
    QueryManifest,
)
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    RESOURCE_STATE_MEASURE_CONCEPTS,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryEvidenceAuthority,
)

from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape
from .semantic_planning_value_filters import stated_value_filters

_GENERIC_COLLECTION_OUTPUTS = frozenset(
    {
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_LIST,
    }
)
_STATE_MEASURES = frozenset(RESOURCE_STATE_MEASURE_CONCEPTS)


def normalize_resource_state_proposal(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
) -> SemanticFrameProposal:
    """Select the collection-state family only from capability-declared measures."""

    declared_measures, value_groups = _state_descriptor_metadata(descriptors)
    catalog_state_measures, catalog_health_measures = _catalog_state_measures(
        utterance,
        registry=inventory_query_language,
    )
    if (
        proposal.operation is SemanticOperation.SELECT
        and proposal.output_shape
        in {
            *_GENERIC_COLLECTION_OUTPUTS,
            SemanticOutputShape.RESOURCE_HEALTH_LIST,
            SemanticOutputShape.RESOURCE_STATE_LIST,
        }
        and catalog_health_measures
    ):
        return proposal.model_copy(
            update={
                "measure_concepts": tuple(sorted(catalog_state_measures | catalog_health_measures)),
                "output_shape": SemanticOutputShape.RESOURCE_HEALTH_LIST,
            }
        )
    stated_measures = _stated_state_measures(utterance, value_groups=value_groups)
    state_measures = (
        catalog_state_measures
        or stated_measures
        or declared_measures.intersection(proposal.measure_concepts)
    )
    if (
        proposal.operation is not SemanticOperation.SELECT
        or proposal.output_shape
        not in {*_GENERIC_COLLECTION_OUTPUTS, SemanticOutputShape.RESOURCE_STATE_LIST}
        or not state_measures
    ):
        return proposal
    return proposal.model_copy(
        update={
            "measure_concepts": tuple(sorted(state_measures)),
            "output_shape": SemanticOutputShape.RESOURCE_STATE_LIST,
        }
    )


def _catalog_state_measures(
    utterance: str,
    *,
    registry: InventoryQueryLanguageRegistry | None,
) -> tuple[frozenset[str], frozenset[str]]:
    """Resolve catalog state groups without crossing their evidence authority."""
    if registry is None:
        return frozenset(), frozenset()
    selected = _stated_state_measures(
        utterance,
        value_groups=tuple((state_id, state.terms) for state_id, state in registry.states.items()),
    )
    state_measures: set[str] = set()
    health_measures: set[str] = set()
    for state_id in selected:
        state = registry.states[state_id]
        normalized = {f"resource_state.{value}" for value in state.values}
        if (
            state.evidence_authority is not QueryEvidenceAuthority.CURRENT_INVENTORY
            or not normalized <= _STATE_MEASURES
        ):
            health_measures.add(f"resource_health.{state_id}")
        else:
            state_measures.update(normalized)
    return frozenset(state_measures), frozenset(health_measures)


def compile_resource_state_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build a secured Resource collection followed by verified state filtering."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_STATE_LIST
        or not _has_state_function(manifest.descriptors)
    ):
        return None
    state_concepts = tuple(sorted(_STATE_MEASURES.intersection(frame.measure_concepts)))
    if not state_concepts:
        return None
    definition = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
    )
    nodes = (
        OntologyQueryNode(
            node_id="resource-state-scope",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-state-filter",
            kind=QueryNodeKind.FUNCTION,
            depends_on=("resource-state-scope",),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_STATE_FUNCTION_NAME,
                    "arguments": {"state_concepts": list(state_concepts)},
                    "dependency_arguments": {"resource-state-scope": "query_result"},
                }
            ),
            output_kind="query.table",
        ),
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": ["resource-state-filter"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("resource-state-filter",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def resource_collection_definition(
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    evaluation_time: datetime,
    purpose: str,
) -> ObjectSetDefinition:
    """Build one current Resource scope narrowed only by stated catalog types."""

    filters = stated_value_filters(utterance, descriptors)
    type_values = filters.get(("Resource", "type"), ())
    type_predicate = (
        ObjectPredicate(
            property="type",
            operator=ObjectPredicateOperator.EQUALS,
            equals=type_values[0],
        )
        if len(type_values) == 1
        else ObjectPredicate(
            property="type",
            operator=ObjectPredicateOperator.IN,
            values=type_values,
        )
        if type_values
        else ObjectPredicate(property="type", operator=ObjectPredicateOperator.EXISTS)
    )
    as_of = evaluation_time.astimezone(UTC)
    return ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(type_predicate,),
        as_of=as_of,
        purpose=purpose,
        limit=1000,
    )


def _state_descriptor_metadata(
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[frozenset[str], tuple[tuple[str, tuple[str, ...]], ...]]:
    selected = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_STATE_FUNCTION_NAME
    )
    if len(selected) != 1:
        return frozenset(), ()
    output_schema = selected[0].get("output_schema")
    if not isinstance(output_schema, dict):
        return frozenset(), ()
    measures = output_schema.get("x-fdai-measure-concepts")
    if not isinstance(measures, list):
        return frozenset(), ()
    groups = output_schema.get("x-fdai-measure-value-groups")
    value_groups: list[tuple[str, tuple[str, ...]]] = []
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            concept = group.get("concept")
            terms = group.get("terms")
            if not isinstance(concept, str) or not isinstance(terms, list):
                continue
            bounded_terms = tuple(term for term in terms if isinstance(term, str) and term.strip())
            if bounded_terms:
                value_groups.append((concept, bounded_terms))
    return (
        frozenset(measure for measure in measures if isinstance(measure, str)),
        tuple(value_groups),
    )


def _stated_state_measures(
    utterance: str,
    *,
    value_groups: tuple[tuple[str, tuple[str, ...]], ...],
) -> frozenset[str]:
    folded = utterance.casefold()
    matches: list[tuple[int, int, str]] = []
    for concept, terms in value_groups:
        for term in terms:
            needle = term.casefold().strip()
            start = folded.find(needle)
            while start != -1:
                end = start + len(needle)
                if not needle.isascii() or _ascii_term_is_bounded(folded, start, end):
                    matches.append((start, end, concept))
                start = folded.find(needle, start + 1)
    selected = {
        concept
        for start, end, concept in matches
        if not any(
            other_concept != concept
            and other_start <= start
            and end <= other_end
            and (other_start, other_end) != (start, end)
            for other_start, other_end, other_concept in matches
        )
    }
    return frozenset(selected)


def _ascii_term_is_bounded(value: str, start: int, end: int) -> bool:
    before = value[start - 1] if start else " "
    after = value[end] if end < len(value) else " "
    return not (before.isascii() and before.isalnum()) and not (after.isascii() and after.isalnum())


def _has_state_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_STATE_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = [
    "compile_resource_state_plan",
    "normalize_resource_state_proposal",
    "resource_collection_definition",
]
