"""Ground the lifecycle state of an ObjectType other than Resource.

A Resource state is read by the reviewed state inventory. Another ObjectType's lifecycle
state is a property whose reviewed value domain the manifest marks as that type's
lifecycle state, such as `Incident.status`. A concept chooser grounds a state mention
over those values; each value names its ObjectType and property, so the compiler reads
it only as an exact predicate on that ObjectType and never on another subject.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_PREFIX = "lifecycle:"
_VALUE = re.compile(
    r"^lifecycle:(?P<object_type>[A-Z][A-Za-z0-9]{0,63})"
    r"\.(?P<property_name>[a-z][a-z0-9_]{0,63})=(?P<value>[^\s=]{1,128})$"
)


@dataclass(frozen=True, slots=True)
class LifecycleValue:
    """One reviewed lifecycle value of one ObjectType property."""

    object_type: str
    property_name: str
    value: str

    @property
    def concept(self) -> str:
        return f"{_PREFIX}{self.object_type}.{self.property_name}={self.value}"


def parse_lifecycle(concept: str) -> LifecycleValue | None:
    """Return the lifecycle value a grounded state concept names, or ``None``."""

    match = _VALUE.fullmatch(concept)
    if match is None:
        return None
    return LifecycleValue(match["object_type"], match["property_name"], match["value"])


def lifecycle_values(descriptors: Sequence[Mapping[str, Any]]) -> tuple[LifecycleValue, ...]:
    """Return every reviewed lifecycle value the manifest declares, in stable order."""

    found: list[LifecycleValue] = []
    for item in descriptors:
        properties = item.get("properties") if item.get("kind") == "object" else None
        if not isinstance(properties, Mapping):
            continue
        for name, facet in properties.items():
            if not isinstance(facet, Mapping) or facet.get("lifecycle_state") is not True:
                continue
            values = facet.get("values")
            if not isinstance(values, list):
                continue
            for value in values:
                parsed = parse_lifecycle(f"{_PREFIX}{item.get('name')}.{name}={value}")
                if parsed is not None:
                    found.append(parsed)
    return tuple(sorted(found, key=lambda value: value.concept))


def lifecycle_predicates(
    concepts: Sequence[str], selector: str
) -> tuple[list[dict[str, Any]], str | None]:
    """Return one exact predicate per lifecycle property the concepts restrict on ``selector``.

    A row holds one value of each property, so the values stated for one property read
    as a union and the properties restrict together. A reason means the concepts mix
    lifecycle values with other states or name another ObjectType's lifecycle.
    """

    parsed = [parse_lifecycle(item) for item in concepts]
    if not all(parsed):
        return [], "state_filter_domain_unsupported"
    stated: dict[str, set[str]] = {}
    for item in parsed:
        if item is None or item.object_type != selector:
            return [], "state_filter_subject_mismatch"
        stated.setdefault(item.property_name, set()).add(item.value)
    predicates: list[dict[str, Any]] = []
    for property_name, values in sorted(stated.items()):
        ordered = sorted(values)
        predicates.append(
            {"property": property_name, "operator": "equals", "equals": ordered[0]}
            if len(ordered) == 1
            else {"property": property_name, "operator": "in", "values": ordered}
        )
    return predicates, None


__all__ = ["LifecycleValue", "lifecycle_predicates", "lifecycle_values", "parse_lifecycle"]
