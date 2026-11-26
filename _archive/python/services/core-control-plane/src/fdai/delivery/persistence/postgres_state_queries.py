"""Bounded tracked-state deletion and exact-total narrow page queries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import psycopg

from fdai.delivery.persistence.postgres_audit_fields import json_object


async def read_state_page(
    connection: psycopg.AsyncConnection[Any],
    *,
    escaped_prefix: str,
    filter_sql: str,
    filter_params: tuple[object, ...],
    limit: int,
    offset: int,
) -> tuple[tuple[Mapping[str, Any], ...], int]:
    """Fetch exact totals and key-selected bodies in the caller's transaction snapshot."""
    cursor = await connection.execute(
        f"""
        WITH page AS MATERIALIZED (
            SELECT key, updated_at FROM state_kv
             WHERE key LIKE %s ESCAPE '\\' {filter_sql}
             ORDER BY updated_at DESC, key DESC LIMIT %s OFFSET %s
        ), total AS (
            SELECT count(*) AS total FROM state_kv
             WHERE key LIKE %s ESCAPE '\\' {filter_sql}
        )
        SELECT total.total, body.value
          FROM total LEFT JOIN page ON TRUE
          LEFT JOIN state_kv AS body ON body.key = page.key
         ORDER BY page.updated_at DESC, page.key DESC
        """,  # noqa: S608 - the caller supplies only fixed private predicate literals
        (
            f"{escaped_prefix}%",
            *filter_params,
            limit,
            offset,
            f"{escaped_prefix}%",
            *filter_params,
        ),
    )
    rows = await cursor.fetchall()
    if not rows:
        raise RuntimeError("state page returned no total accounting")
    return (
        tuple(json_object(row["value"]) for row in rows if row["value"] is not None),
        int(rows[0]["total"]),
    )


async def delete_states_beyond(
    connection: psycopg.AsyncConnection[Any],
    *,
    escaped_prefix: str,
    retain_newest: int,
    path: tuple[str, ...] | None,
    value: str | None,
    set_statement_timeout: Callable[[psycopg.AsyncConnection[Any]], Awaitable[None]],
) -> int:
    """Commit bounded batches; the caller owns input validation and the total deadline."""
    filter_sql = "AND value #>> %s::text[] = %s" if path is not None else ""
    filter_params: tuple[object, ...] = (list(path), value) if path is not None else ()
    removed = 0
    batch_size = 1000
    while True:
        async with connection.transaction():
            await set_statement_timeout(connection)
            await connection.execute("SET LOCAL lock_timeout = '1s'")
            cursor = await connection.execute(
                f"""
                WITH doomed AS MATERIALIZED (
                    SELECT key, updated_at, xmin AS version
                      FROM state_kv
                     WHERE key LIKE %s ESCAPE '\\'
                     {filter_sql}
                     ORDER BY updated_at DESC, key DESC
                     LIMIT %s OFFSET %s
                ), deleted AS (
                    DELETE FROM state_kv
                     USING doomed
                     WHERE state_kv.key = doomed.key
                       AND state_kv.updated_at = doomed.updated_at
                       AND state_kv.xmin = doomed.version
                       {filter_sql}
                     RETURNING state_kv.key
                )
                SELECT (SELECT count(*) FROM doomed) AS selected,
                       count(*) AS deleted FROM deleted
                """,  # noqa: S608 - the optional predicate is a fixed private literal
                (
                    f"{escaped_prefix}%",
                    *filter_params,
                    batch_size,
                    retain_newest,
                    *filter_params,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("state retention returned no deletion accounting")
            selected, deleted = int(row["selected"]), int(row["deleted"])
        removed += deleted
        if selected < batch_size:
            return removed
        if deleted == 0:
            raise RuntimeError(
                "state retention made no progress; retry after concurrent writes settle"
            )
