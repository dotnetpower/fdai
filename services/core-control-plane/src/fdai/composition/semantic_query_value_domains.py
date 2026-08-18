"""Project the CSP-neutral resource-type vocabulary as a planner value domain.

`Resource.type` stores catalog-declared subtype ids. Without the declared value
set a planner emits the operator's own family word as a predicate operand and
the query silently matches nothing, so the composition root binds the catalog
vocabulary to that property.
"""

from __future__ import annotations

from fdai.core.ontology_platform.property_values import PropertyValueDomain, PropertyValueGroup
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry

_RESOURCE_OBJECT_TYPE = "Resource"
_RESOURCE_TYPE_PROPERTY = "type"


def resource_type_value_domains(
    registry: ResourceTypeRegistry,
) -> tuple[PropertyValueDomain, ...]:
    """Return the `Resource.type` domain with its category and query groups."""

    values = tuple(sorted({entry.id for entry in registry.types}))
    if not values:
        return ()
    members: dict[str, set[str]] = {}
    for entry in registry.types:
        members.setdefault(entry.category.value, set()).add(entry.id)
    terms = {
        category.value: tuple(items) for category, items in registry.category_query_terms.items()
    }
    groups = [
        PropertyValueGroup(
            id=category,
            values=tuple(sorted(ids)),
            terms=tuple(sorted(set(terms.get(category, ())))),
        )
        for category, ids in sorted(members.items())
    ]
    declared = set(values)
    groups.extend(
        PropertyValueGroup(
            id=group.id,
            values=tuple(sorted(set(group.members))),
            terms=tuple(sorted(set(group.terms))),
        )
        for group in registry.query_groups
        if set(group.members) <= declared
    )
    # One single-value group per type that declares its own request terms. A
    # category group answers "storage resources" but nothing maps the words an
    # operator actually types for one subtype, so a planner that may not invent
    # an operand falls back to an existence predicate and selects everything.
    group_ids = {group.id for group in groups}
    groups.extend(
        PropertyValueGroup(
            id=entry.id,
            values=(entry.id,),
            terms=tuple(sorted(set(entry.query_terms))),
        )
        for entry in sorted(registry.types, key=lambda item: item.id)
        if entry.query_terms and entry.id not in group_ids
    )
    return (
        PropertyValueDomain(
            object_type=_RESOURCE_OBJECT_TYPE,
            property_name=_RESOURCE_TYPE_PROPERTY,
            values=values,
            groups=tuple(sorted(groups, key=lambda item: item.id)),
        ),
    )


__all__ = ["resource_type_value_domains"]
