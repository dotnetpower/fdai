"""Require every stated restriction on the reads that answer one goal.

V-SEM derives what a goal restricts from the admitted goal alone: its intersected kinds,
name fragments, earlier rows, regions, another ObjectType's lifecycle values, and its
Resource state or health concepts. A result read is a read whose rows answer the goal:
a traversal to the result endpoints, or an ObjectSet that no traversal and no other
function consumes. A state or health reader only filters such a read, so that read keeps
every other restriction, and the reader must read a result read and answer the goal
rather than sit on a side branch. Health rows also report unknown coverage and
not-modeled types, so no aggregate may count them as matches.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
)

from fdai.core.ontology_platform.resource_health_queries import RESOURCE_HEALTH_FUNCTION_NAME
from fdai.core.ontology_platform.resource_state_queries import RESOURCE_STATE_FUNCTION_NAME

_FILTER_READERS = frozenset({RESOURCE_STATE_FUNCTION_NAME, RESOURCE_HEALTH_FUNCTION_NAME})
_EXACT = frozenset({"equals", "in"})


@dataclass(frozen=True, slots=True)
class StatedRestrictions:
    """The restrictions one admitted goal states, each from its own grounded operands."""

    kinds_stated: bool
    required_types: frozenset[str]
    fragments: frozenset[str]
    prior_rows: tuple[str, ...]
    regions: frozenset[str]
    # Another ObjectType's lifecycle values, by (ObjectType, property).
    lifecycle: Mapping[tuple[str, str], frozenset[str]]
    state_concepts: tuple[str, ...]
    health_concepts: tuple[str, ...]


def filter_coverage(plans: Sequence[OntologyQueryPlan], stated: StatedRestrictions) -> list[str]:
    """Return a violation for each stated restriction a result read or reader drops."""

    violations: list[str] = []
    for plan in plans:
        for node in plan.nodes:
            if is_result_read(node, plan):
                violations.extend(_read_violations(node, stated))
            if node.kind is QueryNodeKind.AGGREGATE and any(
                function_name(item) == RESOURCE_HEALTH_FUNCTION_NAME
                for item in plan.nodes
                if item.node_id in node.depends_on
            ):
                violations.append("sem_health_rows_counted")
    for name, argument, concepts, reason in (
        (
            RESOURCE_STATE_FUNCTION_NAME,
            "state_concepts",
            stated.state_concepts,
            "sem_state_filter_missing",
        ),
        (
            RESOURCE_HEALTH_FUNCTION_NAME,
            "health_concepts",
            stated.health_concepts,
            "sem_health_filter_missing",
        ),
    ):
        if concepts and not any(
            function_name(node) == name
            and (node.arguments.get("arguments") or {}).get(argument) == list(concepts)
            and _filters_the_answer(node, plan)
            for plan in plans
            for node in plan.nodes
        ):
            violations.append(reason)
    return violations


def is_result_read(node: OntologyQueryNode, plan: OntologyQueryPlan) -> bool:
    if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL:
        return True
    if node.kind is not QueryNodeKind.OBJECT_SET:
        return False
    dependents = [item for item in plan.nodes if node.node_id in item.depends_on]
    functions = [item for item in dependents if item.kind is QueryNodeKind.FUNCTION]
    # A read that only a state or health reader filters is still the goal's result set.
    filtered = all(function_name(item) in _FILTER_READERS for item in functions)
    return filtered and not any(
        item.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL for item in dependents
    )


def function_name(node: OntologyQueryNode) -> str | None:
    if node.kind is not QueryNodeKind.FUNCTION:
        return None
    name = node.arguments.get("function_name")
    return name if isinstance(name, str) else None


def _read_violations(node: OntologyQueryNode, stated: StatedRestrictions) -> list[str]:
    selector, predicates = _read_predicates(node)
    violations: list[str] = []
    if stated.kinds_stated and not _has(predicates, "type", stated.required_types):
        violations.append("sem_type_filter_missing")
    for fragment in sorted(stated.fragments):
        if {"property": "name", "operator": "contains", "equals": fragment} not in predicates:
            violations.append("sem_name_fragment_missing")
    prior = {"property": "id", "operator": "in", "values": sorted(stated.prior_rows)}
    if stated.prior_rows and prior not in predicates:
        violations.append("sem_prior_result_unrestricted")
    if stated.regions and not _has(predicates, "location", stated.regions):
        violations.append("sem_region_filter_missing")
    for (object_type, property_name), values in sorted(stated.lifecycle.items()):
        if selector != object_type or not _has(predicates, property_name, values):
            violations.append("sem_lifecycle_filter_missing")
    return violations


def _read_predicates(node: OntologyQueryNode) -> tuple[str | None, list[Mapping[str, Any]]]:
    if node.kind is QueryNodeKind.OBJECT_SET:
        definition = node.arguments.get("definition") or {}
        selector = (definition.get("selector") or {}).get("name")
        return (
            selector if isinstance(selector, str) else None,
            list(definition.get("predicates") or ()),
        )
    return None, list(node.arguments.get("endpoint_predicates") or ())


def _has(predicates: Sequence[Mapping[str, Any]], name: str, values: frozenset[str]) -> bool:
    return any(
        item.get("property") == name
        and item.get("operator") in _EXACT
        and frozenset(item.get("values") or [item.get("equals")]) == values
        for item in predicates
    )


def _filters_the_answer(node: OntologyQueryNode, plan: OntologyQueryPlan) -> bool:
    """Return whether a reader filters a result read and its rows answer the goal."""

    by_id = {item.node_id: item for item in plan.nodes}
    reads = [by_id.get(item) for item in node.depends_on]
    if not reads or any(item is None or not is_result_read(item, plan) for item in reads):
        return False
    outputs = set(plan.output_node_ids)
    return node.node_id in outputs or any(
        item.kind is QueryNodeKind.AGGREGATE
        and item.node_id in outputs
        and node.node_id in item.depends_on
        for item in plan.nodes
    )


__all__ = ["StatedRestrictions", "filter_coverage", "function_name", "is_result_read"]
