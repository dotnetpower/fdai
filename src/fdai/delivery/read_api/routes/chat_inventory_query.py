"""Verified typed queries for current inventory and resource activity."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final


class InventoryQuerySource(StrEnum):
    """Authoritative read source selected for an inventory query."""

    CURRENT = "current"
    ACTIVITY = "activity"


class InventoryQueryKind(StrEnum):
    """Bounded result shapes supported by the inventory renderer."""

    LIST = "list"
    COUNT = "count"
    TYPES = "types"
    RELATIONSHIPS = "relationships"


class InventoryQueryScope(StrEnum):
    """Server-owned inventory boundary selected by the typed query."""

    ACTIVE_VIEW = "active_view"
    SUBSCRIPTION = "subscription"


class InventoryQueryGrouping(StrEnum):
    """Evidence-backed grouping requested for deterministic rendering."""

    NONE = "none"
    RESOURCE_TYPE = "resource_type"
    STATUS = "status"
    LOCATION = "location"


class InventoryQueryProjection(StrEnum):
    """Bounded detail projection selected before evidence retrieval."""

    DETAILS = "details"
    NAMES = "names"


class InventoryField(StrEnum):
    """Allowlisted fields a query predicate may inspect."""

    RESOURCE_TYPE = "resource_type"
    STATUS = "status"
    NAME = "name"
    RESOURCE_GROUP = "resource_group"
    LOCATION = "location"
    OPERATION = "operation"
    EVENT_STATUS = "event_status"


class InventoryOperator(StrEnum):
    """Read-only predicate operators accepted by the verifier."""

    EQ = "eq"
    NE = "ne"
    IN = "in"
    CONTAINS = "contains"
    EXISTS = "exists"
    MISSING = "missing"


_CURRENT_FIELDS: Final = frozenset(
    {
        InventoryField.RESOURCE_TYPE,
        InventoryField.STATUS,
        InventoryField.NAME,
        InventoryField.RESOURCE_GROUP,
        InventoryField.LOCATION,
    }
)
_ACTIVITY_FIELDS: Final = frozenset(
    {
        InventoryField.RESOURCE_TYPE,
        InventoryField.NAME,
        InventoryField.RESOURCE_GROUP,
        InventoryField.OPERATION,
        InventoryField.EVENT_STATUS,
    }
)
_VALUE_OPERATORS: Final = frozenset(
    {
        InventoryOperator.EQ,
        InventoryOperator.NE,
        InventoryOperator.IN,
        InventoryOperator.CONTAINS,
    }
)
_MAX_PREDICATES: Final = 8
_MAX_VALUES: Final = 16
_MAX_VALUE_CHARS: Final = 256
_MIN_ACTIVITY_LOOKBACK_SECONDS: Final = 3_600
MAX_ACTIVITY_LOOKBACK_SECONDS: Final = 30 * 24 * 3_600
_FIELD_KEYS: Final[dict[InventoryField, str]] = {
    InventoryField.RESOURCE_TYPE: "type",
    InventoryField.STATUS: "status",
    InventoryField.NAME: "name",
    InventoryField.RESOURCE_GROUP: "resource_group",
    InventoryField.LOCATION: "location",
    InventoryField.OPERATION: "operation",
    InventoryField.EVENT_STATUS: "event_status",
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class InventoryPredicate:
    """One verified field/operator/value condition."""

    field: InventoryField
    operator: InventoryOperator
    value: str | tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.operator in _VALUE_OPERATORS and self.value is None:
            raise ValueError(f"inventory predicate {self.operator.value} requires a value")
        if self.operator not in _VALUE_OPERATORS and self.value is not None:
            raise ValueError(f"inventory predicate {self.operator.value} forbids a value")
        if self.operator is InventoryOperator.IN:
            if not isinstance(self.value, tuple) or not 1 <= len(self.value) <= _MAX_VALUES:
                raise ValueError("inventory predicate in requires 1..16 values")
            normalized = tuple(_bounded_value(item) for item in self.value)
            if len(set(normalized)) != len(normalized):
                raise ValueError("inventory predicate in values MUST be unique")
            object.__setattr__(self, "value", normalized)
        elif isinstance(self.value, str):
            object.__setattr__(self, "value", _bounded_value(self.value))
        elif self.value is not None:
            raise ValueError("inventory predicate value MUST be a string or tuple")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe projection."""

        value: object = list(self.value) if isinstance(self.value, tuple) else self.value
        return {"field": self.field.value, "operator": self.operator.value, "value": value}


