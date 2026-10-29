"""Rebuild inventory observations from durable snapshot state."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import psycopg

from fdai.delivery.inventory_configuration_events import (
    configuration_delivery_key,
    configuration_delivery_pending,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence.postgres_inventory_observation_records import mapping as _mapping
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    MAX_ACTIVE_PROJECTION_OBSERVATIONS,
    projection_replay_drops,
)
from fdai.shared.providers.inventory import (
    LinkRecord,
    RelationshipDrop,
    RelationshipDropReason,
    ResourceRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
)


def snapshot_recovery_observation(
    *,
    generation: str,
    recorded_at: datetime,
    metadata: Mapping[str, Any],
    prior_manifest: Mapping[str, Any],
    resource_rows: Sequence[Mapping[str, Any]],
    link_rows: Sequence[Mapping[str, Any]],
) -> PromotedInventoryObservation:
    if len(resource_rows) + len(link_rows) > MAX_ACTIVE_PROJECTION_OBSERVATIONS:
        raise ValueError("pending inventory snapshot replay exceeds its bound")
    resources = tuple(
        ResourceRecord(
            resource_id=str(row["resource_id"]),
            type=str(row["resource_type"]),
            props=_mapping(row["props"]),
            provider_ref=str(row["provider_ref"]) if row["provider_ref"] is not None else None,
            last_seen=(row["last_seen"].isoformat() if row["last_seen"] is not None else None),
        )
        for row in resource_rows
    )
    links: list[LinkRecord] = []
    relationship_drops = list(projection_replay_drops(metadata, prior_manifest))
    for row in link_rows:
        properties = dict(_mapping(row["props"]))
        raw_observation = properties.pop(LINK_OBSERVATION_METADATA_PROPERTY, None)
        if not isinstance(raw_observation, Mapping):
            relationship_drops.append(
                RelationshipDrop(reason=RelationshipDropReason.UNVERIFIED_METADATA)
            )
            continue
        links.append(
            LinkRecord(
                from_id=str(row["from_id"]),
                from_type=str(row["from_type"]),
                link_type=str(row["link_type"]),
                to_id=str(row["to_id"]),
                to_type=str(row["to_type"]),
                link_props=properties,
                observation_metadata=LinkObservationMetadata.from_mapping(raw_observation),
            )
        )
    return PromotedInventoryObservation(
        generation=generation,
        resources=resources,
        links=tuple(links),
        complete=True,
        relationship_drops=tuple(relationship_drops),
        recorded_at=recorded_at,
        state_base_generation=(
            str(metadata["state_base_generation"])
            if metadata.get("state_base_generation") is not None
            else None
        ),
        state_base_generation_checked="state_base_generation" in metadata,
    )


async def reusable_journal_generation(
    connection: psycopg.AsyncConnection[Any],
    *,
    snapshot: Mapping[str, Any],
    semantic_digest: str,
) -> str | None:
    cursor = await connection.execute(
        "SELECT s.id, s.metadata FROM inventory_snapshot s "
        "WHERE s.id<>%s AND s.status='superseded' AND s.source=%s "
        "AND s.observation_kind=%s AND s.scopes=%s::jsonb "
        "AND s.resource_types=%s::jsonb "
        "AND s.metadata->>'coverage_scope' IS NOT DISTINCT FROM %s "
        "AND s.metadata->>'semantic_content_digest'=%s "
        "AND s.metadata->>'projection_complete'='true' "
        "ORDER BY s.completed_at DESC, s.id DESC LIMIT 1",
        (
            str(snapshot["id"]),
            str(snapshot["source"]),
            str(snapshot["observation_kind"]),
            json.dumps(snapshot["scopes"]),
            json.dumps(snapshot["resource_types"]),
            _mapping(snapshot["metadata"]).get("coverage_scope"),
            semantic_digest,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    metadata = _mapping(row["metadata"])
    prior_generation = str(row["id"])
    delivery_cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key=%s",
        (configuration_delivery_key(prior_generation),),
    )
    delivery_row = await delivery_cursor.fetchone()
    if delivery_row is None:
        return None
    delivery = _mapping(delivery_row["value"])
    configuration_delivery_pending(delivery, generation=prior_generation)
    if delivery.get("generation") != prior_generation or delivery.get("status") != "completed":
        return None
    source_generation = metadata.get("journal_source_generation") or row["id"]
    if (
        not isinstance(source_generation, str)
        or not source_generation.strip()
        or len(source_generation) > 256
    ):
        raise ValueError("inventory journal source generation is malformed")
    retained = await connection.execute(
        "SELECT 1 FROM inventory_observation_journal "
        "WHERE source_revision=%s AND source_event_id=%s LIMIT 1",
        (source_generation, f"snapshot:{source_generation}"),
    )
    return source_generation if await retained.fetchone() is not None else None


def rebase_recovery_metadata(
    metadata: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    rebased = dict(metadata)
    expected_base = metadata.get("state_base_generation")
    actual_base = manifest.get("generation")
    if actual_base == expected_base:
        return rebased
    if not isinstance(actual_base, str) or not actual_base.strip():
        raise ValueError("pending inventory ontology base generation changed")
    rebased["state_base_generation"] = actual_base
    return rebased


__all__ = [
    "rebase_recovery_metadata",
    "reusable_journal_generation",
    "snapshot_recovery_observation",
]
