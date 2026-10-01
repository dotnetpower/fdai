"""Project the CSP-neutral resource-type vocabulary as a planner value domain.

`Resource.type` stores catalog-declared subtype ids. Without the declared value
set a planner emits the operator's own family word as a predicate operand and
the query silently matches nothing, so the composition root binds the catalog
vocabulary to that property.
"""

from __future__ import annotations

from enum import StrEnum

from fdai.core.ontology_platform.property_values import PropertyValueDomain, PropertyValueGroup
from fdai.core.rca.hypothesis import CausalHypothesisStatus
from fdai.core.recovery.models import RecoveryPlanStatus
from fdai.rule_catalog.schema.provider_region import ProviderRegionRegistry
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.contracts.models import IncidentState
from fdai.shared.providers.process_runtime import ProcessStatus

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


def resource_location_value_domains(
    registry: ProviderRegionRegistry,
) -> tuple[PropertyValueDomain, ...]:
    """Return the `Resource.location` domain: every reviewed region code and its name."""

    return (
        PropertyValueDomain(
            object_type=_RESOURCE_OBJECT_TYPE,
            property_name="location",
            values=tuple(item.id for item in registry.regions),
            groups=tuple(
                PropertyValueGroup(id=item.id, values=(item.id,), terms=(item.display_name,))
                for item in registry.regions
            ),
        ),
    )


# Each ObjectType whose projection writes a canonical status enum, with that enum.
_LIFECYCLE_ENUMS: tuple[tuple[str, type[StrEnum]], ...] = (
    ("CausalHypothesis", CausalHypothesisStatus),
    ("Incident", IncidentState),
    ("Process", ProcessStatus),
    ("RecoveryPlan", RecoveryPlanStatus),
)


def lifecycle_value_domains() -> tuple[PropertyValueDomain, ...]:
    """Return the reviewed `status` lifecycle domain of every projected ObjectType."""

    return tuple(
        PropertyValueDomain(
            object_type=object_type,
            property_name="status",
            values=tuple(sorted(item.value for item in enum)),
            lifecycle_state=True,
        )
        for object_type, enum in _LIFECYCLE_ENUMS
    )


__all__ = [
    "lifecycle_value_domains",
    "resource_location_value_domains",
    "resource_type_value_domains",
]
