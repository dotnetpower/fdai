"""PostgreSQL first-writer-wins idempotency ledger for Executor effects."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS action_idempotency (
    idempotency_key TEXT PRIMARY KEY,
    result JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
_SELECT_SQL = "SELECT result FROM action_idempotency WHERE idempotency_key = %s"
_INSERT_SQL = (
    "INSERT INTO action_idempotency (idempotency_key, result) "
    "VALUES (%s, %s::jsonb) ON CONFLICT (idempotency_key) DO NOTHING"
)


@dataclass(frozen=True, slots=True)
class PostgresIdempotencyStoreConfig:
    """Bounded connection and statement settings for effect deduplication."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresIdempotencyStore:
    """Record one immutable effect result per stable idempotency key."""

    def __init__(self, *, config: PostgresIdempotencyStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresIdempotencyStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    async def seen(self, key: str) -> Mapping[str, Any] | None:
        """Return a defensive copy of the existing effect result."""

        async with await self._connect(row_factory=dict_row) as connection:
            await self._prepare(connection)
            cursor = await connection.execute(_SELECT_SQL, (key,))
            row = await cursor.fetchone()
        if row is None:
            return None
        result = row["result"]
        if not isinstance(result, dict):
            raise ValueError("idempotency result is not a JSON object; refusing replay")
        return dict(result)

    async def record(self, key: str, result: Mapping[str, Any]) -> bool:
        """Atomically record the first result and preserve any winner."""

        async with await self._connect() as connection:
            await self._prepare(connection)
            cursor = await connection.execute(
                _INSERT_SQL,
                (key, json.dumps(dict(result), sort_keys=True, default=str)),
            )
            return cursor.rowcount == 1

    async def _connect(self, **kwargs: Any) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=True,
            connect_timeout=self._config.connect_timeout_s,
            **kwargs,
        )

    async def _prepare(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(self._config.statement_timeout_ms),),
        )
        await connection.execute(_CREATE_SQL)


__all__ = ["PostgresIdempotencyStore", "PostgresIdempotencyStoreConfig"]
