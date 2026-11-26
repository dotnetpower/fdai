"""PostgresOutboxStore - durable claim-first outbox on PostgreSQL.

Realizes :class:`~fdai.shared.providers.outbox.OutboxStore` on a single
table with the ``idempotency_key`` as primary key. ``claim`` uses
``INSERT ... ON CONFLICT DO NOTHING`` so two racing replicas cannot both
receive ``NEW`` for the same key; on conflict it reads back the existing
row to report ``IN_PROGRESS`` (a crash suspect) or ``DONE`` (with the
recorded result).

The table is created on first use so the adapter is self-contained; a
fork managing schema via migrations can pre-create it with the same
shape.

psycopg 3 is already a repo dependency (see the sibling adapters).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.outbox import OutboxClaim, OutboxStatus

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS action_outbox (
    idempotency_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    result JSONB,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
)
"""

_CLAIM_SQL = (
    "INSERT INTO action_outbox (idempotency_key, status) "
    "VALUES (%s, 'in_progress') ON CONFLICT (idempotency_key) DO NOTHING"
)

_SELECT_SQL = "SELECT status, result FROM action_outbox WHERE idempotency_key = %s"

# ``complete`` MUST be a one-way transition: an already-DONE row keeps its
# original ``result`` and ``completed_at`` even if a duplicate ``complete()``
# is issued. The ``WHERE action_outbox.status <> 'done'`` predicate freezes
# terminal rows so a buggy retry cannot silently overwrite the recorded
# outcome (exactly-once).
_COMPLETE_SQL = (
    "INSERT INTO action_outbox (idempotency_key, status, result, completed_at) "
    "VALUES (%s, 'done', %s, now()) "
    "ON CONFLICT (idempotency_key) DO UPDATE "
    "SET status = 'done', result = EXCLUDED.result, completed_at = now() "
    "WHERE action_outbox.status <> 'done'"
)


@dataclass(frozen=True, slots=True)
class PostgresOutboxStoreConfig:
    """DSN + per-statement timeout for the adapter."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10
    """Bound the TCP/auth handshake so a dead DB fails fast instead of
    hanging the event loop (``statement_timeout`` only starts *after*
    connect succeeds)."""


class PostgresOutboxStore:
    """Durable :class:`OutboxStore` on PostgreSQL."""

    def __init__(self, *, config: PostgresOutboxStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresOutboxStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config
        self._ready = False

    async def _prepare(self, conn: psycopg.AsyncConnection[Any]) -> None:
        await conn.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(self._config.statement_timeout_ms),),
        )
        if not self._ready:
            await conn.execute(_CREATE_SQL)
            self._ready = True

    async def claim(self, key: str) -> OutboxClaim:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            await self._prepare(conn)
            cur = await conn.execute(_CLAIM_SQL, (key,))
            if cur.rowcount == 1:
                return OutboxClaim(status=OutboxStatus.NEW)
            cur = await conn.execute(_SELECT_SQL, (key,))
            row = await cur.fetchone()
            if row is None:  # pragma: no cover - claimed then vanished
                return OutboxClaim(status=OutboxStatus.NEW)
            if str(row["status"]) == OutboxStatus.DONE.value:
                result = row["result"]
                return OutboxClaim(
                    status=OutboxStatus.DONE,
                    result=dict(result) if isinstance(result, dict) else None,
                )
            return OutboxClaim(status=OutboxStatus.IN_PROGRESS)

    async def complete(self, key: str, result: Mapping[str, Any]) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=True,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            await self._prepare(conn)
            await conn.execute(_COMPLETE_SQL, (key, json.dumps(dict(result))))


__all__ = ["PostgresOutboxStore", "PostgresOutboxStoreConfig"]
