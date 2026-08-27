"""Compile exact context-bound Resource collection queries."""

from __future__ import annotations

from datetime import UTC, datetime

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
from fdai.core.ontology_platform.contextual_resource_queries import (
    CONTEXTUAL_RESOURCE_FUNCTION_NAME,
)

from .semantic_planning_models import BoundResourceContext, SemanticOutputShape
from .semantic_planning_value_filters import stated_subject_fragment, stated_value_filters


def compile_contextual_resource_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    descriptors: tuple[dict[str, object], ...],
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
    bound_context: BoundResourceContext | None,
) -> OntologyQueryPlan | None:
    """Build a plan whose membership is exactly the trusted context resource set."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST
        or bound_context is None
        or not _has_contextual_function(manifest)
        or bound_context.principal_id is None
    ):
        return None
    resource_ids = tuple(bound_context.resource_ids)
    filters = stated_value_filters(utterance, descriptors)
    predicates: list[ObjectPredicate] = [
        ObjectPredicate(
            property="id",
            operator=(
                ObjectPredicateOperator.EQUALS
                if len(resource_ids) == 1
                else ObjectPredicateOperator.IN
            ),
            **({"equals": resource_ids[0]} if len(resource_ids) == 1 else {"values": resource_ids}),
        )
    ]
    for (object_type, property_name), values in sorted(filters.items()):
        if object_type != "Resource" or property_name == "id":
            continue
        predicates.append(
            ObjectPredicate(
                property=property_name,
                operator=(
                    ObjectPredicateOperator.EQUALS
                    if len(values) == 1
                    else ObjectPredicateOperator.IN
                ),
                **({"equals": values[0]} if len(values) == 1 else {"values": values}),
            )
        )
    subject = stated_subject_fragment(utterance, frame.subject_constraints, descriptors)
    if subject is not None:
        predicates.append(
            ObjectPredicate(
                property="name",
                operator=ObjectPredicateOperator.CONTAINS,
                equals=subject,
            )
        )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=tuple(predicates),
        as_of=evaluation_time.astimezone(UTC),
        purpose=purpose,
        limit=min(len(resource_ids), 1000),
    )
    scope = OntologyQueryNode(
        node_id="context-resource-scope",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
        output_kind="query.table",
    )
    function = OntologyQueryNode(
        node_id="context-resource-read",
        kind=QueryNodeKind.FUNCTION,
        depends_on=(scope.node_id,),
        arguments_json=canonical_json(
            {
                "function_name": CONTEXTUAL_RESOURCE_FUNCTION_NAME,
                "arguments": {
                    "context_kind": bound_context.kind,
                    "context_id": (
                        bound_context.screen_id
                        if bound_context.kind == "screen"
                        else bound_context.resource_group_id
                    ),
                    "resource_ids": list(resource_ids),
                    "principal_id": bound_context.principal_id,
                    "principal_scope_digest": bound_context.principal_scope_digest,
                    "ontology_release_digest": bound_context.ontology_release_digest,
                    "source_generation": bound_context.source_generation,
                    "selection_digest": bound_context.selection_digest,
                    "complete": bound_context.complete,
                },
                "dependency_arguments": {scope.node_id: "query_result"},
            }
        ),
        output_kind="query.table",
    )
    nodes = (scope, function)
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": [function.node_id],
        "execution_authority": False,
    }
    return verifier.verify(
        OntologyQueryPlan(
            ontology_release_digest=manifest.release_digest,
            semantic_catalog_digest=manifest.manifest_digest,
            problem_frame_digest=frame.frame_digest,
            purpose=purpose,
            caller_role=manifest.principal_role.value,
            nodes=nodes,
            output_node_ids=(function.node_id,),
            plan_digest=content_digest(body),
        ),
        manifest=manifest,
    )


def _has_contextual_function(manifest: QueryManifest) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == CONTEXTUAL_RESOURCE_FUNCTION_NAME
        for descriptor in manifest.descriptors
    )


__all__ = ["compile_contextual_resource_plan"]
