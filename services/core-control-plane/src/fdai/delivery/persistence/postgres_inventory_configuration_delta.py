"""Compare a promoted inventory generation with the closest earlier one, without properties."""

from __future__ import annotations

import asyncio

import psycopg

from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)

_MAX_RESOURCES = 50_001

_PREVIOUS_SQL = (
    "SELECT previous.id FROM inventory_snapshot current "
    "JOIN inventory_snapshot previous ON previous.id <> current.id "
    "AND previous.status IN ('active', 'superseded') "
    "AND previous.promoted_at IS NOT NULL AND previous.promoted_at < current.promoted_at "
    "AND previous.scopes = current.scopes "
    "WHERE current.id = %s AND current.promoted_at IS NOT NULL "
    "ORDER BY previous.promoted_at DESC, previous.id DESC LIMIT 1"
)

# Equality covers type, provider reference, the exact property digest, and the property-freshness
# metadata; only the collection timestamp is ignored.
_UNCHANGED_SQL = (
    "SELECT current.resource_id FROM inventory_snapshot_resource_row current "
    "JOIN inventory_snapshot_resource_row previous "
    "ON previous.resource_id = current.resource_id AND previous.snapshot_id = %s "
    "WHERE current.snapshot_id = %s "
    "AND current.props_digest IS NOT NULL AND previous.props_digest IS NOT NULL "
    "AND current.props_digest = previous.props_digest "
    "AND current.resource_type = previous.resource_type "
    "AND current.provider_ref IS NOT DISTINCT FROM previous.provider_ref "
    "AND current.props_freshness = previous.props_freshness "
    "LIMIT %s"
)


class PostgresInventoryConfigurationComparison:
    """Read-only comparison that returns Resource identifiers, never properties."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def unchanged_since_previous(self, generation: str) -> tuple[str | None, frozenset[str]]:
        async with asyncio.timeout(30):
            async with await psycopg.AsyncConnection.connect(
                self._config.dsn, connect_timeout=self._config.connect_timeout_s
            ) as connection:
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                cursor = await connection.execute(_PREVIOUS_SQL, (generation,))
                row = await cursor.fetchone()
                if row is None:
                    return None, frozenset()
                previous = str(row[0])
                cursor = await connection.execute(
                    _UNCHANGED_SQL, (previous, generation, _MAX_RESOURCES)
                )
                return previous, frozenset(str(item[0]) for item in await cursor.fetchall())
