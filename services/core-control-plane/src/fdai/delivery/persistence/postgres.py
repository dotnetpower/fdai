"""PostgresStateStore - real `StateStore` on PostgreSQL via psycopg 3.

Realizes :class:`~fdai.shared.providers.state_store.StateStore`
against the ``audit_log`` + ``state_kv`` tables created by the alembic
migrations. Every audit entry is hash-chained to the prior entry (matching
:class:`~fdai.shared.providers.testing.state_store.InMemoryStateStore`)
so :func:`verify_chain` can be used across the two backends
interchangeably.

Notes on the wire choice:

- Psycopg 3 and its official pool package provide the async wire boundary.
- The bounded pool lives inside this adapter, so ``core/`` never sees a
    driver call and event fan-out does not create one TCP connection per query.
- ``previous_hash`` / ``entry_hash`` semantics are enforced in the same
  in-memory canonical serialization as the fake, keeping the two
  implementations swappable without recomputing hashes on migration.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from fdai.delivery.persistence.postgres_approval_guard import (
    compare_and_set_state_with_approval_guard as _compare_and_set_state_with_approval_guard,
)
from fdai.delivery.persistence.postgres_audit_fields import (
    audit_action_kind as _audit_action_kind,
)
from fdai.delivery.persistence.postgres_audit_fields import (
    audit_actor as _audit_actor,
)
from fdai.delivery.persistence.postgres_audit_fields import (
    audit_event_id as _audit_event_id,
)
from fdai.delivery.persistence.postgres_audit_fields import (
    incident_lock as _incident_lock,
)
from fdai.delivery.persistence.postgres_audit_fields import (
    json_object as _json_object,
)
from fdai.shared.providers.audit_hash import GENESIS_HASH, canonical_entry, next_hash
from fdai.shared.providers.state_store import (
    IncidentAppendStatus,
    IncidentOpenAppendResult,
    IncidentWriteConflictError,
    StateStore,
    classify_incident_append,
    incident_number_for,
)

_GENESIS_HASH: Final[str] = GENESIS_HASH

# Deterministic 63-bit signed key for `pg_advisory_xact_lock`. Chosen once
# so every FDAI process contends on the same lock when appending to the
# hash-chained audit log; a different codebase deriving its own key from
# the string "fdai.audit_log" cannot collide by accident.
_AUDIT_APPEND_LOCK_KEY: Final[int] = 0x0FDA10AAAAAA01
_POOL_MIN_SIZE: Final[int] = 1
_POOL_MAX_SIZE: Final[int] = 4


_next_hash = next_hash
_canonical = canonical_entry


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
        self._pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            conninfo=config.dsn,
            kwargs={
                "connect_timeout": config.connect_timeout_s,
                "row_factory": dict_row,
            },
            min_size=_POOL_MIN_SIZE,
            max_size=_POOL_MAX_SIZE,
            open=False,
            timeout=float(config.connect_timeout_s),
            name="fdai-state-store",
        )
        self._pool_open = False
        self._pool_open_lock = asyncio.Lock()

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
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                await self._append_audit_in_transaction(conn, payload)

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        async with self._connection() as conn:
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
        async with self._connection() as conn:
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

    async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    """
                    INSERT INTO state_kv (key, value)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (key) DO NOTHING
                    RETURNING key
                    """,
                    (key, json.dumps(dict(value), default=str)),
                )
                row = await cursor.fetchone()
        return row is not None

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    """
                    INSERT INTO state_kv (key, value)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (key) DO NOTHING
                    RETURNING key
                    """,
                    (key, json.dumps(dict(value), default=str)),
                )
                if await cursor.fetchone() is None:
                    return False
                await self._append_audit_in_transaction(conn, dict(audit_entry))
        return True

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if expected_revision < 0:
            raise ValueError("expected_revision MUST be >= 0")
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    """
                    UPDATE state_kv
                       SET value = %s::jsonb,
                           updated_at = NOW()
                     WHERE key = %s
                       AND COALESCE(value ->> 'revision', '0') = %s
                    RETURNING key
                    """,
                    (
                        json.dumps(dict(value), default=str),
                        key,
                        str(expected_revision),
                    ),
                )
                if await cursor.fetchone() is None:
                    return False
                await self._append_audit_in_transaction(conn, dict(audit_entry))
        return True

    async def compare_and_set_state_with_approval_guard(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        approval_key: str,
        expected_approval_revision: int,
        expected_approval_process_id: str,
        expected_approval_step_id: str,
        expected_approval_attempt: int,
        expected_approval_requester: str,
        expected_approval_quorum: int,
        expected_no_self_approval: bool,
        expected_approval_decisions: tuple[tuple[str, str, str], ...],
        evaluated_at: datetime,
        admission_verified_at: datetime,
        admission_valid_until: datetime,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        async with self._connection() as conn:
            return await _compare_and_set_state_with_approval_guard(
                connection=conn,
                set_statement_timeout=self._set_statement_timeout,
                append_audit_in_transaction=self._append_audit_in_transaction,
                key=key,
                value=value,
                expected_revision=expected_revision,
                approval_key=approval_key,
                expected_approval_revision=expected_approval_revision,
                expected_approval_process_id=expected_approval_process_id,
                expected_approval_step_id=expected_approval_step_id,
                expected_approval_attempt=expected_approval_attempt,
                expected_approval_requester=expected_approval_requester,
                expected_approval_quorum=expected_approval_quorum,
                expected_no_self_approval=expected_no_self_approval,
                expected_approval_decisions=expected_approval_decisions,
                evaluated_at=evaluated_at,
                admission_verified_at=admission_verified_at,
                admission_valid_until=admission_valid_until,
                audit_entry=audit_entry,
            )

    async def find_state(
        self,
        prefix: str,
        *,
        field: str,
        value: str,
    ) -> Mapping[str, Any] | None:
        if not field.replace("_", "").isalnum():
            raise ValueError("state field MUST be an ASCII identifier")
        escaped_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    """
                    SELECT value
                      FROM state_kv
                     WHERE key LIKE %s ESCAPE '\\'
                       AND value ->> %s = %s
                     ORDER BY updated_at DESC, key DESC
                     LIMIT 1
                    """,
                    (f"{escaped_prefix}%", field, value),
                )
                row = await cursor.fetchone()
        return None if row is None else _json_object(row["value"])

    async def read_states(
        self,
        prefix: str,
        *,
        limit: int,
    ) -> tuple[Mapping[str, Any], ...]:
        if limit < 1:
            raise ValueError("limit MUST be >= 1")
        escaped_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    """
                    SELECT value
                      FROM state_kv
                     WHERE key LIKE %s ESCAPE '\\'
                     ORDER BY updated_at DESC, key DESC
                     LIMIT %s
                    """,
                    (f"{escaped_prefix}%", limit),
                )
                rows = await cursor.fetchall()
        return tuple(_json_object(row["value"]) for row in rows)

    async def delete_states_beyond(self, prefix: str, *, retain_newest: int) -> int:
        if not prefix:
            raise ValueError("prefix MUST be non-empty")
        if retain_newest < 1:
            raise ValueError("retain_newest MUST be >= 1")
        escaped_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    """
                    DELETE FROM state_kv
                     WHERE key IN (
                           SELECT key
                             FROM state_kv
                            WHERE key LIKE %s ESCAPE '\\'
                            ORDER BY updated_at DESC, key DESC
                           OFFSET %s
                     )
                    """,
                    (f"{escaped_prefix}%", retain_newest),
                )
        return cursor.rowcount if cursor.rowcount > 0 else 0

    async def read_state_page(
        self,
        prefix: str,
        *,
        limit: int,
        offset: int = 0,
        field: str | None = None,
        value: str | None = None,
    ) -> tuple[tuple[Mapping[str, Any], ...], int]:
        if limit < 1 or offset < 0:
            raise ValueError("limit MUST be >= 1 and offset MUST be >= 0")
        if field is not None and not field.replace("_", "").isalnum():
            raise ValueError("state field MUST be an ASCII identifier")
        if (field is None) != (value is None):
            raise ValueError("state field and value MUST be supplied together")
        escaped_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filter_sql = "" if field is None else "AND value ->> %s = %s"
        filter_params: tuple[object, ...] = () if field is None else (field, value)
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                count_cursor = await conn.execute(
                    f"""SELECT COUNT(*) AS total FROM state_kv
                         WHERE key LIKE %s ESCAPE '\\' {filter_sql}""",  # noqa: S608
                    (f"{escaped_prefix}%", *filter_params),
                )
                count_row = await count_cursor.fetchone()
                page_cursor = await conn.execute(
                    f"""SELECT value FROM state_kv
                         WHERE key LIKE %s ESCAPE '\\' {filter_sql}
                         ORDER BY updated_at DESC, key DESC
                         LIMIT %s OFFSET %s""",  # noqa: S608
                    (f"{escaped_prefix}%", *filter_params, limit, offset),
                )
                rows = await page_cursor.fetchall()
        total = int(count_row["total"]) if count_row is not None else 0
        return tuple(_json_object(row["value"]) for row in rows), total

    async def append_incident_transition(self, entry: Mapping[str, Any]) -> IncidentAppendStatus:
        """Route incident transitions into the same audit chain.

        The audit chain stays the single source of truth for
        tamper-evident lifecycle history. The transition's own
        ``idempotency_key`` upstream (from
        :class:`~fdai.core.incident.IncidentTransition`) plus the
        idempotency-key advisory lock and audit lookup provide dedup;
        the audit hash chain provides tamper evidence.
        """
        payload = dict(entry)
        if payload.get("kind") == "incident.open":
            raise ValueError("incident.open MUST use append_incident_open")
        incident_id = str(payload.get("incident_id") or "")
        if not incident_id:
            raise ValueError("incident transition MUST carry a non-empty incident_id")
        payload.setdefault("actor", str(payload.get("actor_oid", "fdai")))
        payload.setdefault("action_kind", str(payload.get("kind", "incident.transition")))
        payload.setdefault("mode", "shadow")
        async with self._connection() as conn:
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
                history = tuple(_json_object(row["entry"]) for row in rows)
                status = classify_incident_append(history, payload)
                if status is IncidentAppendStatus.DUPLICATE:
                    return status
                await self._append_audit_in_transaction(conn, payload)
                return status

    async def append_incident_open(
        self,
        entry: Mapping[str, Any],
        *,
        number_prefix: str,
    ) -> IncidentOpenAppendResult:
        """Allocate and append one numbered incident.open in one transaction."""
        payload = dict(entry)
        if payload.get("kind") != "incident.open":
            raise ValueError("append_incident_open requires kind=incident.open")
        incident_id = str(payload.get("incident_id") or "")
        if not incident_id:
            raise ValueError("incident open MUST carry a non-empty incident_id")
        incident_number_for(number_prefix, 0)
        payload.setdefault("actor", str(payload.get("actor_oid", "fdai")))
        payload.setdefault("action_kind", "incident.open")
        payload.setdefault("mode", "shadow")
        counter_key = f"incident-number-sequence:{number_prefix}"
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (_incident_lock(incident_id),),
                )
                history_cursor = await conn.execute(
                    """
                    SELECT entry
                    FROM audit_log
                    WHERE entry->>'incident_id' = %s
                      AND entry->>'kind' LIKE 'incident.%%'
                    ORDER BY seq ASC
                    """,
                    (incident_id,),
                )
                rows = await history_cursor.fetchall()
                history = tuple(_json_object(row["entry"]) for row in rows)
                status = classify_incident_append(history, payload)
                if status is IncidentAppendStatus.DUPLICATE:
                    existing = next(row for row in history if row.get("kind") == "incident.open")
                    raw_number = existing.get("incident_number")
                    return IncidentOpenAppendResult(
                        status=status,
                        incident_number=raw_number if isinstance(raw_number, str) else None,
                    )
                sequence_cursor = await conn.execute(
                    """
                    INSERT INTO state_kv (key, value)
                    VALUES (
                        %s,
                        JSONB_BUILD_OBJECT(
                            'revision', 1,
                            'number_prefix', %s::TEXT,
                            'last_sequence', 0
                        )
                    )
                    ON CONFLICT (key) DO UPDATE
                       SET value = JSONB_BUILD_OBJECT(
                               'revision', (state_kv.value->>'revision')::INTEGER + 1,
                               'number_prefix', %s::TEXT,
                               'last_sequence',
                                   (state_kv.value->>'last_sequence')::INTEGER + 1
                           ),
                           updated_at = NOW()
                     WHERE (state_kv.value->>'number_prefix') = %s
                       AND (state_kv.value->>'last_sequence')::INTEGER < 9999
                    RETURNING (value->>'last_sequence')::INTEGER AS last_sequence
                    """,
                    (counter_key, number_prefix, number_prefix, number_prefix),
                )
                sequence_row = await sequence_cursor.fetchone()
                if sequence_row is None:
                    raise IncidentWriteConflictError(
                        f"incident number sequence exhausted for {number_prefix}"
                    )
                incident_number = incident_number_for(
                    number_prefix,
                    int(sequence_row["last_sequence"]),
                )
                payload["incident_number"] = incident_number
                await self._append_audit_in_transaction(conn, payload)
                return IncidentOpenAppendResult(
                    status=IncidentAppendStatus.APPLIED,
                    incident_number=incident_number,
                )

    async def read_incident_transitions(self) -> tuple[Mapping[str, Any], ...]:
        """Return lifecycle audit payloads in append order for recovery."""
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    """
                    SELECT entry
                    FROM audit_log
                    WHERE action_kind IN (
                        'incident.open',
                        'incident.members',
                        'incident.severity',
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

    async def list_incident_evidence(
        self,
        *,
        correlation_id: str,
        limit: int,
    ) -> tuple[tuple[Mapping[str, object], ...], bool]:
        """Return latest bounded audit rows for one exact incident correlation."""
        if not correlation_id or limit < 1 or limit > 500:
            raise ValueError("incident evidence correlation_id and limit are invalid")
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    """
                    SELECT seq,
                           event_id::text AS event_id,
                           correlation_id,
                           actor,
                           action_kind,
                           mode,
                           created_at AS recorded_at,
                           entry
                      FROM audit_log
                     WHERE correlation_id = %s
                     ORDER BY seq DESC
                     LIMIT %s
                    """,
                    (correlation_id, limit + 1),
                )
                rows = await cursor.fetchall()
        truncated = len(rows) > limit
        selected = rows[:limit]
        projected = tuple(
            {
                "seq": int(row["seq"]),
                "event_id": str(row["event_id"]),
                "correlation_id": str(row["correlation_id"]),
                "actor": str(row["actor"]),
                "action_kind": str(row["action_kind"]),
                "mode": str(row["mode"]),
                "recorded_at": row["recorded_at"].isoformat(),
                "entry": dict(_json_object(row["entry"])),
            }
            for row in reversed(selected)
        )
        return projected, truncated

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
        async with self._connection() as conn:
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

    async def aclose(self) -> None:
        """Close the adapter-owned pool after every runtime consumer has stopped."""

        async with self._pool_open_lock:
            if not self._pool_open:
                return
            self._pool_open = False
            await self._pool.close()

    async def _ensure_pool(self) -> None:
        if self._pool_open:
            return
        async with self._pool_open_lock:
            if self._pool_open:
                return
            await self._pool.open(
                wait=True,
                timeout=float(self._config.connect_timeout_s),
            )
            self._pool_open = True

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[psycopg.AsyncConnection[dict[str, Any]]]:
        await self._ensure_pool()
        async with self._pool.connection(
            timeout=float(self._config.connect_timeout_s),
        ) as connection:
            yield connection

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
        cursor = await conn.execute("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1")
        row = await cursor.fetchone()
        previous = row["entry_hash"] if row is not None else _GENESIS_HASH
        entry_hash = _next_hash(previous, payload)
        event_id = _audit_event_id(payload)
        actor = _audit_actor(payload)
        action_kind = _audit_action_kind(payload)
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
                payload.get("correlation_id"),
                actor,
                action_kind,
                mode,
                _canonical(payload),
                previous,
                entry_hash,
            ),
        )


__all__ = ["PostgresStateStore", "PostgresStateStoreConfig"]
