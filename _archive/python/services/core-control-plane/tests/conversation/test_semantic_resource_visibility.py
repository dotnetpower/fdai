"""Operational Resource collection visibility tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.conversation.semantic_planning_models import SemanticOutputShape
from fdai.core.conversation.semantic_resource_visibility import (
    exclude_hidden_operational_resources,
)
from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
)

DIGEST = "sha256:" + ("a" * 64)
RESOURCE_DESCRIPTOR = {
    "kind": "object",
    "name": "Resource",
    "properties": {
        "type": {
            "type": "string",
            "values": ["compute.vm", "authorization.role-assignment"],
        }
    },
}


def _plan(definition: ObjectSetDefinition) -> OntologyQueryPlan:
    node = OntologyQueryNode(
        node_id="resources",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
        output_kind="query.table",
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": DIGEST,
        "semantic_catalog_digest": DIGEST,
        "problem_frame_digest": DIGEST,
        "purpose": "operations-review",
        "caller_role": "Reader",
        "nodes": [node.model_dump(mode="json")],
        "output_node_ids": ["resources"],
        "execution_authority": False,
    }
    return OntologyQueryPlan(
        ontology_release_digest=DIGEST,
        semantic_catalog_digest=DIGEST,
        problem_frame_digest=DIGEST,
        purpose="operations-review",
        caller_role="Reader",
        nodes=(node,),
        output_node_ids=("resources",),
        plan_digest=content_digest(body),
    )


def test_resource_list_excludes_role_assignments_and_preserves_existing_filters() -> None:
    original = _plan(
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
            predicates=(
                ObjectPredicate(
                    property="name",
                    operator=ObjectPredicateOperator.CONTAINS,
                    equals="fdai",
                ),
            ),
            as_of=datetime(2026, 9, 7, tzinfo=UTC),
            purpose="operations-review",
        )
    )

    filtered = exclude_hidden_operational_resources(
        original,
        output_shape=SemanticOutputShape.RESOURCE_LIST,
        descriptors=(RESOURCE_DESCRIPTOR,),
    )
    definition = ObjectSetDefinition.model_validate(filtered.nodes[0].arguments["definition"])

    assert definition.predicates == (
        ObjectPredicate(
            property="name",
            operator=ObjectPredicateOperator.CONTAINS,
            equals="fdai",
        ),
        ObjectPredicate(
            property="type",
            operator=ObjectPredicateOperator.NOT_EQUALS,
            equals="authorization.role-assignment",
        ),
    )
    assert filtered.plan_digest != original.plan_digest


def test_non_collection_plan_preserves_explicit_iam_query() -> None:
    original = _plan(
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
            predicates=(
                ObjectPredicate(
                    property="type",
                    operator=ObjectPredicateOperator.EQUALS,
                    equals="authorization.role-assignment",
                ),
            ),
            as_of=datetime(2026, 9, 7, tzinfo=UTC),
            purpose="operations-review",
        )
    )

    assert (
        exclude_hidden_operational_resources(
            original,
            output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            descriptors=(RESOURCE_DESCRIPTOR,),
        )
        is original
    )


def test_resource_schema_without_type_property_is_unchanged() -> None:
    original = _plan(
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
            as_of=datetime(2026, 9, 7, tzinfo=UTC),
            purpose="operations-review",
        )
    )

    assert (
        exclude_hidden_operational_resources(
            original,
            output_shape=SemanticOutputShape.RESOURCE_LIST,
            descriptors=(
                {
                    "kind": "object",
                    "name": "Resource",
                    "properties": {"id": {"type": "string"}},
                },
            ),
        )
        is original
    )
