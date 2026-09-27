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
_FREE_TEXT_FRAGMENT_PROPERTIES = ("name", "label", "id", "parent_id")
# Characters that join an ASCII term into a larger identifier, such as a Resource name,
# when an ASCII letter or digit continues on their other side.
_IDENTIFIER_JOINERS = frozenset("-_./:")


def stated_value_filters(
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
    *,
    allowed_properties: frozenset[str] | None = None,
    preferred_terms: Sequence[str] = (),
    excluded_values: frozenset[str] = frozenset(),
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
            if allowed_properties is not None and property_name not in allowed_properties:
                continue
            groups = declaration.get("value_groups")
            if not isinstance(groups, list):
                continue
            selected: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
            spans: dict[tuple[tuple[str, ...], tuple[str, ...]], set[tuple[int, int]]] = {}
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                terms = group.get("terms")
                values = group.get("values")
                if not isinstance(terms, list) or not isinstance(values, list):
                    continue
                bounded_terms = tuple(term for term in terms if isinstance(term, str))
                bounded_values = tuple(str(value) for value in values)
                if set(bounded_values) <= excluded_values:
                    continue
                group_spans = {
                    span for term in bounded_terms for span in _term_spans(term, lowered)
                }
                if group_spans:
                    candidate = (bounded_values, bounded_terms)
                    selected.append(candidate)
                    spans.setdefault(candidate, set()).update(group_spans)
            selected = list(dict.fromkeys(selected))
            selected = _without_contained_mentions(selected, spans)
            folded_preferences = tuple(term.casefold() for term in preferred_terms)
            preferred = [
                candidate
                for candidate in selected
                if any(value.casefold() in folded_preferences for value in candidate[0])
                or any(
                    _term_stated(term, preferred_term)
                    for preferred_term in folded_preferences
                    for term in candidate[1]
                )
            ]
            if preferred:
                selected = preferred
            if len(selected) > 1:
                most_specific = tuple(
                    candidate
                    for candidate in selected
                    if all(
                        set(candidate[0]) < set(other[0])
                        for other in selected
                        if other != candidate
                    )
                )
                selected = list(most_specific) if len(most_specific) == 1 else selected
            if len(selected) != 1 or not 1 <= len(selected[0][0]) <= MAX_GROUNDED_FILTER_VALUES:
                continue
            matched[(object_type, property_name)] = tuple(sorted(set(selected[0][0])))
    return matched


def stated_value_term_spans(
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
    *,
    object_type: str = "Resource",
    property_name: str = "type",
) -> tuple[tuple[int, int], ...]:
    """Return every source span where a declared value term of one property is stated."""

    lowered = utterance.casefold()
    if len(lowered) != len(utterance):
        return ()
    spans: set[tuple[int, int]] = set()
    for descriptor in descriptors:
        if descriptor.get("kind") != "object" or descriptor.get("name") != object_type:
            continue
        properties = descriptor.get("properties")
        declaration = properties.get(property_name) if isinstance(properties, Mapping) else None
        groups = declaration.get("value_groups") if isinstance(declaration, Mapping) else None
        for group in groups if isinstance(groups, list) else ():
            terms = group.get("terms") if isinstance(group, Mapping) else None
            for term in terms if isinstance(terms, list) else ():
                if isinstance(term, str):
                    spans.update(_term_spans(term, lowered))
    return tuple(sorted(spans))


def resource_type_filters_are_bound(
    resource_type_filters: Sequence[str],
    descriptors: Sequence[Mapping[str, Any]],
) -> bool:
    """Require every typed Resource filter to bind from its exact source value."""

    return all(
        bool(
            stated_value_filters(
                value,
                descriptors,
                allowed_properties=frozenset({"type"}),
                preferred_terms=(value,),
            ).get(("Resource", "type"), ())
        )
        for value in resource_type_filters
    )


def _term_stated(term: str, lowered_utterance: str) -> bool:
    """Report whether ``term`` stands on its own inside the utterance.

    Korean writes without spaces between a noun and its particle, so a bare
    substring test is correct there. An ASCII term needs a boundary or a short
    word such as `vm` would match inside an unrelated identifier.
    """
    return bool(_term_spans(term, lowered_utterance))


def _term_spans(term: str, lowered_utterance: str) -> tuple[tuple[int, int], ...]:
    """Return every bounded occurrence of ``term``, including its regular English plural.

    An ASCII edge must not continue a larger identifier: a letter or digit, or a joiner
    such as ``-`` followed by one, makes `aks` inside `aks-prod-01` part of a name rather
    than a stated type.
    """
    needle = term.casefold().strip()
    if not needle:
        return ()
    variants = [needle]
    if needle.isascii() and needle[-1].isalpha():
        if needle.endswith("y") and len(needle) > 1 and needle[-2] not in "aeiou":
            variants.append(f"{needle[:-1]}ies")
        elif needle.endswith(("s", "x", "z", "ch", "sh")):
            variants.append(f"{needle}es")
        else:
            variants.append(f"{needle}s")
    spans: set[tuple[int, int]] = set()
    for variant in variants:
        start = lowered_utterance.find(variant)
        while start != -1:
            end = start + len(variant)
            if (
                not _ascii_alphanumeric(variant[0])
                or not _continues_identifier(lowered_utterance, start - 1, step=-1)
            ) and (
                not _ascii_alphanumeric(variant[-1])
                or not _continues_identifier(lowered_utterance, end, step=1)
            ):
                spans.add((start, end))
            start = lowered_utterance.find(variant, start + 1)
    return tuple(sorted(spans))


def _continues_identifier(lowered_utterance: str, index: int, *, step: int) -> bool:
    if not 0 <= index < len(lowered_utterance):
        return False
    character = lowered_utterance[index]
    if _ascii_alphanumeric(character):
        return True
    neighbor = index + step
    return (
        character in _IDENTIFIER_JOINERS
        and 0 <= neighbor < len(lowered_utterance)
        and _ascii_alphanumeric(lowered_utterance[neighbor])
    )


def _without_contained_mentions(
    candidates: list[tuple[tuple[str, ...], tuple[str, ...]]],
    spans: Mapping[tuple[tuple[str, ...], tuple[str, ...]], set[tuple[int, int]]],
) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Drop a group stated only inside a longer term of another group.

    `virtual machine` inside `virtual machine scale sets` states the scale-set group,
    not a second, competing virtual-machine group.
    """

    def contained(inner: tuple[int, int], outer: tuple[int, int]) -> bool:
        return (
            outer[0] <= inner[0]
            and inner[1] <= outer[1]
            and outer[1] - outer[0] > inner[1] - inner[0]
        )

    return [
        candidate
        for candidate in candidates
        if not all(
            any(
                contained(span, other_span)
                for other in candidates
                if other != candidate
                for other_span in spans.get(other, ())
            )
            for span in spans.get(candidate, ())
        )
    ]


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
    allowed_properties: frozenset[str] | None = None,
) -> tuple[OntologyQueryPlan, tuple[str, ...]]:
    """Constrain an existence predicate the operator already stated a value for.

    A bare existence predicate over a required property selects the whole
    ObjectType, so a stated filter would be answered with an unfiltered
    superset. Rewriting it can only narrow the result, and every operand comes
    from the declared domain the verifier checks.
    """
    filters = stated_value_filters(
        utterance,
        descriptors,
        allowed_properties=allowed_properties,
    )
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
    allowed_properties: frozenset[str] | None = None,
) -> None:
    """Reject model-proposed enum operands that the operator did not state."""
    filters = stated_value_filters(
        utterance,
        descriptors,
        allowed_properties=allowed_properties,
    )
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
