"""Typed normalized observations for inventory journal and deterministic replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

INVENTORY_OBSERVATION_SCHEMA_VERSION = "1.0.0"
_MAX_TEXT = 512
_MAX_PROPERTY_KEYS = 256


class InventoryObservationSubjectKind(StrEnum):
    """Normalized inventory journal subject."""

    OBJECT = "object"
    RELATIONSHIP = "relationship"


class InventoryObservationKind(StrEnum):
    """Completeness and deletion meaning carried by one observation."""

    FULL = "full"
    PARTIAL = "partial"
    CHANGE_HINT = "change_hint"
    TOMBSTONE = "tombstone"


class InventoryMutationKind(StrEnum):
    """Current-projection mutation represented by an observation."""

    UPSERT = "upsert"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class NormalizedInventoryObservation:
    """One content-addressed object or relationship observation."""

    observation_id: str
    content_digest: str
    idempotency_key: str
    subject_kind: InventoryObservationSubjectKind
    observation_kind: InventoryObservationKind
    mutation_kind: InventoryMutationKind
    subject_ref: str
    subject_type: str
    properties_json: str
    property_mask: tuple[str, ...]
    properties_complete: bool
    links_complete: bool
    tombstone_confirmed: bool
    source_identity: str
    source_event_id: str
    source_revision: str
    effective_at: datetime
    observed_at: datetime
    evidence_cutoff: datetime
    recorded_at: datetime
    provider_ref: str | None = None
    scope_ref: str | None = None
    operation: str | None = None
    operation_status: str | None = None
    from_id: str | None = None
    from_type: str | None = None
    link_type: str | None = None
    to_id: str | None = None
    to_type: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("idempotency_key", self.idempotency_key),
            ("subject_ref", self.subject_ref),
            ("subject_type", self.subject_type),
            ("source_identity", self.source_identity),
            ("source_event_id", self.source_event_id),
            ("source_revision", self.source_revision),
        ):
            _bounded_text(field_name, value)
        for field_name, optional_value in (
            ("provider_ref", self.provider_ref),
            ("scope_ref", self.scope_ref),
            ("operation", self.operation),
            ("operation_status", self.operation_status),
        ):
            if optional_value is not None:
                _bounded_text(field_name, optional_value)
        _aware_times(
            self.effective_at,
            self.observed_at,
            self.evidence_cutoff,
            self.recorded_at,
        )
        properties = self.properties
        if self.property_mask != tuple(sorted(set(self.property_mask))):
            raise ValueError("inventory observation property_mask MUST be sorted and unique")
        if len(self.property_mask) > _MAX_PROPERTY_KEYS:
            raise ValueError("inventory observation property_mask exceeds its bound")
        if any(not key or len(key) > 128 for key in self.property_mask):
            raise ValueError("inventory observation property_mask entries MUST be bounded")
        if set(self.property_mask) != set(properties):
            raise ValueError("inventory observation property_mask MUST match observed properties")
        if self.observation_kind is InventoryObservationKind.FULL:
            if (
                self.mutation_kind is not InventoryMutationKind.UPSERT
                or not self.properties_complete
                or self.tombstone_confirmed
            ):
                raise ValueError("full inventory observation semantics are inconsistent")
        elif self.observation_kind in {
            InventoryObservationKind.PARTIAL,
            InventoryObservationKind.CHANGE_HINT,
        }:
            if (
                self.mutation_kind is not InventoryMutationKind.UPSERT
                or self.properties_complete
                or self.tombstone_confirmed
            ):
                raise ValueError("sparse inventory observation semantics are inconsistent")
        elif (
            self.mutation_kind is not InventoryMutationKind.DELETE
            or self.properties_complete
            or properties
            or self.property_mask
        ):
            raise ValueError("tombstone inventory observation semantics are inconsistent")
        relationship_fields = (
            self.from_id,
            self.from_type,
            self.link_type,
            self.to_id,
            self.to_type,
        )
        if self.subject_kind is InventoryObservationSubjectKind.RELATIONSHIP:
            if any(value is None for value in relationship_fields):
                raise ValueError("relationship observation endpoints MUST be complete")
            for relationship_value in relationship_fields:
                _bounded_text("relationship observation endpoint", str(relationship_value))
        elif any(value is not None for value in relationship_fields):
            raise ValueError("object observation MUST NOT carry relationship endpoints")
        if self.content_digest != _digest(self._content_body()):
            raise ValueError("inventory observation content_digest does not match content")
        if self.observation_id != self.content_digest:
            raise ValueError("inventory observation id does not match content digest")

    @property
    def properties(self) -> Mapping[str, Any]:
        value = json.loads(self.properties_json)
        if not isinstance(value, dict):
            raise ValueError("inventory observation properties MUST decode to an object")
        return value

    def _content_body(self) -> dict[str, object]:
        return {
            "schema_version": INVENTORY_OBSERVATION_SCHEMA_VERSION,
            "idempotency_key": self.idempotency_key,
            "subject_kind": self.subject_kind.value,
            "observation_kind": self.observation_kind.value,
            "mutation_kind": self.mutation_kind.value,
            "subject_ref": self.subject_ref,
            "subject_type": self.subject_type,
            "properties": self.properties,
            "property_mask": list(self.property_mask),
            "properties_complete": self.properties_complete,
            "links_complete": self.links_complete,
            "tombstone_confirmed": self.tombstone_confirmed,
            "provider_ref": self.provider_ref,
            "scope_ref": self.scope_ref,
            "operation": self.operation,
            "operation_status": self.operation_status,
            "source_identity": self.source_identity,
            "source_event_id": self.source_event_id,
            "source_revision": self.source_revision,
            "effective_at": self.effective_at.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "evidence_cutoff": self.evidence_cutoff.isoformat(),
            "from_id": self.from_id,
            "from_type": self.from_type,
            "link_type": self.link_type,
            "to_id": self.to_id,
            "to_type": self.to_type,
        }

    @classmethod
    def create(
        cls,
        *,
        idempotency_key: str,
        subject_kind: InventoryObservationSubjectKind,
        observation_kind: InventoryObservationKind,
        mutation_kind: InventoryMutationKind,
        subject_ref: str,
        subject_type: str,
        properties: Mapping[str, Any],
        property_mask: Sequence[str],
        properties_complete: bool,
        links_complete: bool,
        tombstone_confirmed: bool,
        source_identity: str,
        source_event_id: str,
        source_revision: str,
        effective_at: datetime,
        observed_at: datetime,
        evidence_cutoff: datetime,
        recorded_at: datetime,
        provider_ref: str | None = None,
        scope_ref: str | None = None,
        operation: str | None = None,
        operation_status: str | None = None,
        from_id: str | None = None,
        from_type: str | None = None,
        link_type: str | None = None,
        to_id: str | None = None,
        to_type: str | None = None,
    ) -> NormalizedInventoryObservation:
        properties_json = _canonical_json(properties)
        normalized_mask = tuple(sorted(property_mask))
        values: dict[str, Any] = {
            "idempotency_key": idempotency_key,
            "subject_kind": subject_kind,
            "observation_kind": observation_kind,
            "mutation_kind": mutation_kind,
            "subject_ref": subject_ref,
            "subject_type": subject_type,
            "properties_json": properties_json,
            "property_mask": normalized_mask,
            "properties_complete": properties_complete,
            "links_complete": links_complete,
            "tombstone_confirmed": tombstone_confirmed,
            "provider_ref": provider_ref,
            "scope_ref": scope_ref,
            "operation": operation,
            "operation_status": operation_status,
            "source_identity": source_identity,
            "source_event_id": source_event_id,
            "source_revision": source_revision,
            "effective_at": effective_at,
            "observed_at": observed_at,
            "evidence_cutoff": evidence_cutoff,
            "recorded_at": recorded_at,
            "from_id": from_id,
            "from_type": from_type,
            "link_type": link_type,
            "to_id": to_id,
            "to_type": to_type,
        }
        digest = _digest(
            {
                "schema_version": INVENTORY_OBSERVATION_SCHEMA_VERSION,
                "idempotency_key": idempotency_key,
                "subject_kind": subject_kind.value,
                "observation_kind": observation_kind.value,
                "mutation_kind": mutation_kind.value,
                "subject_ref": subject_ref,
                "subject_type": subject_type,
                "properties": json.loads(properties_json),
                "property_mask": list(normalized_mask),
                "properties_complete": properties_complete,
                "links_complete": links_complete,
                "tombstone_confirmed": tombstone_confirmed,
                "provider_ref": provider_ref,
                "scope_ref": scope_ref,
                "operation": operation,
                "operation_status": operation_status,
                "source_identity": source_identity,
                "source_event_id": source_event_id,
                "source_revision": source_revision,
                "effective_at": effective_at.isoformat(),
                "observed_at": observed_at.isoformat(),
                "evidence_cutoff": evidence_cutoff.isoformat(),
                "from_id": from_id,
                "from_type": from_type,
                "link_type": link_type,
                "to_id": to_id,
                "to_type": to_type,
            }
        )
        return cls(observation_id=digest, content_digest=digest, **values)


@dataclass(frozen=True, slots=True)
class InventoryObservationReplay:
    """Deterministic current object state reduced from normalized observations."""

    present: bool
    resource_type: str
    properties_json: str
    provider_ref: str | None
    observed_at: datetime | None
    source_event_id: str | None
    idempotency_key: str | None
    digest: str

    @property
    def properties(self) -> Mapping[str, Any]:
        value = json.loads(self.properties_json)
        if not isinstance(value, dict):
            raise ValueError("inventory replay properties MUST decode to an object")
        return value


class InventoryObservationProjectionJournal(Protocol):
    """Advance the normalized journal's ontology projection watermark."""

    async def mark_ontology_projected(self, *, generation: str, watermark: int) -> None: ...


