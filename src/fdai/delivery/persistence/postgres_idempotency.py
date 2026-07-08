"""PostgresIdempotencyStore - durable exactly-once guard on PostgreSQL.

Realizes :class:`~fdai.shared.providers.idempotency.IdempotencyStore` on
a single table with a UNIQUE ``idempotency_key``. ``record`` uses
``INSERT ... ON CONFLICT DO NOTHING`` so two racing replicas cannot both
claim the same key, and a post-restart retry finds the prior result via
``seen`` instead of re-mutating.

The table is created on first use (``CREATE TABLE IF NOT EXISTS``) so the
adapter is self-contained; a fork that manages schema via migrations can
pre-create it with the same shape.

psycopg 3 is already a repo dependency (see the sibling adapters).
"""

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
    "VALUES (%s, %s) ON CONFLICT (idempotency_key) DO NOTHING"
)


@dataclass(frozen=True, slots=True)
class PostgresIdempotencyStoreConfig:
    """DSN + per-statement timeout for the adapter."""

    dsn: str
    statement_timeout_ms: int = 15_000


class PostgresIdempotencyStore:
    """Durable :class:`IdempotencyStore` on PostgreSQL."""

    def __init__(self, *, config: PostgresIdempotencyStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresIdempotencyStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        self._config = config
        self._ready = False

    async def _ensure_table(self, conn: psycopg.AsyncConnection[Any]) -> None:
        if self._ready:
            return
        await conn.execute(_CREATE_SQL)
        self._ready = True

    async def _set_statement_timeout(self, conn: psycopg.AsyncConnection[Any]) -> None:
        await conn.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(self._config.statement_timeout_ms),),
        )

    async def seen(self, key: str) -> Mapping[str, Any] | None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn, autocommit=True, row_factory=dict_row
        ) as conn:
            await self._set_statement_timeout(conn)
            await self._ensure_table(conn)
            cur = await conn.execute(_SELECT_SQL, (key,))
            row = await cur.fetchone()
            if row is None:
                return None
            result = row["result"]
            return dict(result) if isinstance(result, dict) else None

    async def record(self, key: str, result: Mapping[str, Any]) -> bool:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn, autocommit=True
        ) as conn:
            await self._set_statement_timeout(conn)
            await self._ensure_table(conn)
            cur = await conn.execute(_INSERT_SQL, (key, json.dumps(dict(result))))
            # rowcount is 1 on insert, 0 when ON CONFLICT skipped it.
            return cur.rowcount == 1


__all__ = ["PostgresIdempotencyStore", "PostgresIdempotencyStoreConfig"]
