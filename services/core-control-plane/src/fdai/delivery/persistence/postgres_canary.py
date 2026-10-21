"""One indexed latest-success canary read, without audit-history completeness claims."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from fdai.delivery.canary_sequence import MAX_CANARY_AUDITS

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

CANARY_SEQUENCE_SQL = """
SELECT seq, event_id::text AS event_id, LEFT(correlation_id, 129) AS correlation_id,
       actor, action_kind, LEFT(mode::text, 17) AS mode,
       CASE WHEN octet_length(entry::text) <= 8192 THEN entry ELSE NULL END AS entry,
       LEFT(previous_hash, 65) AS previous_hash, LEFT(entry_hash, 65) AS entry_hash
  FROM audit_log
 WHERE actor = 'fdai.canary-job'
   AND action_kind IN ('control_loop.canary', 'control_loop.canary.attempt')
   AND event_id = %s AND correlation_id = %s
 ORDER BY seq ASC
 LIMIT %s
"""


async def read_latest_consumed_canary(store: PostgresStateStore) -> dict[str, Any] | None:
    async with store._connection() as conn:
        async with conn.transaction():
            await store._set_statement_timeout(conn)
            cursor = await conn.execute(LATEST_CANARY_SQL)
            row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def read_consumed_canary_sequence(
    store: PostgresStateStore, *, slot: str
) -> tuple[tuple[dict[str, Any], ...], bool]:
    if not 1 <= len(slot) <= 100 or slot != slot.strip():
        raise ValueError("canary sequence slot must be exact and bounded")
    parameters = (
        uuid5(NAMESPACE_URL, f"fdai.canary://{slot}"),
        f"canary:{slot}",
        MAX_CANARY_AUDITS + 1,
    )
    async with store._connection() as conn:
        async with conn.transaction():
            await store._set_statement_timeout(conn)
            cursor = await conn.execute(CANARY_SEQUENCE_SQL, parameters)
            rows = await cursor.fetchall()
    return tuple(dict(row) for row in rows[:MAX_CANARY_AUDITS]), len(rows) > MAX_CANARY_AUDITS
