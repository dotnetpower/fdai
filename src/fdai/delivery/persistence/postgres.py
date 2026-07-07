"""PostgresStateStore - real `StateStore` on PostgreSQL via psycopg 3.

Realizes :class:`~fdai.shared.providers.state_store.StateStore`
against the ``audit_log`` + ``state_kv`` tables created by the alembic
migrations. Every audit entry is hash-chained to the prior entry (matching
:class:`~fdai.shared.providers.testing.state_store.InMemoryStateStore`)
so :func:`verify_chain` can be used across the two backends
interchangeably.

Notes on the wire choice:

- psycopg 3 is already a repo dep (see ``pyproject.toml`` W1.5/W1.6). No
  new package lands in the lockfile.
- Async is opt-in per-connection (``psycopg.AsyncConnection``); the pool
  lives inside this adapter, so ``core/`` never sees a driver call.
- ``previous_hash`` / ``entry_hash`` semantics are enforced in the same
  in-memory canonical serialization as the fake, keeping the two
  implementations swappable without recomputing hashes on migration.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.state_store import StateStore

_GENESIS_HASH: Final[str] = "0" * 64


def _canonical(entry: Mapping[str, Any]) -> str:
    """Deterministic JSON serialization matching :class:`InMemoryStateStore`."""
    return json.dumps(dict(entry), sort_keys=True, separators=(",", ":"), default=str)


def _next_hash(previous: str, entry: Mapping[str, Any]) -> str:
    return hashlib.sha256((previous + _canonical(entry)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PostgresStateStoreConfig:
    """DSN + optional per-statement timeout for the adapter."""

    dsn: str
    """psycopg 3 connection string. e.g.
    ``postgresql://user:password@host:5432/db?sslmode=require``."""

    statement_timeout_ms: int = 15_000
    """Applied via ``SET LOCAL`` on every operation; fails fast rather than
    blocking the event loop on a stuck query."""


class PostgresStateStore(StateStore):
    """Async :class:`StateStore` implementation for PostgreSQL."""

    def __init__(self, *, config: PostgresStateStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresStateStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        self._config = config

    # ------------------------------------------------------------------
    # StateStore
    # ------------------------------------------------------------------

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        """Append one audit record inside a hash-chained transaction.

        The row is refused if a concurrent writer already committed a
        record with the same ``entry_hash`` - the unique index doubles
        as tamper-evidence and idempotency guard. Callers deduplicating
        on ``idempotency_key`` upstream (event-ingest) will not hit this
        path twice for the same event.
        """
        payload = dict(entry)
        event_id = str(payload.get("event_id") or "00000000-0000-0000-0000-000000000000")
        correlation_id = payload.get("correlation_id")
        actor = str(payload.get("actor", "fdai"))
        action_kind = str(payload.get("action_kind", "unknown"))
        mode = str(payload.get("mode", "shadow"))
        if mode not in ("shadow", "enforce"):
            raise ValueError(f"audit entry mode MUST be 'shadow'|'enforce', got {mode!r}")

        async with await psycopg.AsyncConnection.connect(self._config.dsn) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cur = await conn.execute(
                    "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
                )
                row = await cur.fetchone()
                previous = row[0] if row is not None else _GENESIS_HASH
                entry_hash = _next_hash(previous, payload)
                await conn.execute(
                    """
                    INSERT INTO audit_log
                        (event_id, correlation_id, actor, action_kind, mode,
                         entry, previous_hash, entry_hash)
                    VALUES
                        (%s::uuid, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        event_id,
                        correlation_id,
                        actor,
                        action_kind,
                        mode,
                        _canonical(payload),
                        previous,
                        entry_hash,
                    ),
                )

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn, row_factory=dict_row
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cur = await conn.execute("SELECT value FROM state_kv WHERE key = %s", (key,))
                row = await cur.fetchone()
        if row is None:
            return None
        value = row["value"]
        if isinstance(value, dict):
            return dict(value)
        raise RuntimeError(
            f"state_kv[{key!r}].value is not a JSON object; got {type(value).__name__}"
        )

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        async with await psycopg.AsyncConnection.connect(self._config.dsn) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                await conn.execute(
                    """
                    INSERT INTO state_kv (key, value)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (key)
                    DO UPDATE SET value = EXCLUDED.value,
                                  updated_at = NOW()
                    """,
                    (key, json.dumps(dict(value), default=str)),
                )

    async def append_incident_transition(self, entry: Mapping[str, Any]) -> None:
        """Route incident transitions into the same audit chain.

        The audit chain stays the single source of truth for
        tamper-evident lifecycle history. The transition's own
        ``idempotency_key`` upstream (from
        :class:`~fdai.core.incident.IncidentTransition`) plus the
        UNIQUE index on ``entry_hash`` provide dedup + tamper
        evidence; no separate schema is needed for P1.
        """
        payload = dict(entry)
        payload.setdefault("actor", str(payload.get("actor_oid", "fdai")))
        payload.setdefault("action_kind", str(payload.get("kind", "incident.transition")))
        payload.setdefault("mode", "shadow")
        await self.append_audit_entry(payload)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def verify_chain(self) -> bool:
        """Walk the persisted audit chain and recompute every hash."""
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn, row_factory=dict_row
        ) as conn:
            await self._set_statement_timeout(conn)
            cur = await conn.execute(
                """
                SELECT entry, previous_hash, entry_hash
                  FROM audit_log
                 ORDER BY seq ASC
                """
            )
            rows = await cur.fetchall()
        previous = _GENESIS_HASH
        for row in rows:
            if row["previous_hash"] != previous:
                return False
            entry = row["entry"]
            if isinstance(entry, str):
                entry = json.loads(entry)
            expected = _next_hash(previous, entry)
            if row["entry_hash"] != expected:
                return False
            previous = row["entry_hash"]
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _set_statement_timeout(self, conn: psycopg.AsyncConnection[Any]) -> None:
        # SET LOCAL does not accept parametrized values in Postgres; inline
        # the (validated int) timeout literally.
        ms = int(self._config.statement_timeout_ms)
        await conn.execute(f"SET LOCAL statement_timeout = {ms}")


__all__ = ["PostgresStateStore", "PostgresStateStoreConfig"]
