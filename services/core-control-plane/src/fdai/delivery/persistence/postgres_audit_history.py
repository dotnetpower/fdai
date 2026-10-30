"""Bounded read-only audit history behind the PostgreSQL StateStore facade."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Protocol

from psycopg import AsyncConnection, sql

from fdai.delivery.persistence.postgres_audit_fields import json_object
from fdai.shared.providers.state_store import AUDIT_CHAIN_ENTRY_FIELDS

if TYPE_CHECKING:
    from fdai.delivery.persistence.postgres import PostgresStateStore

# Read only stored headers; an unsorted LIMIT bounds corrupt duplicate-hash branching.
_CHAIN_WINDOW_SQL = sql.SQL(
    "WITH RECURSIVE recent(entry,depth) AS ("
    "(SELECT saga_header,1 FROM audit_log "
    "WHERE saga_header->>'entry_hash'=%s LIMIT 2) "
    "UNION ALL SELECT parent.saga_header,recent.depth+1 FROM recent "
    "CROSS JOIN LATERAL (SELECT saga_header FROM audit_log "
    "WHERE saga_header->>'entry_hash'=recent.entry->>'prev_hash' LIMIT 2) parent "
    "WHERE recent.depth<%s) SELECT entry FROM recent LIMIT %s"
)


class _AuditHistoryContext(Protocol):
    _compact_audit_schema_available: bool | None

    def _connection(
        self,
    ) -> AbstractAsyncContextManager[AsyncConnection[dict[str, Any]]]: ...

    async def _set_statement_timeout(self, conn: AsyncConnection[Any]) -> None: ...


class PostgresAuditChainWindowMixin:
    _compact_audit_schema_available: bool | None = None

    async def supports_compact_audit_checkpoint(self: _AuditHistoryContext) -> bool:
        if self._compact_audit_schema_available is None:
            async with self._connection() as conn:
                async with conn.transaction():
                    await self._set_statement_timeout(conn)
                    row = await (
                        await conn.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_attribute "
                            "WHERE attrelid='audit_log'::regclass AND attname='saga_header' "
                            "AND attgenerated='s' AND NOT attisdropped) "
                            "AND EXISTS(SELECT 1 FROM pg_index "
                            "WHERE indexrelid=to_regclass('audit_log_saga_header_hash_idx') "
                            "AND indrelid='audit_log'::regclass AND indisvalid AND indisready) "
                            "AS available"
                        )
                    ).fetchone()
            if row is None:
                raise RuntimeError("compact audit schema readiness returned no result")
            self._compact_audit_schema_available = bool(row["available"])
        return self._compact_audit_schema_available

    async def read_audit_chain_window(
        self: _AuditHistoryContext, *, start_seq: int, end_seq: int, head_hash: str
    ) -> tuple[dict[str, Any], ...]:
        return await read_audit_chain_window(
            self, start_seq=start_seq, end_seq=end_seq, head_hash=head_hash
        )


async def read_audit_chain_window(
    store: _AuditHistoryContext, *, start_seq: int, end_seq: int, head_hash: str
) -> tuple[dict[str, Any], ...]:
    if (
        type(start_seq) is not int
        or type(end_seq) is not int
        or start_seq < 0
        or not 1 <= end_seq - start_seq <= 512
        or not isinstance(head_hash, str)
        or len(head_hash) != 64
        or any(character not in "0123456789abcdef" for character in head_hash)
    ):
        raise ValueError("audit chain window must contain between 1 and 512 sequences")
    async with store._connection() as conn:
        async with conn.transaction():
            await store._set_statement_timeout(conn)
            cursor = await conn.execute(
                _CHAIN_WINDOW_SQL,
                (head_hash, end_seq - start_seq, end_seq - start_seq + 1),
            )
            rows = await cursor.fetchall()
    return tuple(dict(json_object(row["entry"])) for row in reversed(rows))


async def read_audit_entries(
    store: PostgresStateStore, *, limit: int
) -> tuple[tuple[dict[str, Any], ...], bool]:
    """Return an oldest-first bounded snapshot, explicitly reporting omitted rows."""
    if type(limit) is not int or not 1 <= limit <= 512:
        raise ValueError("audit history limit must be between 1 and 512")
    async with store._connection() as conn:
        async with conn.transaction():
            await store._set_statement_timeout(conn)
            cursor = await conn.execute(
                "SELECT entry FROM audit_log ORDER BY seq ASC LIMIT %s", (limit + 1,)
            )
            rows = await cursor.fetchall()
    return tuple(dict(json_object(row["entry"])) for row in rows[:limit]), len(rows) > limit


async def read_audit_chain_entries(
    store: PostgresStateStore, *, limit: int
) -> tuple[tuple[dict[str, Any], ...], bool]:
    """Return the Saga chain's own records, filtered before the limit.

    The audit table is shared by every writer, so a plain bounded read stops being a valid
    view of the chain once unrelated rows pass the limit. The condition mirrors
    ``is_audit_chain_record``.
    """
    if type(limit) is not int or not 1 <= limit <= 512:
        raise ValueError("audit history limit must be between 1 and 512")
    async with store._connection() as conn:
        async with conn.transaction():
            await store._set_statement_timeout(conn)
            cursor = await conn.execute(
                "SELECT entry FROM audit_log "
                "WHERE jsonb_exists_all(entry::jsonb, %s) "
                "OR (entry->>'actor' = 'Saga' AND entry->>'action_kind' = 'audit.record') "
                "ORDER BY seq ASC LIMIT %s",
                (sorted(AUDIT_CHAIN_ENTRY_FIELDS), limit + 1),
            )
            rows = await cursor.fetchall()
    return tuple(dict(json_object(row["entry"])) for row in rows[:limit]), len(rows) > limit


async def list_incident_evidence(
    store: PostgresStateStore, *, correlation_id: str, limit: int
) -> tuple[tuple[dict[str, object], ...], bool]:
    """Keep the latest incident window in chronological order with recorded metadata."""
    if not correlation_id or limit < 1 or limit > 500:
        raise ValueError("incident evidence correlation_id and limit are invalid")
    async with store._connection() as conn:
        async with conn.transaction():
            await store._set_statement_timeout(conn)
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
            "entry": dict(json_object(row["entry"])),
        }
        for row in reversed(selected)
    )
    return projected, truncated