@dataclass(frozen=True, slots=True)
class InventoryObservationSchemaReplay:
    """N or N-1 normalized record replay with both content digests."""

    source_schema_version: str
    target_schema_version: str
    original_digest: str
    transformed_digest: str
    transformed_record: Mapping[str, Any]


def replay_inventory_observation_schema(
    record: Mapping[str, Any],
) -> InventoryObservationSchemaReplay:
    """Replay N or N-1 journal records without inferring missing authority."""

    source_schema = record.get("schema_version")
    if source_schema not in {"0.9.0", INVENTORY_OBSERVATION_SCHEMA_VERSION}:
        raise ValueError("inventory observation schema version is unsupported")
    original = dict(record)
    transformed = dict(original)
    if source_schema == "0.9.0":
        properties = transformed.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("N-1 inventory observation properties MUST be an object")
        transformed.update(
            {
                "schema_version": INVENTORY_OBSERVATION_SCHEMA_VERSION,
                "property_mask": sorted(properties),
                "scope_ref": None,
                "operation": None,
                "operation_status": None,
                "tombstone_confirmed": False,
            }
        )
    return InventoryObservationSchemaReplay(
        source_schema_version=str(source_schema),
        target_schema_version=INVENTORY_OBSERVATION_SCHEMA_VERSION,
        original_digest=_digest(original),
        transformed_digest=_digest(transformed),
        transformed_record=transformed,
    )


