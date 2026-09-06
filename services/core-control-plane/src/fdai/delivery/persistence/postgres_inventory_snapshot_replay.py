"""Load one complete active inventory snapshot for journal-backed release replay."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.delivery.inventory_sync import (
    PromotedInventoryObservation,
    compute_relationship_coverage,
)
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    MAX_ACTIVE_PROJECTION_OBSERVATIONS,
    projection_replay_drops,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    _PROMOTION_LOCK,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
)


class PostgresInventorySnapshotReplayLoader:
    """Read the exact active snapshot without invoking a provider."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def load(self) -> PromotedInventoryObservation:
        """Return one bounded complete observation while holding the promotion read lock."""

        async with await self._connect() as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await self._set_timeout(connection)
            await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,))
            snapshot_cursor = await connection.execute(
                "SELECT s.id, s.completed_at, s.metadata "
                "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "WHERE a.singleton=TRUE AND s.status='active'"
            )
            snapshot = await snapshot_cursor.fetchone()
            if snapshot is None or snapshot["completed_at"] is None:
                raise ValueError("active inventory snapshot is unavailable for journal bootstrap")
            generation = str(snapshot["id"])
            resources_cursor = await connection.execute(
                "SELECT resource_id, resource_type, props, provider_ref, last_seen "
                "FROM inventory_snapshot_resource WHERE snapshot_id=%s "
                "ORDER BY resource_id LIMIT %s",
                (generation, MAX_ACTIVE_PROJECTION_OBSERVATIONS + 1),
            )
            resources = await resources_cursor.fetchall()
            if len(resources) > MAX_ACTIVE_PROJECTION_OBSERVATIONS:
                raise ValueError("active inventory snapshot journal bootstrap exceeds its bound")
            remaining = MAX_ACTIVE_PROJECTION_OBSERVATIONS - len(resources)
            links_cursor = await connection.execute(
                "SELECT from_id, from_type, link_type, to_id, to_type, props "
                "FROM inventory_snapshot_link WHERE snapshot_id=%s "
                "ORDER BY link_type, from_id, to_id LIMIT %s",
                (generation, remaining + 1),
            )
            links = await links_cursor.fetchall()
            if len(links) > remaining:
                raise ValueError("active inventory snapshot journal bootstrap exceeds its bound")
            manifest_cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest'"
            )
            manifest_row = await manifest_cursor.fetchone()
        if manifest_row is None:
            raise ValueError("inventory projection replay manifest is unavailable")
        return build_active_snapshot_observation(
            snapshot=snapshot,
            resource_rows=resources,
            link_rows=links,
            prior_manifest=_mapping(manifest_row["value"]),
        )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def build_active_snapshot_observation(
    *,
    snapshot: Mapping[str, Any],
    resource_rows: Sequence[Mapping[str, Any]],
    link_rows: Sequence[Mapping[str, Any]],
    prior_manifest: Mapping[str, Any],
) -> PromotedInventoryObservation:
    """Rehydrate one verified active snapshot for the existing dual-write path."""

    generation = str(snapshot["id"])
    if prior_manifest.get("generation") != generation:
        raise ValueError("inventory projection replay manifest generation changed")
    metadata = _mapping(snapshot["metadata"])
    if metadata.get("projection_complete") is not True:
        raise ValueError("active inventory snapshot is incomplete for journal bootstrap")
    recorded_at = _timestamp(snapshot["completed_at"], "snapshot completed_at")
    resources = tuple(
        ResourceRecord(
            resource_id=str(row["resource_id"]),
            type=str(row["resource_type"]),
            props=_mapping(row["props"]),
            provider_ref=str(row["provider_ref"]) if row["provider_ref"] is not None else None,
            last_seen=(
                _timestamp(row["last_seen"], "resource last_seen").isoformat()
                if row["last_seen"] is not None
                else None
            ),
        )
        for row in resource_rows
    )
    links = tuple(_link_record(row) for row in link_rows)
    observation = PromotedInventoryObservation(
        generation=generation,
        resources=resources,
        links=links,
        complete=True,
        relationship_drops=projection_replay_drops(metadata, prior_manifest),
        recorded_at=recorded_at,
    )
    expected_coverage = _mapping(metadata.get("relationship_coverage"))
    if dict(compute_relationship_coverage(observation).to_metadata()) != dict(expected_coverage):
        raise ValueError("inventory snapshot journal bootstrap relationship coverage changed")
    return observation


def _link_record(row: Mapping[str, Any]) -> LinkRecord:
    properties = dict(_mapping(row["props"]))
    raw_observation = properties.pop(LINK_OBSERVATION_METADATA_PROPERTY, None)
    properties.pop("provider_relationship_evidence", None)
    if not isinstance(raw_observation, Mapping):
        raise ValueError("inventory snapshot relationship has no observation metadata")
    return LinkRecord(
        from_id=str(row["from_id"]),
        from_type=str(row["from_type"]),
        link_type=str(row["link_type"]),
        to_id=str(row["to_id"]),
        to_type=str(row["to_type"]),
        link_props=properties,
        observation_metadata=LinkObservationMetadata.from_mapping(raw_observation),
    )


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("inventory snapshot replay value MUST be an object")
    return value


def _timestamp(value: object, field: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"inventory snapshot replay {field} MUST be timezone-aware")
    return parsed.astimezone(UTC)


__all__ = ["PostgresInventorySnapshotReplayLoader", "build_active_snapshot_observation"]
