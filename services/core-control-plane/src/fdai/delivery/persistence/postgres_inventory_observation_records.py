"""Pure record conversion helpers for the PostgreSQL inventory journal."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence.postgres_inventory_snapshot import _snapshot_relationship_props
from fdai.shared.providers.inventory_observation import (
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)


def observation_from_row(row: Mapping[str, Any]) -> NormalizedInventoryObservation:
    """Decode one persisted journal row without changing its evidence content."""

    properties = mapping(row["properties"])
    return NormalizedInventoryObservation(
        observation_id=str(row["observation_id"]),
        content_digest=str(row["content_digest"]),
        idempotency_key=str(row["idempotency_key"]),
        subject_kind=InventoryObservationSubjectKind(str(row["subject_kind"])),
        observation_kind=InventoryObservationKind(str(row["observation_kind"])),
        mutation_kind=InventoryMutationKind(str(row["mutation_kind"])),
        subject_ref=str(row["subject_ref"]),
        subject_type=str(row["subject_type"]),
        properties_json=json.dumps(
            properties,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        property_mask=tuple(row["property_mask"]),
        properties_complete=bool(row["properties_complete"]),
        links_complete=bool(row["links_complete"]),
        tombstone_confirmed=bool(row["tombstone_confirmed"]),
        provider_ref=str(row["provider_ref"]) if row["provider_ref"] is not None else None,
        scope_ref=str(row["scope_ref"]) if row["scope_ref"] is not None else None,
        operation=str(row["operation"]) if row["operation"] is not None else None,
        operation_status=(
            str(row["operation_status"]) if row["operation_status"] is not None else None
        ),
        source_identity=str(row["source_identity"]),
        source_event_id=str(row["source_event_id"]),
        source_revision=str(row["source_revision"]),
        effective_at=row["effective_at"],
        observed_at=row["observed_at"],
        evidence_cutoff=row["evidence_cutoff"],
        recorded_at=row["recorded_at"],
        from_id=str(row["from_id"]) if row["from_id"] is not None else None,
        from_type=str(row["from_type"]) if row["from_type"] is not None else None,
        link_type=str(row["link_type"]) if row["link_type"] is not None else None,
        to_id=str(row["to_id"]) if row["to_id"] is not None else None,
        to_type=str(row["to_type"]) if row["to_type"] is not None else None,
    )


def snapshot_records(
    observation: PromotedInventoryObservation,
    *,
    scope_refs: tuple[str, ...],
) -> tuple[NormalizedInventoryObservation, ...]:
    """Normalize one promoted snapshot into idempotent journal records."""

    if observation.recorded_at is None:
        raise ValueError("promoted inventory observation recorded_at MUST be supplied")
    records: list[NormalizedInventoryObservation] = []
    scope_ref = _scope_set_ref(scope_refs)
    for resource in observation.resources:
        observed_at = _timestamp(resource.last_seen) or observation.recorded_at
        records.append(
            NormalizedInventoryObservation.create(
                idempotency_key=_snapshot_key(
                    observation.generation, "object", resource.resource_id
                ),
                subject_kind=InventoryObservationSubjectKind.OBJECT,
                observation_kind=InventoryObservationKind.FULL,
                mutation_kind=InventoryMutationKind.UPSERT,
                subject_ref=resource.resource_id,
                subject_type=resource.type,
                properties=resource.props,
                property_mask=tuple(resource.props),
                properties_complete=True,
                links_complete=observation.complete,
                tombstone_confirmed=False,
                provider_ref=resource.provider_ref,
                scope_ref=_provider_scope(resource.provider_ref) or scope_ref,
                source_identity="inventory.reconciliation",
                source_event_id=f"snapshot:{observation.generation}",
                source_revision=observation.generation,
                effective_at=observed_at,
                observed_at=observed_at,
                evidence_cutoff=observed_at,
                recorded_at=observation.recorded_at,
            )
        )
    for link in observation.links:
        subject_ref = _relationship_ref(link.from_id, link.link_type, link.to_id)
        relationship_properties = _snapshot_relationship_props(link)
        records.append(
            NormalizedInventoryObservation.create(
                idempotency_key=_snapshot_key(observation.generation, "relationship", subject_ref),
                subject_kind=InventoryObservationSubjectKind.RELATIONSHIP,
                observation_kind=InventoryObservationKind.FULL,
                mutation_kind=InventoryMutationKind.UPSERT,
                subject_ref=subject_ref,
                subject_type=link.link_type,
                properties=relationship_properties,
                property_mask=tuple(relationship_properties),
                properties_complete=True,
                links_complete=observation.complete,
                tombstone_confirmed=False,
                scope_ref=scope_ref,
                source_identity="inventory.reconciliation",
                source_event_id=f"snapshot:{observation.generation}",
                source_revision=observation.generation,
                effective_at=observation.recorded_at,
                observed_at=observation.recorded_at,
                evidence_cutoff=observation.recorded_at,
                recorded_at=observation.recorded_at,
                from_id=link.from_id,
                from_type=link.from_type,
                link_type=link.link_type,
                to_id=link.to_id,
                to_type=link.to_type,
            )
        )
    return tuple(records)


def confirmed_tombstone(
    row: Mapping[str, Any],
    *,
    generation: str,
    confirmed_at: datetime,
    recorded_at: datetime,
) -> NormalizedInventoryObservation:
    """Normalize one snapshot-confirmed deletion candidate."""

    resource_id = str(row["resource_id"])
    candidate_id = str(row["observation_id"])
    return NormalizedInventoryObservation.create(
        idempotency_key=f"inventory-tombstone-confirmation:{candidate_id}:{generation}",
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.TOMBSTONE,
        mutation_kind=InventoryMutationKind.DELETE,
        subject_ref=resource_id,
        subject_type=str(row["resource_type"]),
        properties={},
        property_mask=(),
        properties_complete=False,
        links_complete=True,
        tombstone_confirmed=True,
        scope_ref=str(row["scope_ref"]) if row["scope_ref"] is not None else None,
        source_identity="inventory.reconciliation",
        source_event_id=f"snapshot:{generation}",
        source_revision=generation,
        effective_at=confirmed_at,
        observed_at=confirmed_at,
        evidence_cutoff=confirmed_at,
        recorded_at=recorded_at,
    )


def mapping(value: object) -> Mapping[str, Any]:
    """Decode one JSON object while rejecting scalar or sequence values."""

    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("inventory observation JSON value MUST be an object")
    return value


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("inventory observation timestamp MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _snapshot_key(generation: str, subject_kind: str, subject_ref: str) -> str:
    digest = hashlib.sha256(subject_ref.encode("utf-8")).hexdigest()
    return f"inventory-snapshot:{generation}:{subject_kind}:{digest}"


def _relationship_ref(from_id: str, link_type: str, to_id: str) -> str:
    digest = hashlib.sha256(f"{from_id}\0{link_type}\0{to_id}".encode()).hexdigest()
    return f"relationship:{digest}"


def _provider_scope(provider_ref: str | None) -> str | None:
    if provider_ref is None:
        return None
    parts = provider_ref.strip("/").split("/")
    for index, part in enumerate(parts[:-1]):
        if part.lower() == "subscriptions" and parts[index + 1]:
            return parts[index + 1]
    return None


def _scope_set_ref(scope_refs: tuple[str, ...]) -> str:
    scopes = tuple(sorted(set(scope_refs)))
    if not scopes:
        raise ValueError("promoted inventory observation requires source scopes")
    if len(scopes) == 1:
        return scopes[0]
    digest = hashlib.sha256("\0".join(scopes).encode()).hexdigest()
    return f"scope-set:sha256:{digest}"


__all__ = ["confirmed_tombstone", "mapping", "observation_from_row", "snapshot_records"]
