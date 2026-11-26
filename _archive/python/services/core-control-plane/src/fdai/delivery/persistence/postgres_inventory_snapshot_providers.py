"""Read-only providers backed by the active PostgreSQL inventory snapshot."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final, Protocol

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_inventory_snapshot_support import read_inventory_context
from fdai.shared.providers.inventory_snapshot import InventoryObservationKind

_PROMOTION_LOCK: Final[int] = 732_410_991


class _InventorySnapshotConnectionConfig(Protocol):
    @property
    def dsn(self) -> str: ...

    @property
    def statement_timeout_ms(self) -> int: ...

    @property
    def connect_timeout_s(self) -> int: ...


class PostgresInventoryAgeProvider:
    """Return the active snapshot age for RiskGate freshness checks."""

    def __init__(self, *, config: _InventorySnapshotConnectionConfig) -> None:
        self._config = config

    async def __call__(self, resource_ref: str) -> int | None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,))
            cursor = await connection.execute(
                "SELECT EXTRACT(EPOCH FROM (NOW() - s.completed_at)) AS age_seconds, "
                "s.observation_kind, s.metadata, "
                "EXISTS (SELECT 1 FROM inventory_realtime_resource d "
                "WHERE d.resource_id=%s AND d.change_kind='upsert') OR ("
                "EXISTS (SELECT 1 FROM inventory_snapshot_resource r "
                "WHERE r.snapshot_id=s.id AND r.resource_id=%s) AND NOT EXISTS ("
                "SELECT 1 FROM inventory_realtime_resource d WHERE d.resource_id=%s)) "
                "AS resource_present, EXISTS (SELECT 1 FROM inventory_realtime_resource d "
                "WHERE d.resource_id=%s) AS realtime_pending, "
                "EXISTS (SELECT 1 FROM inventory_snapshot newer "
                "WHERE newer.id<>s.id AND newer.started_at>s.completed_at AND ("
                "newer.status='failed' OR (newer.status='collecting' AND "
                "newer.started_at < NOW() - INTERVAL '30 minutes'))) AS newer_failure "
                "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "WHERE a.singleton=TRUE AND s.status='active'",
                (resource_ref, resource_ref, resource_ref, resource_ref),
            )
            row = await cursor.fetchone()
        if row is None or row["age_seconds"] is None:
            return None
        if not row["resource_present"] or row["realtime_pending"] or row["newer_failure"]:
            return None
        if row["observation_kind"] != InventoryObservationKind.OBSERVED.value:
            return None
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        covered_links = (
            set(metadata.get("link_types", ())) if isinstance(metadata, Mapping) else set()
        )
        if not {"contains", "attached_to", "depends_on"}.issubset(covered_links):
            return None
        return max(0, int(row["age_seconds"]))


class PostgresInventoryContextProvider:
    """Return trusted properties for one resource in the active snapshot."""

    def __init__(self, *, config: _InventorySnapshotConnectionConfig) -> None:
        self._config = config

    async def __call__(self, resource_ref: str) -> Mapping[str, Any] | None:
        return await read_inventory_context(
            self._config,
            resource_ref,
            promotion_lock=_PROMOTION_LOCK,
        )


__all__ = [
    "_PROMOTION_LOCK",
    "PostgresInventoryAgeProvider",
    "PostgresInventoryContextProvider",
]
