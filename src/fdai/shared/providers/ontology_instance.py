"""Typed runtime ontology instance store and bounded query contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType, PropertyType

OntologyDirection = Literal["outgoing", "incoming", "both"]


@dataclass(frozen=True, slots=True)
class OntologyObjectRecord:
    """One validated runtime instance of an ``OntologyObjectType``."""

    id: str
    object_type: str
    properties: Mapping[str, Any]
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("OntologyObjectRecord.id MUST be non-empty")
        if not self.object_type.strip():
            raise ValueError("OntologyObjectRecord.object_type MUST be non-empty")
        if self.revision < 0:
            raise ValueError("OntologyObjectRecord.revision MUST be >= 0")


@dataclass(frozen=True, slots=True)
class OntologyLinkRecord:
    """One typed relationship between two ontology object instances."""

    link_type: str
    from_id: str
    to_id: str
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("link_type", self.link_type),
            ("from_id", self.from_id),
            ("to_id", self.to_id),
        ):
            if not value.strip():
                raise ValueError(f"OntologyLinkRecord.{field_name} MUST be non-empty")


@dataclass(frozen=True, slots=True)
class OntologyGraphSnapshot:
    """Bounded result of an ontology instance query or traversal."""

    objects: tuple[OntologyObjectRecord, ...] = ()
    links: tuple[OntologyLinkRecord, ...] = ()
    truncated: bool = False


class OntologyInstanceValidationError(ValueError):
    """An instance does not satisfy its registered ontology declaration."""


def validate_object_record(
    record: OntologyObjectRecord,
    object_types: Mapping[str, OntologyObjectType],
) -> None:
    """Validate key, required, unknown, and property types at the write boundary."""

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
) -> None:
    """Validate link declaration and endpoint object types."""

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

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        """Return one object by id."""
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
    "OntologyDirection",
    "OntologyGraphSnapshot",
    "OntologyInstanceStore",
    "OntologyInstanceValidationError",
    "OntologyLinkRecord",
    "OntologyObjectRecord",
    "validate_link_record",
    "validate_object_record",
]
