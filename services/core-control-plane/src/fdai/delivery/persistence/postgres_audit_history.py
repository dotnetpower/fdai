"""Bounded read-only audit history behind the PostgreSQL StateStore facade."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fdai.delivery.persistence.postgres_audit_fields import json_object
from fdai.shared.providers.state_store import AUDIT_CHAIN_ENTRY_FIELDS

if TYPE_CHECKING:
    from fdai.delivery.persistence.postgres import PostgresStateStore


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
