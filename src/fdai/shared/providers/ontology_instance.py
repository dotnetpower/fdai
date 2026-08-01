"""Typed runtime ontology instance store and bounded query contract."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyDeclarationKind,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
    OntologyTypeRef,
    PropertyType,
)

OntologyDirection = Literal["outgoing", "incoming", "both"]
_MAX_JSON_DEPTH = 32


@dataclass(frozen=True, slots=True)
class OntologyObjectRecord:
    """One validated runtime instance of an ``OntologyObjectType``."""

    id: str
    object_type: str
    properties: Mapping[str, Any]
    revision: int = 0
    type_ref: OntologyTypeRef | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("OntologyObjectRecord.id MUST be non-empty")
        if not self.object_type.strip():
            raise ValueError("OntologyObjectRecord.object_type MUST be non-empty")
        if self.revision < 0:
            raise ValueError("OntologyObjectRecord.revision MUST be >= 0")
        if self.type_ref is not None and (
            self.type_ref.kind is not OntologyDeclarationKind.OBJECT
            or self.type_ref.name != self.object_type
        ):
            raise ValueError("OntologyObjectRecord.type_ref MUST match object_type")


@dataclass(frozen=True, slots=True)
class OntologyLinkRecord:
    """One typed relationship between two ontology object instances."""

    link_type: str
    from_id: str
    to_id: str
    properties: Mapping[str, Any] = field(default_factory=dict)
    type_ref: OntologyTypeRef | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("link_type", self.link_type),
            ("from_id", self.from_id),
            ("to_id", self.to_id),
        ):
            if not value.strip():
                raise ValueError(f"OntologyLinkRecord.{field_name} MUST be non-empty")
        if self.type_ref is not None and (
            self.type_ref.kind is not OntologyDeclarationKind.LINK
            or self.type_ref.name != self.link_type
        ):
            raise ValueError("OntologyLinkRecord.type_ref MUST match link_type")


@dataclass(frozen=True, slots=True)
class OntologyGraphSnapshot:
    """Bounded result of an ontology instance query or traversal."""

    objects: tuple[OntologyObjectRecord, ...] = ()
    links: tuple[OntologyLinkRecord, ...] = ()
    truncated: bool = False


class OntologyInstanceValidationError(ValueError):
    """An instance does not satisfy its registered ontology declaration."""


def normalize_json_value(
    value: Any,
    *,
    path: str = "value",
    _depth: int = 0,
) -> Any:
    """Return deterministic JSON data or fail closed on unsupported values."""

    if _depth > _MAX_JSON_DEPTH:
        raise OntologyInstanceValidationError(
            f"{path} exceeds maximum JSON nesting depth {_MAX_JSON_DEPTH}"
        )

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OntologyInstanceValidationError(f"{path} MUST contain finite numbers")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise OntologyInstanceValidationError(f"{path} datetime MUST be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise OntologyInstanceValidationError(f"{path} mapping keys MUST be strings")
        normalized: dict[str, Any] = {}
        for key in sorted(value):
            normalized[key] = normalize_json_value(
                value[key], path=f"{path}.{key}", _depth=_depth + 1
            )
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            normalize_json_value(item, path=f"{path}[{index}]", _depth=_depth + 1)
            for index, item in enumerate(value)
        ]
    raise OntologyInstanceValidationError(
        f"{path} MUST contain canonical JSON data, got {type(value).__name__}"
    )


def canonical_json_mapping(value: Mapping[str, Any], *, path: str) -> tuple[dict[str, Any], str]:
    """Normalize and encode one mapping using the replay-stable JSON form."""

    normalized = normalize_json_value(value, path=path)
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping always normalizes to dict
        raise OntologyInstanceValidationError(f"{path} MUST be a JSON object")
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return normalized, encoded


def normalize_object_record(record: OntologyObjectRecord) -> OntologyObjectRecord:
    properties, _ = canonical_json_mapping(
        record.properties,
        path=f"{record.object_type}.properties",
    )
    return OntologyObjectRecord(
        id=record.id,
        object_type=record.object_type,
        properties=properties,
        revision=record.revision,
        type_ref=record.type_ref,
    )


def normalize_link_record(record: OntologyLinkRecord) -> OntologyLinkRecord:
    properties, _ = canonical_json_mapping(
        record.properties,
        path=f"{record.link_type}.properties",
    )
    return OntologyLinkRecord(
        link_type=record.link_type,
        from_id=record.from_id,
        to_id=record.to_id,
        properties=properties,
        type_ref=record.type_ref,
    )


def pin_object_record(
    record: OntologyObjectRecord,
    release: OntologyRelease,
) -> OntologyObjectRecord:
    expected = release.type_ref(OntologyDeclarationKind.OBJECT, record.object_type)
    if record.type_ref is not None and record.type_ref != expected:
        raise OntologyInstanceValidationError(
            f"{record.object_type} type_ref does not match the active ontology release"
        )
    return replace(record, type_ref=expected)


def pin_link_record(
    record: OntologyLinkRecord,
    release: OntologyRelease,
) -> OntologyLinkRecord:
    expected = release.type_ref(OntologyDeclarationKind.LINK, record.link_type)
    if record.type_ref is not None and record.type_ref != expected:
        raise OntologyInstanceValidationError(
            f"{record.link_type} type_ref does not match the active ontology release"
        )
    return replace(record, type_ref=expected)


def validate_object_record(
    record: OntologyObjectRecord,
    object_types: Mapping[str, OntologyObjectType],
) -> None:
    """Validate key, required, unknown, and property types at the write boundary."""

    canonical_json_mapping(record.properties, path=f"{record.object_type}.properties")
    declaration = object_types.get(record.object_type)
    if declaration is None:
        raise OntologyInstanceValidationError(
            f"unknown ontology object type {record.object_type!r}"
        )
    unknown = set(record.properties) - set(declaration.properties)
    if unknown:
        raise OntologyInstanceValidationError(
            f"{record.object_type} has undeclared properties: {', '.join(sorted(unknown))}"
        )
    missing = [
        name
        for name, property_decl in declaration.properties.items()
        if property_decl.required and name not in record.properties
    ]
    if missing:
        raise OntologyInstanceValidationError(
            f"{record.object_type} is missing required properties: {', '.join(sorted(missing))}"
        )
    key_value = record.properties.get(declaration.key)
    if key_value != record.id:
        raise OntologyInstanceValidationError(
            f"{record.object_type}.{declaration.key} MUST equal instance id {record.id!r}"
        )
    for name, value in record.properties.items():
        expected = declaration.properties[name].type
        if not _matches_property_type(value, expected):
            raise OntologyInstanceValidationError(
                f"{record.object_type}.{name} MUST be {expected.value}, got {type(value).__name__}"
            )


def validate_link_record(
    record: OntologyLinkRecord,
    *,
    link_types: Mapping[str, OntologyLinkType],
    objects: Mapping[str, OntologyObjectRecord],
    existing_links: Sequence[OntologyLinkRecord] = (),
) -> None:
    """Validate link declaration, endpoints, properties, and cardinality."""

    canonical_json_mapping(record.properties, path=f"{record.link_type}.properties")
    declaration = link_types.get(record.link_type)
    if declaration is None:
        raise OntologyInstanceValidationError(f"unknown ontology link type {record.link_type!r}")
    source = objects.get(record.from_id)
    target = objects.get(record.to_id)
    if source is None or target is None:
        missing = [
            identifier for identifier in (record.from_id, record.to_id) if identifier not in objects
        ]
        raise OntologyInstanceValidationError(
            f"ontology link endpoints do not exist: {', '.join(missing)}"
        )
    if source.object_type != declaration.from_type or target.object_type != declaration.to_type:
        raise OntologyInstanceValidationError(
            f"{record.link_type} requires {declaration.from_type}->{declaration.to_type}, "
            f"got {source.object_type}->{target.object_type}"
        )
    _validate_cardinality(record, declaration=declaration, existing_links=existing_links)


def _validate_cardinality(
    record: OntologyLinkRecord,
    *,
    declaration: OntologyLinkType,
    existing_links: Sequence[OntologyLinkRecord],
) -> None:
    for existing in existing_links:
        if existing.link_type != record.link_type:
            continue
        if existing.from_id == record.from_id and existing.to_id == record.to_id:
            continue
        source_conflict = existing.from_id == record.from_id
        target_conflict = existing.to_id == record.to_id
        cardinality = declaration.cardinality
        if cardinality is LinkCardinality.ONE_TO_ONE and (source_conflict or target_conflict):
            break
        if cardinality is LinkCardinality.ONE_TO_MANY and target_conflict:
            break
        if cardinality is LinkCardinality.MANY_TO_ONE and source_conflict:
            break
    else:
        return
    raise OntologyInstanceValidationError(
        f"{record.link_type} violates {declaration.cardinality.value} cardinality"
    )


def can_repeat_link(previous_link_type: str | None, current: OntologyLinkType) -> bool:
    """Return whether traversal may follow ``current`` after the same LinkType."""

    return previous_link_type != current.name or current.is_transitive


def ontology_link_sort_key(
    link: OntologyLinkRecord,
    *,
    link_types: Mapping[str, OntologyLinkType],
    objects: Mapping[str, OntologyObjectRecord],
) -> tuple[str, str, int, float, str, str]:
    """Order temporal links by their declared target property, then identity."""

    declaration = link_types[link.link_type]
    value = None
    if declaration.temporal_order and declaration.order_by_property is not None:
        target = objects.get(link.to_id)
        if target is not None:
            value = target.properties.get(declaration.order_by_property)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (link.link_type, link.from_id, 0, float(value), "", link.to_id)
    if isinstance(value, str):
        return (link.link_type, link.from_id, 1, 0.0, value, link.to_id)
    return (link.link_type, link.from_id, 2, 0.0, "", link.to_id)


def _matches_property_type(value: Any, expected: PropertyType) -> bool:
    if expected is PropertyType.STRING:
        return isinstance(value, str)
    if expected is PropertyType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is PropertyType.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is PropertyType.BOOLEAN:
        return isinstance(value, bool)
    if expected is PropertyType.OBJECT:
        return isinstance(value, Mapping)
    if expected is PropertyType.ARRAY:
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
    if expected is PropertyType.DATETIME:
        if isinstance(value, datetime):
            return value.tzinfo is not None
        if not isinstance(value, str):
            return False
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
        except ValueError:
            return False
    return False


@runtime_checkable
class OntologyInstanceStore(Protocol):
    """Persist and query the current typed ontology instance graph."""

    async def upsert_object(
        self,
        record: OntologyObjectRecord,
        *,
        expected_revision: int | None = None,
    ) -> OntologyObjectRecord:
        """Insert or update one object with optional optimistic concurrency."""
        ...

    async def upsert_link(self, record: OntologyLinkRecord) -> None:
        """Idempotently insert or replace one typed link."""
        ...

    async def replace_subgraph(
        self,
        *,
        objects: Sequence[OntologyObjectRecord],
        links: Sequence[OntologyLinkRecord],
        previous_object_ids: Sequence[str] = (),
        previous_link_keys: Sequence[tuple[str, str, str]] = (),
    ) -> None:
        """Atomically replace one caller-owned subgraph or write nothing."""
        ...

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        """Return one object by id."""
        ...

    async def delete_object(self, object_id: str) -> bool:
        """Delete one object and every incident link; return whether it existed."""
        ...

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        limit: int = 100,
    ) -> OntologyGraphSnapshot:
        """Return a bounded object selection and internal links."""
        ...

    async def traverse(
        self,
        *,
        root_ids: Sequence[str],
        link_types: Sequence[str] = (),
        direction: OntologyDirection = "outgoing",
        max_depth: int = 1,
        limit: int = 500,
    ) -> OntologyGraphSnapshot:
        """Traverse a bounded subgraph from one or more roots."""
        ...


__all__ = [
    "canonical_json_mapping",
    "can_repeat_link",
    "OntologyDirection",
    "OntologyGraphSnapshot",
    "OntologyInstanceStore",
    "OntologyInstanceValidationError",
    "OntologyLinkRecord",
    "OntologyObjectRecord",
    "normalize_json_value",
    "normalize_link_record",
    "normalize_object_record",
    "pin_link_record",
    "pin_object_record",
    "ontology_link_sort_key",
    "validate_link_record",
    "validate_object_record",
]
