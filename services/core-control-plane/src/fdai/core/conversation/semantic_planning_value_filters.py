"""Ground a stated value filter into an ObjectSet predicate before verification.

The catalog declares the words an operator uses for a value, so a filter the
operator already stated can be grounded without asking a model to reproduce the
value. This lives beside the planner rather than inside it because it reads only
the plan and the declared descriptors.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    canonical_json,
    content_digest,
)

MAX_GROUNDED_FILTER_VALUES = 16


def _stated_value_filters(
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Return declared values whose own request terms the operator actually typed.

    The catalog declares the words an operator uses for a value, so a stated
    filter can be grounded without asking a model to reproduce the value. Two
    different groups matching the same property is ambiguous, and guessing one
    would answer a question nobody asked, so that property is skipped.
    """
    lowered = utterance.casefold()
    matched: dict[tuple[str, str], tuple[str, ...]] = {}
    for descriptor in descriptors:
        if descriptor.get("kind") != "object":
            continue
        object_type = descriptor.get("name")
        properties = descriptor.get("properties")
        if not isinstance(object_type, str) or not isinstance(properties, Mapping):
            continue
        for property_name, declaration in properties.items():
            if not isinstance(property_name, str) or not isinstance(declaration, Mapping):
                continue
            groups = declaration.get("value_groups")
            if not isinstance(groups, list):
                continue
            selected: list[tuple[str, ...]] = []
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                terms = group.get("terms")
                values = group.get("values")
                if not isinstance(terms, list) or not isinstance(values, list):
                    continue
                if any(isinstance(term, str) and _term_stated(term, lowered) for term in terms):
                    selected.append(tuple(str(value) for value in values))
            if len(selected) != 1 or not 1 <= len(selected[0]) <= MAX_GROUNDED_FILTER_VALUES:
                continue
            matched[(object_type, property_name)] = tuple(sorted(set(selected[0])))
    return matched


def _term_stated(term: str, lowered_utterance: str) -> bool:
    """Report whether ``term`` stands on its own inside the utterance.

    Korean writes without spaces between a noun and its particle, so a bare
    substring test is correct there. An ASCII term needs a boundary or a short
    word such as `vm` would match inside an unrelated identifier.
    """
    needle = term.casefold().strip()
    if not needle:
        return False
    start = lowered_utterance.find(needle)
    while start != -1:
        if not needle.isascii():
            return True
        before = lowered_utterance[start - 1] if start else " "
        after_index = start + len(needle)
        after = lowered_utterance[after_index] if after_index < len(lowered_utterance) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        start = lowered_utterance.find(needle, start + 1)
    return False


def ground_stated_value_filters(
    plan: OntologyQueryPlan,
    *,
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[OntologyQueryPlan, tuple[str, ...]]:
    """Constrain an existence predicate the operator already stated a value for.

    A bare existence predicate over a required property selects the whole
    ObjectType, so a stated filter would be answered with an unfiltered
    superset. Rewriting it can only narrow the result, and every operand comes
    from the declared domain the verifier checks.
    """
    filters = _stated_value_filters(utterance, descriptors)
    if not filters:
        return plan, ()
    grounded: list[str] = []
    nodes: list[OntologyQueryNode] = []
    for node in plan.nodes:
        rewritten = _grounded_object_set(node, filters=filters, grounded=grounded)
        nodes.append(rewritten)
    if not grounded:
        return plan, ()
    payload = {
        **plan.model_dump(mode="json", exclude={"nodes", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    narrowed = OntologyQueryPlan.model_validate({**payload, "plan_digest": content_digest(payload)})
    return narrowed, tuple(grounded)


def _grounded_object_set(
    node: OntologyQueryNode,
    *,
    filters: Mapping[tuple[str, str], tuple[str, ...]],
    grounded: list[str],
) -> OntologyQueryNode:
    if node.kind.value != "object_set":
        return node
    definition = node.arguments.get("definition")
    if not isinstance(definition, Mapping):
        return node
    selector = definition.get("selector")
    if not isinstance(selector, Mapping) or selector.get("kind") != "object_type":
        return node
    object_type = selector.get("name")
    predicates = definition.get("predicates")
    if not isinstance(object_type, str) or not isinstance(predicates, list):
        return node
    rewritten: list[Any] = []
    changed = False
    for predicate in predicates:
        if not isinstance(predicate, Mapping) or predicate.get("operator") != "exists":
            rewritten.append(predicate)
            continue
        property_name = predicate.get("property")
        values = (
            filters.get((object_type, property_name)) if isinstance(property_name, str) else None
        )
        if values is None:
            rewritten.append(predicate)
            continue
        property_name = str(property_name)
        rewritten.append(
            {"property": property_name, "operator": "equals", "equals": values[0]}
            if len(values) == 1
            else {"property": property_name, "operator": "in", "values": list(values)}
        )
        grounded.append(f"{object_type}.{property_name}")
        changed = True
    if not changed:
        return node
    return node.model_copy(
        update={
            "arguments_json": canonical_json(
                {
                    **node.arguments,
                    "definition": {**definition, "predicates": rewritten},
                }
            )
        }
    )


__all__ = ["MAX_GROUNDED_FILTER_VALUES", "ground_stated_value_filters"]