def replay_object_observations(
    observations: Sequence[NormalizedInventoryObservation],
    *,
    resource_type: str,
    baseline_properties: Mapping[str, Any],
    baseline_provider_ref: str | None,
    baseline_present: bool = True,
) -> InventoryObservationReplay:
    """Reduce duplicate or reordered object observations to one monotonic digest."""

    object_observations = tuple(
        item for item in observations if item.subject_kind is InventoryObservationSubjectKind.OBJECT
    )
    if any(item.subject_type != resource_type for item in object_observations):
        raise ValueError("inventory replay resource type changed")
    ordered = sorted(
        {item.observation_id: item for item in object_observations}.values(),
        key=lambda item: (
            item.effective_at,
            item.observation_kind is InventoryObservationKind.TOMBSTONE,
            item.source_event_id,
            item.content_digest,
        ),
    )
    properties = dict(baseline_properties)
    provider_ref = baseline_provider_ref
    present = baseline_present
    latest: NormalizedInventoryObservation | None = None
    for item in ordered:
        if item.observation_kind is InventoryObservationKind.TOMBSTONE:
            if item.tombstone_confirmed:
                present = False
                properties = {}
                provider_ref = None
            latest = item
            continue
        incoming = item.properties
        if item.observation_kind is InventoryObservationKind.FULL:
            properties = dict(incoming)
        else:
            for key in item.property_mask:
                properties[key] = incoming[key]
        if item.observation_kind is InventoryObservationKind.FULL:
            present = True
        if item.provider_ref is not None:
            provider_ref = item.provider_ref
        latest = item
    properties_json = _canonical_json(properties)
    replay_body = {
        "present": present,
        "resource_type": resource_type,
        "properties": json.loads(properties_json),
        "provider_ref": provider_ref,
        "latest_observation": latest.content_digest if latest is not None else None,
    }
    return InventoryObservationReplay(
        present=present,
        resource_type=resource_type,
        properties_json=properties_json,
        provider_ref=provider_ref,
        observed_at=latest.effective_at if latest is not None else None,
        source_event_id=latest.source_event_id if latest is not None else None,
        idempotency_key=latest.idempotency_key if latest is not None else None,
        digest=_digest(replay_body),
    )


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("inventory observation properties MUST be JSON-compatible") from exc


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _bounded_text(field_name: str, value: str) -> None:
    if not value or len(value) > _MAX_TEXT:
        raise ValueError(f"{field_name} MUST be bounded non-empty text")


def _aware_times(*values: datetime) -> None:
    if any(value.tzinfo is None for value in values):
        raise ValueError("inventory observation timestamps MUST be timezone-aware")


__all__ = [
    "INVENTORY_OBSERVATION_SCHEMA_VERSION",
    "InventoryMutationKind",
    "InventoryObservationKind",
    "InventoryObservationProjectionJournal",
    "InventoryObservationReplay",
    "InventoryObservationSchemaReplay",
    "InventoryObservationSubjectKind",
    "NormalizedInventoryObservation",
    "replay_inventory_observation_schema",
    "replay_object_observations",
]
