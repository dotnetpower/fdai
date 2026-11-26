"""Stable, optionally age-bounded key pages for retention readers of the Postgres StateStore."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class PostgresStateKeysetMixin:
    """Read ascending keys only; a CAS update never reorders a cursor."""

    async def read_state_keys(
        self: Any, prefix: str, *, after: str = "", limit: int = 128
    ) -> tuple[str, ...]:
        return await _read_key_page(self, prefix, after=after, limit=limit, before=None)

    async def read_state_keys_before(
        self: Any, prefix: str, *, before: datetime, after: str = "", limit: int = 128
    ) -> tuple[str, ...]:
        """Return keys last written before ``before``; any rewrite refreshes the time."""
        if before.tzinfo is None:
            raise ValueError("state key age cutoff MUST be timezone-aware")
        return await _read_key_page(self, prefix, after=after, limit=limit, before=before)


async def _read_key_page(
    store: Any, prefix: str, *, after: str, limit: int, before: datetime | None
) -> tuple[str, ...]:
    if not prefix or limit < 1 or (after and not after.startswith(prefix)):
        raise ValueError("state key page requires a prefix, valid cursor, and positive limit")
    escaped_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    async with store._connection() as conn:
        async with conn.transaction():
            await store._set_statement_timeout(conn)
            cursor = await conn.execute(
                """
                SELECT key FROM state_kv
                 WHERE key LIKE %s ESCAPE '\\'
                   AND key COLLATE "C" > %s
                   AND (%s::timestamptz IS NULL OR updated_at < %s::timestamptz)
                 ORDER BY key COLLATE "C"
                 LIMIT %s
                """,
                (f"{escaped_prefix}%", after, before, before, limit),
            )
            rows = await cursor.fetchall()
    return tuple(str(row["key"]) for row in rows)
