"""Validate normalized inventory change semantics and rebuild object overlays."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import psycopg

from fdai.delivery.persistence.postgres_inventory_observation import (
    PostgresInventoryObservationJournal,
)
from fdai.shared.providers.inventory_observation import (
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationReplay,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
    replay_object_observations,
)

_SNAPSHOT_RESOURCE_QUERY = (
    "SELECT resource_type, props, provider_ref FROM inventory_snapshot_resource "
    "WHERE snapshot_id=%s AND resource_id=%s"
)


def optional_change_text(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item or len(item) > 512:
        raise ValueError(f"inventory_change.{key} MUST be bounded non-empty text or null")
    return item


def inventory_observation_kind(
    change: Mapping[str, Any],
    *,
    change_kind: str,
    properties_complete: bool,
) -> InventoryObservationKind:
    raw = change.get("observation_kind")
    if raw is None:
        if not properties_complete:
            return InventoryObservationKind.PARTIAL
        if change_kind == "delete":
            return InventoryObservationKind.TOMBSTONE
        return InventoryObservationKind.FULL
    if not isinstance(raw, str):
        raise ValueError("inventory_change.observation_kind MUST be a string")
    try:
        return InventoryObservationKind(raw)
    except ValueError as exc:
        raise ValueError(
            "inventory_change.observation_kind MUST be full, partial, change_hint, or tombstone"
        ) from exc


def inventory_property_mask(
    change: Mapping[str, Any],
    *,
    properties: Mapping[str, Any],
    observation_kind: InventoryObservationKind,
) -> tuple[str, ...]:
    raw = change.get("property_mask")
    if raw is None:
        return (
            ()
            if observation_kind is InventoryObservationKind.TOMBSTONE
            else tuple(sorted(properties))
        )
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ValueError("inventory_change.property_mask MUST be an array")
    if any(not isinstance(item, str) or not item or len(item) > 128 for item in raw):
        raise ValueError("inventory_change.property_mask entries MUST be bounded strings")
    mask = tuple(raw)
    if mask != tuple(sorted(set(mask))):
        raise ValueError("inventory_change.property_mask MUST be sorted and unique")
    return mask


def validate_inventory_observation_semantics(
    *,
    observation_kind: InventoryObservationKind,
    change_kind: str,
    properties_complete: bool,
    property_mask: tuple[str, ...],
    properties: Mapping[str, Any],
    tombstone_confirmed: bool,
) -> None:
    if set(property_mask) != set(properties):
        raise ValueError("inventory_change.property_mask MUST match observed property keys")
    if observation_kind is InventoryObservationKind.FULL:
        if change_kind != "upsert" or not properties_complete or tombstone_confirmed:
            raise ValueError("full inventory observation semantics are inconsistent")
        return
    if observation_kind in {
        InventoryObservationKind.PARTIAL,
        InventoryObservationKind.CHANGE_HINT,
    }:
        if change_kind != "upsert" or properties_complete or tombstone_confirmed:
            raise ValueError("sparse inventory observation semantics are inconsistent")
        return
    if change_kind != "delete" or properties_complete or properties or property_mask:
        raise ValueError("tombstone inventory observation semantics are inconsistent")


def normalized_inventory_observations(
    *,
    payload: Mapping[str, Any],
    change: Mapping[str, Any],
    resource: Mapping[str, Any],
    links: Sequence[Mapping[str, Any]],
    link_kinds: Sequence[str],
    observation_kind: InventoryObservationKind,
    property_mask: tuple[str, ...],
    properties_complete: bool,
    links_complete: bool,
    tombstone_confirmed: bool,
    operation: str | None,
    operation_status: str | None,
    observed_at: datetime,
    recorded_at: datetime,
) -> tuple[NormalizedInventoryObservation, ...]:
    event_id = _required_str(payload, "event_id")
    idempotency_key = _required_str(payload, "idempotency_key")
    source = payload.get("source")
    source_identity = source if isinstance(source, str) and source else "inventory.resource_changed"
    source_revision_value = change.get("source_revision")
    source_revision = (
        source_revision_value
        if isinstance(source_revision_value, str) and source_revision_value
        else observed_at.isoformat()
    )
    scope_value = change.get("scope_ref")
    if scope_value is not None and (
        not isinstance(scope_value, str) or not scope_value or len(scope_value) > 512
    ):
        raise ValueError("inventory_change.scope_ref MUST be bounded non-empty text or null")
    provider_ref = (
        str(resource["provider_ref"]) if resource.get("provider_ref") is not None else None
    )
    scope_ref = scope_value if isinstance(scope_value, str) else _provider_scope(provider_ref)
    resource_props = resource.get("props", {})
    if not isinstance(resource_props, Mapping):
        raise ValueError("inventory_change.resource.props MUST be an object")
    records = [
        NormalizedInventoryObservation.create(
            idempotency_key=idempotency_key,
            subject_kind=InventoryObservationSubjectKind.OBJECT,
            observation_kind=observation_kind,
            mutation_kind=InventoryMutationKind(_required_str(change, "kind")),
            subject_ref=_required_str(resource, "resource_id"),
            subject_type=_required_str(resource, "type"),
            properties=resource_props,
            property_mask=property_mask,
            properties_complete=properties_complete,
            links_complete=links_complete,
            tombstone_confirmed=tombstone_confirmed,
            provider_ref=provider_ref,
            scope_ref=scope_ref,
            operation=operation,
            operation_status=operation_status,
            source_identity=source_identity,
            source_event_id=event_id,
            source_revision=source_revision,
            effective_at=observed_at,
            observed_at=observed_at,
            evidence_cutoff=observed_at,
            recorded_at=recorded_at,
        )
    ]
    for link, link_kind in zip(links, link_kinds, strict=True):
        link_props = link.get("props", {})
        if not isinstance(link_props, Mapping):
            raise ValueError("inventory_change link.props MUST be an object")
        from_id = _required_str(link, "from_id")
        link_type = _required_str(link, "link_type")
        to_id = _required_str(link, "to_id")
        subject_ref = _relationship_ref(from_id, link_type, to_id)
        is_tombstone = link_kind == "delete"
        records.append(
            NormalizedInventoryObservation.create(
                idempotency_key=idempotency_key,
                subject_kind=InventoryObservationSubjectKind.RELATIONSHIP,
                observation_kind=(
                    InventoryObservationKind.TOMBSTONE
                    if is_tombstone
                    else InventoryObservationKind.FULL
                ),
                mutation_kind=InventoryMutationKind(link_kind),
                subject_ref=subject_ref,
                subject_type=link_type,
                properties={} if is_tombstone else link_props,
                property_mask=() if is_tombstone else tuple(sorted(link_props)),
                properties_complete=not is_tombstone,
                links_complete=links_complete,
                tombstone_confirmed=is_tombstone,
                scope_ref=scope_ref,
                source_identity=source_identity,
                source_event_id=event_id,
                source_revision=source_revision,
                effective_at=observed_at,
                observed_at=observed_at,
                evidence_cutoff=observed_at,
                recorded_at=recorded_at,
                from_id=from_id,
                from_type=_required_str(link, "from_type"),
                link_type=link_type,
                to_id=to_id,
                to_type=_required_str(link, "to_type"),
            )
        )
    return tuple(records)


async def replay_inventory_resource_projection(
    connection: psycopg.AsyncConnection[Any],
    *,
    journal: PostgresInventoryObservationJournal,
    snapshot_id: str,
    snapshot_started_at: datetime,
    resource_id: str,
    resource_type: str,
) -> InventoryObservationReplay:
    baseline_cursor = await connection.execute(
        _SNAPSHOT_RESOURCE_QUERY,
        (snapshot_id, resource_id),
    )
    baseline = await baseline_cursor.fetchone()
    baseline_properties: Mapping[str, Any] = {}
    baseline_provider_ref: str | None = None
    baseline_present = baseline is not None
    if baseline is not None:
        if str(baseline["resource_type"]) != resource_type:
            raise ValueError("inventory resource type does not match the snapshot resource type")
        baseline_properties_value = baseline["props"]
        if isinstance(baseline_properties_value, str):
            baseline_properties_value = json.loads(baseline_properties_value)
        if not isinstance(baseline_properties_value, Mapping):
            raise ValueError("snapshot inventory resource props MUST be an object")
        baseline_properties = baseline_properties_value
        if baseline["provider_ref"] is not None:
            baseline_provider_ref = str(baseline["provider_ref"])
    observations = await journal.load_object_observations(
        connection,
        resource_id=resource_id,
        after=snapshot_started_at,
    )
    return replay_object_observations(
        observations,
        resource_type=resource_type,
        baseline_properties=baseline_properties,
        baseline_provider_ref=baseline_provider_ref,
        baseline_present=baseline_present,
    )


def _required_str(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} MUST be a non-empty string")
    return item


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


__all__ = [
    "inventory_observation_kind",
    "inventory_property_mask",
    "normalized_inventory_observations",
    "optional_change_text",
    "replay_inventory_resource_projection",
    "validate_inventory_observation_semantics",
]
