"""Resource-type bounds for reviewed provider property paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdai_service_contracts.ontology_query import OntologyQueryNode

from .models import ObjectPredicateOperator, ObjectSetDefinition
from .query_manifest import ReviewedPropertyRead


def reviewed_property_paths(
    reads: Sequence[ReviewedPropertyRead],
) -> dict[str, frozenset[str]]:
    """Index each provider path by the Resource types that reviewed it."""

    by_path: dict[str, set[str]] = {}
    for read in reads:
        for kind, path in read.paths:
            by_path.setdefault(f"properties.properties.{path}", set()).add(kind)
    return {field: frozenset(kinds) for field, kinds in by_path.items()}


def reviewed_fields_for_resource_set(
    node: OntologyQueryNode,
    reviewed: Mapping[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    """Return paths reviewed for at least one exact type selected by the node."""

    definition = ObjectSetDefinition.model_validate(node.arguments["definition"])
    resource_types = set()
    for predicate in definition.predicates:
        if predicate.property != "type":
            continue
        if predicate.operator is ObjectPredicateOperator.EQUALS:
            resource_types.add(str(predicate.equals))
        elif predicate.operator is ObjectPredicateOperator.IN:
            resource_types.update(str(value) for value in predicate.values)
    return {
        field: types
        for field, types in reviewed.items()
        if resource_types and resource_types <= types
    }


__all__ = ["reviewed_fields_for_resource_set", "reviewed_property_paths"]
