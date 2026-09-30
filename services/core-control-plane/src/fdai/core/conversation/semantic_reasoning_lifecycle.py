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


def lifecycle_predicate(
    concepts: Sequence[str], selector: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Return the exact predicate for grounded lifecycle concepts on ``selector``.

    ``(None, None)`` means the concepts name no lifecycle value; a reason means they
    mix lifecycle values with other states or name another ObjectType's lifecycle.
    """

    parsed = [parse_lifecycle(item) for item in concepts]
    if not any(parsed):
        return None, None
    if not all(parsed):
        return None, "state_filter_domain_unsupported"
    values = [item for item in parsed if item is not None]
    targets = {(item.object_type, item.property_name) for item in values}
    if len(targets) != 1 or next(iter(targets))[0] != selector:
        return None, "state_filter_subject_mismatch"
    ((_object_type, property_name),) = targets
    stated = sorted({item.value for item in values})
    if len(stated) == 1:
        return {"property": property_name, "operator": "equals", "equals": stated[0]}, None
    return {"property": property_name, "operator": "in", "values": stated}, None


__all__ = ["LifecycleValue", "lifecycle_predicate", "lifecycle_values", "parse_lifecycle"]
