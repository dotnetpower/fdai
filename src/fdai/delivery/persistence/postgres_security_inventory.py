"""Bounded active-inventory reader for security assessment projection."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import ResourceRecord

_SECURITY_RESOURCE_TYPES = (
    "kubernetes-cluster",
    "kubernetes-node-pool",
    "mysql-server",
)


class PostgresSecurityInventoryReader:
    """Read only security-relevant resources from the promoted snapshot."""

    def __init__(
        self,
        *,
        config: PostgresInventorySnapshotStoreConfig,
        max_resources: int = 10_000,
    ) -> None:
        if max_resources < 1:
            raise ValueError("max_resources MUST be >= 1")
        self._config = config
        self._max_resources = max_resources

    async def list_security_resources(self) -> tuple[ResourceRecord, ...]:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(
                "SELECT r.resource_id, r.resource_type, r.props, "
                "r.provider_ref, r.last_seen "
                "FROM inventory_active a "
                "JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "JOIN inventory_snapshot_resource r ON r.snapshot_id=a.snapshot_id "
                "WHERE a.singleton=TRUE AND s.status='active' "
                "AND r.resource_type=ANY(%s) "
                "ORDER BY r.resource_type, r.resource_id LIMIT %s",
                (list(_SECURITY_RESOURCE_TYPES), self._max_resources + 1),
            )
            rows = await cursor.fetchall()
        if len(rows) > self._max_resources:
            raise RuntimeError(f"security inventory exceeds max_resources={self._max_resources}")
        return tuple(_row_to_resource(row) for row in rows)


def _row_to_resource(row: Mapping[str, Any]) -> ResourceRecord:
    props = row["props"]
    if isinstance(props, str):
        props = json.loads(props)
    last_seen = row.get("last_seen")
    if isinstance(last_seen, datetime):
        last_seen = last_seen.isoformat()
    return ResourceRecord(
        resource_id=str(row["resource_id"]),
        type=str(row["resource_type"]),
        props=dict(props) if isinstance(props, Mapping) else {},
        provider_ref=str(row["provider_ref"]) if row.get("provider_ref") else None,
        last_seen=str(last_seen) if last_seen else None,
    )


__all__ = ["PostgresSecurityInventoryReader"]
