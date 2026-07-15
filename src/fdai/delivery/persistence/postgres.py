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

from fdai.shared.providers.state_store import (
    IncidentAppendStatus,
    StateStore,
    classify_incident_append,
)

_GENESIS_HASH: Final[str] = "0" * 64

# Deterministic 63-bit signed key for `pg_advisory_xact_lock`. Chosen once
# so every FDAI process contends on the same lock when appending to the
# hash-chained audit log; a different codebase deriving its own key from
# the string "fdai.audit_log" cannot collide by accident.
_AUDIT_APPEND_LOCK_KEY: Final[int] = 0x0FDA10AAAAAA01


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

    connect_timeout_s: int = 10
    """Bound the TCP + auth handshake so a dead DB fails fast instead of
    hanging the event loop for ~2 minutes on the kernel TCP retry budget
    (``statement_timeout`` only starts *after* connect succeeds)."""


class PostgresStateStore(StateStore):
    """Async :class:`StateStore` implementation for PostgreSQL."""

    def __init__(self, *, config: PostgresStateStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresStateStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
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
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                await self._append_audit_in_transaction(conn, payload)

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
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
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
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

    async def append_incident_transition(
        self, entry: Mapping[str, Any]
    ) -> IncidentAppendStatus:
        """Route incident transitions into the same audit chain.

        The audit chain stays the single source of truth for
        tamper-evident lifecycle history. The transition's own
        ``idempotency_key`` upstream (from
        :class:`~fdai.core.incident.IncidentTransition`) plus the
        idempotency-key advisory lock and audit lookup provide dedup;
        the audit hash chain provides tamper evidence.
        """
        payload = dict(entry)
        incident_id = str(payload.get("incident_id") or "")
        if not incident_id:
            raise ValueError("incident transition MUST carry a non-empty incident_id")
        payload.setdefault("actor", str(payload.get("actor_oid", "fdai")))
        payload.setdefault("action_kind", str(payload.get("kind", "incident.transition")))
        payload.setdefault("mode", "shadow")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (_incident_lock(incident_id),),
                )
                cursor = await conn.execute(
                    """
                    SELECT entry
                    FROM audit_log
                    WHERE entry->>'incident_id' = %s
                      AND entry->>'kind' LIKE 'incident.%%'
                    ORDER BY seq ASC
                    """,
                    (incident_id,),
                )
                rows = await cursor.fetchall()
                history = tuple(_json_object(row[0]) for row in rows)
                status = classify_incident_append(history, payload)
                if status is IncidentAppendStatus.DUPLICATE:
                    return status
                await self._append_audit_in_transaction(conn, payload)
                return status

    async def read_incident_transitions(self) -> tuple[Mapping[str, Any], ...]:
        """Return lifecycle audit payloads in append order for recovery."""
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    """
                    SELECT entry
                    FROM audit_log
                    WHERE entry->>'kind' IN (
                        'incident.open',
                        'incident.members',
                        'incident.assigned',
                        'incident.ticket',
                        'incident.transition'
                    )
                    ORDER BY seq ASC
                    """
                )
                rows = await cursor.fetchall()
        entries: list[Mapping[str, Any]] = []
        for row in rows:
            entry = row["entry"]
            if not isinstance(entry, dict):
                raise RuntimeError("incident lifecycle audit entry is not a JSON object")
            entries.append(dict(entry))
        return tuple(entries)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def verify_chain(self) -> bool:
        """Walk the persisted audit chain and recompute every hash.

        Uses a server-side cursor (streaming) so a multi-gigabyte audit
        log does not buffer entirely in memory. Each row is hashed and
        chained as it arrives; the statement_timeout still bounds total
        runtime so a runaway verify does not lock a connection forever.
        """
        previous = _GENESIS_HASH
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            await self._set_statement_timeout(conn)
            async with conn.cursor(name="fdai_verify_chain") as cur:
                await cur.execute(
                    """
                    SELECT entry, previous_hash, entry_hash
                      FROM audit_log
                     ORDER BY seq ASC
                    """
                )
                async for row in cur:
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

    async def _append_audit_in_transaction(
        self,
        conn: psycopg.AsyncConnection[Any],
        payload: Mapping[str, Any],
    ) -> None:
        mode = str(payload.get("mode", "shadow"))
        if mode not in ("shadow", "enforce"):
            raise ValueError(f"audit entry mode MUST be 'shadow'|'enforce', got {mode!r}")
        await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_AUDIT_APPEND_LOCK_KEY,))
        cursor = await conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        )
        row = await cursor.fetchone()
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
                str(payload.get("event_id") or "00000000-0000-0000-0000-000000000000"),
                payload.get("correlation_id"),
                str(payload.get("actor", "fdai")),
                str(payload.get("action_kind", "unknown")),
                mode,
                _canonical(payload),
                previous,
                entry_hash,
            ),
        )


def _incident_lock(incident_id: str) -> int:
    """Return a stable positive 63-bit per-incident advisory-lock key."""
    digest = hashlib.sha256(incident_id.encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) & ((1 << 63) - 1)


def _json_object(value: object) -> Mapping[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise RuntimeError("incident lifecycle audit entry is not a JSON object")


__all__ = ["PostgresStateStore", "PostgresStateStoreConfig"]
