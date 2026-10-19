"""One indexed latest-success canary read, without audit-history completeness claims."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.delivery.persistence.postgres import PostgresStateStore

LATEST_CANARY_SQL = """
SELECT seq, event_id::text AS event_id, LEFT(correlation_id, 129) AS correlation_id,
       actor, action_kind, LEFT(mode::text, 17) AS mode,
       CASE WHEN octet_length(entry::text) <= 8192 THEN entry ELSE NULL END AS entry,
       LEFT(previous_hash, 65) AS previous_hash, LEFT(entry_hash, 65) AS entry_hash
  FROM audit_log
 WHERE action_kind = 'control_loop.canary'
   AND actor = 'fdai.canary-job'
   AND entry ->> 'outcome' = 'success'
 ORDER BY seq DESC
 LIMIT 1
"""


async def read_latest_consumed_canary(store: PostgresStateStore) -> dict[str, Any] | None:
    async with store._connection() as conn:
        async with conn.transaction():
            await store._set_statement_timeout(conn)
            cursor = await conn.execute(LATEST_CANARY_SQL)
            row = await cursor.fetchone()
    return dict(row) if row is not None else None
