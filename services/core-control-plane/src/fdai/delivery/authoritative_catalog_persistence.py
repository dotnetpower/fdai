"""Atomic PostgreSQL publication for one authoritative catalog generation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol, cast

import psycopg
from psycopg.rows import dict_row


class CatalogConnection(Protocol):
    async def execute(self, query: str, params: object = None) -> object: ...


async def write_catalog_snapshots_atomic(
    *,
    dsn: str,
    snapshots: Mapping[str, Mapping[str, object]],
    statement_timeout_ms: int,
    connect_timeout_s: int,
) -> None:
    """Publish all projection keys in one transaction or publish none of them."""
    if not dsn:
        raise ValueError("catalog snapshot DSN MUST NOT be empty")
    if statement_timeout_ms < 1 or connect_timeout_s < 1:
        raise ValueError("catalog snapshot timeouts MUST be positive")
    async with await psycopg.AsyncConnection.connect(
        dsn,
        connect_timeout=connect_timeout_s,
        row_factory=dict_row,
    ) as connection:
        async with connection.transaction():
            await write_catalog_snapshots_in_transaction(
                cast(CatalogConnection, connection),
                snapshots,
                statement_timeout_ms=statement_timeout_ms,
            )


async def write_catalog_snapshots_in_transaction(
    connection: CatalogConnection,
    snapshots: Mapping[str, Mapping[str, object]],
    *,
    statement_timeout_ms: int,
) -> None:
    """Write a deterministic complete batch through the caller's active transaction."""
    if statement_timeout_ms < 1:
        raise ValueError("statement_timeout_ms MUST be positive")
    await connection.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
    for key in sorted(snapshots):
        await connection.execute(
            """
            INSERT INTO state_kv (key, value)
            VALUES (%s, %s::jsonb)
            ON CONFLICT (key)
            DO UPDATE SET value = EXCLUDED.value,
                          updated_at = NOW()
            """,
            (key, json.dumps(dict(snapshots[key]), allow_nan=False, default=str)),
        )


__all__ = ["write_catalog_snapshots_atomic", "write_catalog_snapshots_in_transaction"]
