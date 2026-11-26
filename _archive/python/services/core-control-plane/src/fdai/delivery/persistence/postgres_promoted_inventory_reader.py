"""Read the active promoted inventory generation for baseline evaluation, without writes."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import (
    PromotedInventoryGeneration,
    PromotedInventoryGenerationLimitError,
    PromotedInventoryGenerationUnavailableError,
    ResourceRecord,
)

_READ_DEADLINE_SECONDS = 60


class PostgresPromotedInventoryGenerationReader:
    """Read the ``inventory_active`` snapshot in one repeatable-read, read-only transaction."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def active_generation_id(self) -> str | None:
        async with asyncio.timeout(_READ_DEADLINE_SECONDS):
            async with await psycopg.AsyncConnection.connect(
                self._config.dsn,
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                await connection.execute("SET TRANSACTION READ ONLY")
                cursor = await connection.execute(
                    "SELECT snapshot_id FROM inventory_active WHERE singleton=TRUE"
                )
                row = await cursor.fetchone()
        return str(row["snapshot_id"]) if row is not None else None

    async def load_active_generation(
        self,
        *,
        max_resources: int,
    ) -> PromotedInventoryGeneration | None:
        if max_resources < 1:
            raise ValueError("max_resources MUST be positive")
        async with asyncio.timeout(_READ_DEADLINE_SECONDS):
            async with await psycopg.AsyncConnection.connect(
                self._config.dsn,
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                cursor = await connection.execute(
                    "SELECT snapshot.id, snapshot.status, snapshot.completed_at, "
                    "snapshot.resource_count FROM inventory_active active "
                    "JOIN inventory_snapshot snapshot ON snapshot.id=active.snapshot_id "
                    "WHERE active.singleton=TRUE"
                )
                snapshot = await cursor.fetchone()
                if snapshot is None:
                    return None
                expected = _validated_snapshot(snapshot)
                if expected > max_resources:
                    raise PromotedInventoryGenerationLimitError(
                        "active inventory generation exceeds the Resource bound"
                    )
                cursor = await connection.execute(
                    "SELECT resource_id, resource_type, props, provider_ref, last_seen "
                    "FROM inventory_snapshot_resource WHERE snapshot_id=%s "
                    "ORDER BY resource_id LIMIT %s",
                    (snapshot["id"], max_resources + 1),
                )
                rows = await cursor.fetchall()
        if len(rows) != expected:
            raise PromotedInventoryGenerationUnavailableError(
                "active inventory generation Resource count does not reconcile"
            )
        resources = tuple(_resource(row) for row in rows)
        return PromotedInventoryGeneration(
            generation=str(snapshot["id"]),
            resources=resources,
            complete=True,
            recorded_at=snapshot["completed_at"],
        )


def _validated_snapshot(snapshot: Mapping[str, Any]) -> int:
    count = snapshot.get("resource_count")
    if (
        snapshot.get("status") != "active"
        or snapshot.get("completed_at") is None
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
    ):
        raise PromotedInventoryGenerationUnavailableError(
            "active inventory generation is not a completed snapshot"
        )
    return count


def _resource(row: Mapping[str, Any]) -> ResourceRecord:
    props = row["props"]
    if not isinstance(props, Mapping) or props.get("_truncated") is True:
        raise PromotedInventoryGenerationUnavailableError(
            "active inventory generation contains truncated Resource properties"
        )
    return ResourceRecord(
        resource_id=str(row["resource_id"]),
        type=str(row["resource_type"]),
        props=dict(props),
        provider_ref=str(row["provider_ref"]) if row["provider_ref"] is not None else None,
        last_seen=row["last_seen"].isoformat() if row["last_seen"] is not None else None,
    )


__all__ = ["PostgresPromotedInventoryGenerationReader"]
