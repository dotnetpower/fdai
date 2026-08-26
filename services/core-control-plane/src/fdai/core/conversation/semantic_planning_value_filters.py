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
_FREE_TEXT_FRAGMENT_PROPERTIES = ("name", "label", "id")


def stated_value_filters(
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
            selected = list(dict.fromkeys(selected))
            if len(selected) > 1:
                most_specific = tuple(
                    candidate
                    for candidate in selected
                    if all(set(candidate) < set(other) for other in selected if other != candidate)
                )
                selected = list(most_specific) if len(most_specific) == 1 else selected
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
        if not _ascii_alphanumeric(before) and not _ascii_alphanumeric(after):
            return True
        start = lowered_utterance.find(needle, start + 1)
    return False


def _ascii_alphanumeric(value: str) -> bool:
    return value.isascii() and value.isalnum()


def stated_subject_fragment(
    utterance: str,
    subject_constraints: Sequence[str],
    descriptors: Sequence[Mapping[str, Any]],
) -> str | None:
    """Return one exact free-text subject preserved from the operator turn.

    Descriptor names, property names, and declared value terms already have a
    typed grounding path. A remaining subject can narrow a free-text property
    only when it occurs verbatim in the utterance. Multiple remaining subjects
    are ambiguous and therefore ground nothing.
    """
    vocabulary = _declared_subject_vocabulary(descriptors)
    lowered = utterance.casefold()
    candidates: list[str] = []
    seen: set[str] = set()
    for subject in subject_constraints:
        candidate = subject.strip()
        normalized = candidate.casefold()
        if (
            not candidate
            or normalized in vocabulary
            or normalized in seen
            or not _term_stated(candidate, lowered)
        ):
            continue
        candidates.append(candidate)
        seen.add(normalized)
    return candidates[0] if len(candidates) == 1 else None


def _declared_subject_vocabulary(
    descriptors: Sequence[Mapping[str, Any]],
) -> frozenset[str]:
    """Return typed descriptor words that must not become free-text operands."""
    words: set[str] = set()
    for descriptor in descriptors:
        name = descriptor.get("name")
        if isinstance(name, str):
            words.add(name.casefold())
        properties = descriptor.get("properties")
        if not isinstance(properties, Mapping):
            continue
        for property_name, declaration in properties.items():
            if isinstance(property_name, str):
                words.add(property_name.casefold())
            if not isinstance(declaration, Mapping):
                continue
            values = declaration.get("values")
            if isinstance(values, list):
                words.update(value.casefold() for value in values if isinstance(value, str))
            groups = declaration.get("value_groups")
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                group_id = group.get("id")
                if isinstance(group_id, str):
                    words.add(group_id.casefold())
                for key in ("terms", "values"):
                    items = group.get(key)
                    if isinstance(items, list):
                        words.update(item.casefold() for item in items if isinstance(item, str))
    return frozenset(words)


def ground_stated_value_filters(
    plan: OntologyQueryPlan,
    *,
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
    subject_constraints: Sequence[str] = (),
) -> tuple[OntologyQueryPlan, tuple[str, ...]]:
    """Constrain an existence predicate the operator already stated a value for.

    A bare existence predicate over a required property selects the whole
    ObjectType, so a stated filter would be answered with an unfiltered
    superset. Rewriting it can only narrow the result, and every operand comes
    from the declared domain the verifier checks.
    """
    filters = stated_value_filters(utterance, descriptors)
    subject_fragment = stated_subject_fragment(
        utterance,
        subject_constraints,
        descriptors,
    )
    if not filters and subject_fragment is None:
        return plan, ()
    grounded: list[str] = []
    nodes: list[OntologyQueryNode] = []
    for node in plan.nodes:
        rewritten = _grounded_object_set(
            node,
            descriptors=descriptors,
            filters=filters,
            subject_fragment=subject_fragment,
            grounded=grounded,
        )
        nodes.append(rewritten)
    if not grounded:
        return plan, ()
    payload = {
        **plan.model_dump(mode="json", exclude={"nodes", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    narrowed = OntologyQueryPlan.model_validate({**payload, "plan_digest": content_digest(payload)})
    return narrowed, tuple(grounded)


def verify_stated_value_filter_operands(
    plan: OntologyQueryPlan,
    *,
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
) -> None:
    """Reject model-proposed enum operands that the operator did not state."""
    filters = stated_value_filters(utterance, descriptors)
    for node in plan.nodes:
        if node.kind.value != "object_set":
            continue
        definition = node.arguments.get("definition")
        selector = definition.get("selector") if isinstance(definition, Mapping) else None
        predicates = definition.get("predicates") if isinstance(definition, Mapping) else None
        object_type = selector.get("name") if isinstance(selector, Mapping) else None
        if not isinstance(object_type, str) or not isinstance(predicates, list):
            continue
        properties = _object_properties(object_type, descriptors)
        for predicate in predicates:
            if not isinstance(predicate, Mapping):
                continue
            property_name = predicate.get("property")
            if not isinstance(property_name, str):
                continue
            operator = predicate.get("operator")
            declaration = properties.get(property_name)
            if (
                operator in {"exists", "absent"}
                or not isinstance(declaration, Mapping)
                or not isinstance(declaration.get("value_groups"), list)
            ):
                continue
            operands = predicate.get("values") if operator == "in" else [predicate.get("equals")]
            stated_values = filters.get((object_type, property_name))
            if (
                not isinstance(operands, (list, tuple))
                or not operands
                or stated_values is None
                or not set(operands) <= set(stated_values)
            ):
                raise ValueError("semantic enum predicate operand is not grounded in the utterance")


def _grounded_object_set(
    node: OntologyQueryNode,
    *,
    descriptors: Sequence[Mapping[str, Any]],
    filters: Mapping[tuple[str, str], tuple[str, ...]],
    subject_fragment: str | None,
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
    properties = _object_properties(object_type, descriptors)
    rewritten: list[Any] = []
    selected_properties: set[str] = set()
    changed = False
    for predicate in predicates:
        property_name = predicate.get("property") if isinstance(predicate, Mapping) else None
        if isinstance(property_name, str):
            selected_properties.add(property_name)
        values = (
            filters.get((object_type, property_name)) if isinstance(property_name, str) else None
        )
        if (
            isinstance(predicate, Mapping)
            and predicate.get("operator") == "in"
            and values is not None
            and set(values) <= set(str(value) for value in predicate.get("values", ()))
        ):
            narrowed = _value_predicate(str(property_name), values)
            rewritten.append(narrowed)
            grounded.append(f"{object_type}.{property_name}")
            changed = changed or dict(predicate) != narrowed
            continue
        if not isinstance(predicate, Mapping) or predicate.get("operator") != "exists":
            rewritten.append(predicate)
            continue
        if values is not None:
            rewritten.append(_value_predicate(str(property_name), values))
            grounded.append(f"{object_type}.{property_name}")
            changed = True
            continue
        if (
            subject_fragment is None
            or property_name not in _FREE_TEXT_FRAGMENT_PROPERTIES
            or property_name not in properties
            or _property_has_values(properties[property_name])
        ):
            rewritten.append(predicate)
            continue
        rewritten.append(
            {
                "property": property_name,
                "operator": "contains",
                "equals": subject_fragment,
            }
        )
        grounded.append(f"{object_type}.{property_name}")
        changed = True
    for (filter_type, property_name), values in sorted(filters.items()):
        if filter_type != object_type or property_name in selected_properties:
            continue
        rewritten.append(_value_predicate(property_name, values))
        selected_properties.add(property_name)
        grounded.append(f"{object_type}.{property_name}")
        changed = True
    if subject_fragment is not None and not any(
        property_name in selected_properties for property_name in _FREE_TEXT_FRAGMENT_PROPERTIES
    ):
        fragment_property = next(
            (
                property_name
                for property_name in _FREE_TEXT_FRAGMENT_PROPERTIES
                if property_name in properties
                and not _property_has_values(properties[property_name])
            ),
            None,
        )
        if fragment_property is not None:
            rewritten.append(
                {
                    "property": fragment_property,
                    "operator": "contains",
                    "equals": subject_fragment,
                }
            )
            grounded.append(f"{object_type}.{fragment_property}")
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


def _object_properties(
    object_type: str,
    descriptors: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    for descriptor in descriptors:
        if descriptor.get("kind") != "object" or descriptor.get("name") != object_type:
            continue
        properties = descriptor.get("properties")
        if isinstance(properties, Mapping):
            return properties
    return {}


def _property_has_values(declaration: object) -> bool:
    return isinstance(declaration, Mapping) and isinstance(declaration.get("values"), list)


def _value_predicate(property_name: str, values: tuple[str, ...]) -> dict[str, object]:
    return (
        {"property": property_name, "operator": "equals", "equals": values[0]}
        if len(values) == 1
        else {"property": property_name, "operator": "in", "values": list(values)}
    )


__all__ = [
    "MAX_GROUNDED_FILTER_VALUES",
    "ground_stated_value_filters",
    "stated_subject_fragment",
    "stated_value_filters",
    "verify_stated_value_filter_operands",
]
