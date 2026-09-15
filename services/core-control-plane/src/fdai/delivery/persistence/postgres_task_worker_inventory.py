"""One-statement, exact-resource recorded inventory read for bounded task workers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)


class PostgresTaskWorkerInventoryReader:
    """Project bounded recorded state and its provenance from one MVCC snapshot, without writes.

    Unreconciled target changes, failed newer collections, expected-only, future or stale snapshots
    stay unavailable. A single SQL statement binds the pointer, resource, time and state; this
    reader never combines graph metadata with a later context read or loads raw properties.
    """

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def __call__(self, resource_ref: str) -> Mapping[str, Any] | None:
        """Read only the selected resource, returning None when current evidence is unavailable."""
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.set_read_only(True)
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(
                "SELECT s.id AS snapshot_id, s.completed_at AS observed_at, r.resource_id, "
                "r.resource_type, "
                "CASE WHEN jsonb_typeof(r.props->'name')='string' "
                "AND length(r.props->>'name')<=256 THEN r.props->>'name' END AS name, "
                "CASE WHEN jsonb_typeof(r.props->'state')='string' "
                "AND length(r.props->>'state')<=256 THEN r.props->>'state' END AS state, "
                "CASE WHEN jsonb_typeof(r.props->'status')='string' "
                "AND length(r.props->>'status')<=256 THEN r.props->>'status' END AS status, "
                "EXTRACT(EPOCH FROM (NOW()-s.completed_at)) AS age_seconds, "
                "EXISTS (SELECT 1 FROM inventory_realtime_resource d "
                "WHERE d.resource_id=r.resource_id) AS pending, "
                "EXISTS (SELECT 1 FROM inventory_snapshot newer "
                "WHERE newer.id<>s.id AND newer.started_at>s.completed_at AND "
                "(newer.status='failed' OR (newer.status='collecting' AND "
                "newer.started_at < NOW()-INTERVAL '30 minutes'))) AS newer_failure "
                "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "JOIN inventory_snapshot_resource r ON r.snapshot_id=s.id "
                "WHERE a.singleton=TRUE AND s.status='active' "
                "AND s.observation_kind='observed' AND r.resource_id=%s",
                (resource_ref,),
            )
            row = await cursor.fetchone()
        if (
            row is None
            or row["age_seconds"] is None
            or not 0 <= row["age_seconds"] <= self._config.freshness_budget_seconds
            or row["pending"]
            or row["newer_failure"]
        ):
            return None
        return {
            "resource_id": row["resource_id"],
            "resource_type": row["resource_type"],
            "name": row["name"],
            "state": row["state"] or row["status"],
            "snapshot_id": row["snapshot_id"],
            "observed_at": row["observed_at"].isoformat(),
        }
