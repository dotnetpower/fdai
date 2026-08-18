"""Declared value domains for readable ObjectType properties.

A planner can name a property but cannot invent one of its values. A domain
projects the catalog-declared value set, plus the named subsets an ordinary
request refers to, into the principal manifest so the plan verifier can reject
an operand the catalog never declared.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_MAX_VALUES = 512
_MAX_GROUPS = 64
_MAX_TERMS = 64
_MAX_TEXT = 128


@dataclass(frozen=True, slots=True)
class PropertyValueGroup:
    """One named subset of a value domain and the request terms that select it."""

    id: str
    values: tuple[str, ...]
    terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_identifier(self.id, "property value group id")
        _bounded_sorted_unique(self.values, "property value group values", maximum=_MAX_VALUES)
        if not self.values:
            raise ValueError("property value group MUST declare at least one value")
        _bounded_sorted_unique(self.terms, "property value group terms", maximum=_MAX_TERMS)


@dataclass(frozen=True, slots=True)
class PropertyValueDomain:
    """The complete declared value set for one readable ObjectType property."""

    object_type: str
    property_name: str
    values: tuple[str, ...]
    groups: tuple[PropertyValueGroup, ...] = ()

    def __post_init__(self) -> None:
        _bounded_identifier(self.object_type, "property value domain object type")
        _bounded_identifier(self.property_name, "property value domain property")
        _bounded_sorted_unique(self.values, "property value domain values", maximum=_MAX_VALUES)
        if not self.values:
            raise ValueError("property value domain MUST declare at least one value")
        if len(self.groups) > _MAX_GROUPS:
            raise ValueError(f"property value domain MUST declare at most {_MAX_GROUPS} groups")
        group_ids = tuple(group.id for group in self.groups)
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("property value domain group ids MUST be unique")
        declared = set(self.values)
        for group in self.groups:
            if not set(group.values) <= declared:
                raise ValueError("property value group values MUST belong to the domain")

    def projection(self) -> dict[str, Any]:
        """Return the manifest facet a planner reads for this property."""

        facet: dict[str, Any] = {"values": list(self.values)}
        if self.groups:
            facet["value_groups"] = [
                {"id": group.id, "terms": list(group.terms), "values": list(group.values)}
                for group in sorted(self.groups, key=lambda item: item.id)
            ]
        return facet


def property_value_index(
    domains: Sequence[PropertyValueDomain],
) -> dict[tuple[str, str], PropertyValueDomain]:
    """Return one domain per (ObjectType, property) and reject a duplicate binding."""

    index: dict[tuple[str, str], PropertyValueDomain] = {}
    for domain in domains:
        key = (domain.object_type, domain.property_name)
        if key in index:
            raise ValueError("property value domains MUST bind each property once")
        index[key] = domain
    return index


def declared_property_values(descriptor_property: object) -> frozenset[str] | None:
    """Return the declared values a manifest property carries, or ``None``."""

    if not isinstance(descriptor_property, Mapping):
        return None
    values = descriptor_property.get("values")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return None
    return frozenset(str(item) for item in values)


def _bounded_identifier(value: str, label: str) -> None:
    if not value or len(value) > _MAX_TEXT:
        raise ValueError(f"{label} MUST be non-empty and bounded")


def _bounded_sorted_unique(values: tuple[str, ...], label: str, *, maximum: int) -> None:
    if len(values) > maximum:
        raise ValueError(f"{label} MUST contain at most {maximum} entries")
    if any(not item or len(item) > _MAX_TEXT for item in values):
        raise ValueError(f"{label} MUST be non-empty and bounded")
    if len(values) != len(set(values)) or tuple(sorted(values)) != values:
        raise ValueError(f"{label} MUST be sorted and unique")


__all__ = [
    "PropertyValueDomain",
    "PropertyValueGroup",
    "declared_property_values",
    "property_value_index",
]
