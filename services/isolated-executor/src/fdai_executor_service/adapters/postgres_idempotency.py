"""PostgreSQL first-writer-wins idempotency ledger for Executor effects."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

_EXECUTOR_ROLE = "fdai_executor"
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

    async def assert_schema(self) -> None:
        """Fail startup unless the migration-owned idempotency schema is exact."""
        async with await self._connect(row_factory=dict_row) as connection:
            await self._prepare(connection)
            readiness = await (
                await connection.execute(
                    "SELECT current_user AS database_role, "
                    "has_table_privilege(current_user, 'action_idempotency', "
                    "'SELECT, INSERT') AS ready"
                )
            ).fetchone()
            if (
                readiness is None
                or str(readiness["database_role"]) != _EXECUTOR_ROLE
                or readiness["ready"] is not True
            ):
                raise RuntimeError("Executor database role or idempotency grants are invalid")
            columns = await (
                await connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = %s",
                    ("action_idempotency",),
                )
            ).fetchall()
            primary_key = await (
                await connection.execute(
                    "SELECT a.attname FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE "
                    "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                    "WHERE n.nspname = current_schema() AND t.relname = %s "
                    "AND c.contype = 'p' ORDER BY k.ord",
                    ("action_idempotency",),
                )
            ).fetchall()
        observed_columns = {str(row["column_name"]) for row in columns}
        observed_primary_key = tuple(str(row["attname"]) for row in primary_key)
        required_columns = {"idempotency_key", "result", "recorded_at"}
        if not required_columns <= observed_columns or observed_primary_key != ("idempotency_key",):
            raise RuntimeError("Executor idempotency schema is missing or incompatible")

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


__all__ = ["PostgresIdempotencyStore", "PostgresIdempotencyStoreConfig"]