@dataclass(frozen=True, slots=True)
class InventoryQueryValueGroup:
    """One catalog semantic group over canonical provider values."""

    id: str
    values: tuple[str, ...]
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_id = _bounded_value(self.id)
        normalized_values = tuple(_bounded_value(value) for value in self.values)
        if not normalized_values or len(set(normalized_values)) != len(normalized_values):
            raise ValueError("inventory query value group requires unique values")
        normalized_labels = {
            _bounded_value(locale): _bounded_label(label) for locale, label in self.labels.items()
        }
        object.__setattr__(self, "id", normalized_id)
        object.__setattr__(self, "values", normalized_values)
        object.__setattr__(self, "labels", MappingProxyType(normalized_labels))


@dataclass(frozen=True, slots=True)
class InventoryQuery:
    """One immutable, bounded, read-only resource query."""

    source: InventoryQuerySource
    kind: InventoryQueryKind
    predicates: tuple[InventoryPredicate, ...] = ()
    lookback_seconds: int | None = None
    scope: InventoryQueryScope = InventoryQueryScope.ACTIVE_VIEW
    group_by: InventoryQueryGrouping = InventoryQueryGrouping.NONE
    projection: InventoryQueryProjection = InventoryQueryProjection.DETAILS
    require_fresh: bool = False
    include_workloads: bool = False
    status_groups: tuple[InventoryQueryValueGroup, ...] = ()

    def __post_init__(self) -> None:
        if len(self.predicates) > _MAX_PREDICATES:
            raise ValueError("inventory query exceeds 8 predicates")
        allowed_fields = (
            _CURRENT_FIELDS if self.source is InventoryQuerySource.CURRENT else _ACTIVITY_FIELDS
        )
        if any(predicate.field not in allowed_fields for predicate in self.predicates):
            raise ValueError(f"inventory query field is invalid for {self.source.value} source")
        if self.source is InventoryQuerySource.CURRENT:
            if self.lookback_seconds is not None:
                raise ValueError("current inventory query MUST NOT carry lookback_seconds")
        elif (
            not isinstance(self.lookback_seconds, int)
            or isinstance(self.lookback_seconds, bool)
            or not _MIN_ACTIVITY_LOOKBACK_SECONDS
            <= self.lookback_seconds
            <= MAX_ACTIVITY_LOOKBACK_SECONDS
        ):
            raise ValueError("activity inventory query lookback_seconds is out of bounds")
        if (
            self.source is InventoryQuerySource.ACTIVITY
            and self.kind is InventoryQueryKind.RELATIONSHIPS
        ):
            raise ValueError("activity inventory query does not support relationships")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> InventoryQuery:
        """Parse one untrusted structured planner result without partial acceptance."""

        if set(raw) - {"source", "kind", "predicates", "lookback_seconds"}:
            raise ValueError("inventory query contains unknown fields")
        if not {"source", "kind", "predicates"}.issubset(raw):
            raise ValueError("inventory query is missing required fields")
        raw_predicates = raw["predicates"]
        if not isinstance(raw_predicates, Sequence) or isinstance(raw_predicates, str | bytes):
            raise ValueError("inventory query predicates MUST be an array")
        predicates = tuple(_predicate_from_mapping(item) for item in raw_predicates)
        lookback = raw.get("lookback_seconds")
        if lookback is not None and (not isinstance(lookback, int) or isinstance(lookback, bool)):
            raise ValueError("inventory query lookback_seconds MUST be an integer or null")
        try:
            return cls(
                source=InventoryQuerySource(str(raw["source"])),
                kind=InventoryQueryKind(str(raw["kind"])),
                predicates=predicates,
                lookback_seconds=lookback,
            )
        except ValueError as exc:
            raise ValueError(f"inventory query is invalid: {exc}") from exc

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe canonical query projection."""

        return {
            "source": self.source.value,
            "kind": self.kind.value,
            "predicates": [predicate.to_dict() for predicate in self.predicates],
            "lookback_seconds": self.lookback_seconds,
        }


def inventory_query_argument_schema() -> dict[str, object]:
    """Return the strict semantic-planner schema for ``query_inventory``."""

    return {
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": [item.value for item in InventoryQuerySource]},
            "kind": {"type": "string", "enum": [item.value for item in InventoryQueryKind]},
            "predicates": {
                "type": "array",
                "maxItems": _MAX_PREDICATES,
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": [item.value for item in InventoryField],
                        },
                        "operator": {
                            "type": "string",
                            "enum": [item.value for item in InventoryOperator],
                        },
                        "value": {
                            "anyOf": [
                                {"type": "string", "maxLength": _MAX_VALUE_CHARS},
                                {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": _MAX_VALUES,
                                    "items": {
                                        "type": "string",
                                        "maxLength": _MAX_VALUE_CHARS,
                                    },
                                },
                                {"type": "null"},
                            ]
                        },
                    },
                    "required": ["field", "operator", "value"],
                    "additionalProperties": False,
                },
            },
            "lookback_seconds": {
                "type": ["integer", "null"],
                "minimum": _MIN_ACTIVITY_LOOKBACK_SECONDS,
                "maximum": MAX_ACTIVITY_LOOKBACK_SECONDS,
            },
        },
        "required": ["source", "kind", "predicates", "lookback_seconds"],
        "additionalProperties": False,
    }


def inventory_query_matches(query: InventoryQuery, record: Mapping[str, Any]) -> bool:
    """Return whether one safe current-resource or activity projection matches."""

    return all(_predicate_matches(record, predicate) for predicate in query.predicates)


def normalize_inventory_value(value: object) -> str:
    """Normalize one provider or query scalar for stable case-insensitive matching."""

    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    text = re.sub(r"[\\/_]+", " ", text)
    return " ".join(text.split())


def _predicate_from_mapping(raw: object) -> InventoryPredicate:
    if not isinstance(raw, Mapping) or set(raw) != {"field", "operator", "value"}:
        raise ValueError("inventory predicate fields are invalid")
    try:
        field = InventoryField(str(raw["field"]))
        operator = InventoryOperator(str(raw["operator"]))
    except ValueError as exc:
        raise ValueError("inventory predicate enum is invalid") from exc
    value = raw["value"]
    if isinstance(value, list):
        if any(not isinstance(item, str) for item in value):
            raise ValueError("inventory predicate array values MUST be strings")
        value = tuple(value)
    return InventoryPredicate(field=field, operator=operator, value=value)


def _bounded_value(value: str) -> str:
    normalized = normalize_inventory_value(value)
    if not normalized or len(normalized) > _MAX_VALUE_CHARS or _CONTROL.search(normalized):
        raise ValueError("inventory predicate value is invalid")
    return normalized


def _bounded_label(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > _MAX_VALUE_CHARS or _CONTROL.search(normalized):
        raise ValueError("inventory query label is invalid")
    return normalized


def _predicate_matches(record: Mapping[str, Any], predicate: InventoryPredicate) -> bool:
    key = _FIELD_KEYS[predicate.field]
    present = key in record and record.get(key) not in (None, "")
    if predicate.operator is InventoryOperator.EXISTS:
        return present
    if predicate.operator is InventoryOperator.MISSING:
        return not present
    if not present:
        return False
    actual = normalize_inventory_value(record[key])
    if predicate.operator is InventoryOperator.EQ:
        return actual == predicate.value
    if predicate.operator is InventoryOperator.NE:
        return actual != predicate.value
    if predicate.operator is InventoryOperator.IN:
        return isinstance(predicate.value, tuple) and actual in predicate.value
    if predicate.operator is InventoryOperator.CONTAINS:
        return isinstance(predicate.value, str) and _contains_token_sequence(
            actual, predicate.value
        )
    return False


def _contains_token_sequence(actual: str, expected: str) -> bool:
    offset = 0
    while (index := actual.find(expected, offset)) >= 0:
        end = index + len(expected)
        left_boundary = index == 0 or not actual[index - 1].isalnum()
        right_boundary = end == len(actual) or not actual[end].isalnum()
        if left_boundary and right_boundary:
            return True
        offset = index + 1
    return False


__all__ = [
    "MAX_ACTIVITY_LOOKBACK_SECONDS",
    "InventoryField",
    "InventoryOperator",
    "InventoryPredicate",
    "InventoryQuery",
    "InventoryQueryGrouping",
    "InventoryQueryKind",
    "InventoryQueryProjection",
    "InventoryQueryScope",
    "InventoryQuerySource",
    "InventoryQueryValueGroup",
    "inventory_query_argument_schema",
    "inventory_query_matches",
    "normalize_inventory_value",
]
