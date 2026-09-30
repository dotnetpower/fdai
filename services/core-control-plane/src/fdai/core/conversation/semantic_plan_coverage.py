"""Check that a verified current-path plan reads what the question was read to ask.

The judgment's coverage review proves that the judgment quoted every stated constraint,
but the frame and plan built from that judgment can still drop one: a per-group count
planned as one ungrouped count, or a region question planned as a list of every Resource
of that kind. These checks compare closed structure only, never words. A plan that reads
only a filtered list has no function, metric, path, order, grouping, or predicate beyond
kind, name, and identity; a reading that asks more than such a list, or a blind reading
that states a grouping or a relation, is then not what the plan answers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
)

from .semantic_reasoning_review import ConstraintExtraction, ConstraintRole

PLAN_CONSTRAINT_UNCOVERED = "semantic_plan_constraint_uncovered"
# Properties a filtered list reads: its kind, a name part, an identity, and its container.
_LIST_PROPERTIES = frozenset({"type", "name", "id", "parent_id"})
_CONTAINMENT = "contains"


def plan_reads_only_a_list(plan: OntologyQueryPlan) -> bool:
    """Return whether the plan can only answer a filtered Resource list or its row count.

    Every node reads objects by kind, name part, identity, or container, unites such
    reads, projects their fields, or counts them without a grouping; nothing else.
    """

    return all(_list_node(node) for node in plan.nodes)


def plan_uncovered_roles(
    extraction: ConstraintExtraction | None, plan: OntologyQueryPlan
) -> tuple[str, ...]:
    """Return the closed roles a blind reading states that the plan's structure never reads.

    A stated grouping needs a grouped aggregate, and a stated relation needs more than a
    filtered list. Restrictions stay with the judgment's coverage review, because two
    readers may fairly disagree on whether a word restricts or names the kind read.
    """

    if extraction is None:
        return ()
    roles = {item.role for item in extraction.constraints}
    uncovered: list[str] = []
    if ConstraintRole.GROUPS in roles and not any(_grouped(node) for node in plan.nodes):
        uncovered.append(ConstraintRole.GROUPS.value)
    if ConstraintRole.RELATES in roles and plan_reads_only_a_list(plan):
        uncovered.append(ConstraintRole.RELATES.value)
    return tuple(uncovered)


def _list_node(node: OntologyQueryNode) -> bool:
    arguments = node.arguments
    if node.kind in {QueryNodeKind.UNION, QueryNodeKind.PROJECT}:
        return True
    if node.kind is QueryNodeKind.AGGREGATE:
        return arguments.get("operation") == "count" and not arguments.get("group_by")
    if node.kind is QueryNodeKind.OBJECT_SET:
        definition = arguments.get("definition")
        if not isinstance(definition, Mapping) or definition.get("traversal") is not None:
            return False
        return _list_predicates(definition.get("predicates", ()))
    if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL:
        # A containment read from a named container to its members only restates a scope.
        return list(arguments.get("link_types", ())) == [_CONTAINMENT] and _list_predicates(
            arguments.get("endpoint_predicates", ())
        )
    return False


def _list_predicates(predicates: Any) -> bool:
    if not isinstance(predicates, Iterable) or isinstance(predicates, str | bytes | Mapping):
        return False
    return all(
        isinstance(item, Mapping) and item.get("property") in _LIST_PROPERTIES
        for item in predicates
    )


def _grouped(node: OntologyQueryNode) -> bool:
    return node.kind is QueryNodeKind.AGGREGATE and bool(node.arguments.get("group_by"))


__all__ = ["PLAN_CONSTRAINT_UNCOVERED", "plan_reads_only_a_list", "plan_uncovered_roles"]
