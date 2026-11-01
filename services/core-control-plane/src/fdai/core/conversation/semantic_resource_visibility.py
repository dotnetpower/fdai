"""Keep authorization evidence out of operational Resource collections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
)

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelectorKind,
    ObjectSetDefinition,
)

from .semantic_planning_models import SemanticOutputShape

OPERATIONAL_RESOURCE_EXCLUDED_TYPES = ("authorization.role-assignment",)

_OPERATIONAL_RESOURCE_COLLECTION_OUTPUTS = frozenset(
    {
        SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST,
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_CONDITION_SECTIONS,
        SemanticOutputShape.RESOURCE_HEALTH_LIST,
        SemanticOutputShape.RESOURCE_LIST,
        SemanticOutputShape.RESOURCE_STATE_LIST,
        SemanticOutputShape.RESOURCE_TARGET_CANDIDATES,
    }
)


def exclude_hidden_operational_resources(
    plan: OntologyQueryPlan,
    *,
    output_shape: SemanticOutputShape,
    descriptors: Sequence[Mapping[str, Any]],
) -> OntologyQueryPlan:
    """Exclude access-control carrier objects from operational Resource lists."""

    excluded_types = _declared_excluded_resource_types(descriptors)
    if output_shape not in _OPERATIONAL_RESOURCE_COLLECTION_OUTPUTS or not excluded_types:
        return plan
    changed = False
    nodes = []
    for node in plan.nodes:
        if node.kind is not QueryNodeKind.OBJECT_SET:
            nodes.append(node)
            continue
        definition = ObjectSetDefinition.model_validate(node.arguments.get("definition"))
        if (
            definition.selector.kind is not ObjectSelectorKind.OBJECT_TYPE
            or definition.selector.name != "Resource"
        ):
            nodes.append(node)
            continue
        predicates = list(definition.predicates)
        for resource_type in excluded_types:
            exclusion = ObjectPredicate(
                property="type",
                operator=ObjectPredicateOperator.NOT_EQUALS,
                equals=resource_type,
            )
            if exclusion not in predicates:
                predicates.append(exclusion)
                changed = True
        updated_definition = definition.model_copy(update={"predicates": tuple(predicates)})
        nodes.append(
            node.model_copy(
                update={
                    "arguments_json": canonical_json(
                        {
                            **node.arguments,
                            "definition": updated_definition.model_dump(mode="json"),
                        }
                    )
                }
            )
        )
    if not changed:
        return plan
    payload = {
        **plan.model_dump(mode="json", exclude={"nodes", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    return OntologyQueryPlan.model_validate({**payload, "plan_digest": content_digest(payload)})


def _declared_excluded_resource_types(
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    for descriptor in descriptors:
        if descriptor.get("kind") != "object" or descriptor.get("name") != "Resource":
            continue
        properties = descriptor.get("properties")
        type_property = properties.get("type") if isinstance(properties, Mapping) else None
        values = type_property.get("values") if isinstance(type_property, Mapping) else None
        if not isinstance(values, (list, tuple)):
            return ()
        declared = {value for value in values if isinstance(value, str)}
        return tuple(
            resource_type
            for resource_type in OPERATIONAL_RESOURCE_EXCLUDED_TYPES
            if resource_type in declared
        )
    return ()


__all__ = [
    "OPERATIONAL_RESOURCE_EXCLUDED_TYPES",
    "exclude_hidden_operational_resources",
]
