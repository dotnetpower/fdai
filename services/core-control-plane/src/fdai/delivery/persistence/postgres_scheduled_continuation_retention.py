"""Production deleters for expired scheduled continuation copies.

The retention worker owns ordering, grace, legal hold, and the deletion fence. This
adapter owns the physical statements for the three PostgreSQL-resident copies of one
scheduled result: the projected conversation turn, the source briefing run, and the
anchor row. Every deletion is confirmed by an independent readback on a separate
connection, so a committed statement that left a row behind fails the purge instead of
reporting completed deletion.
"""

# ruff: noqa: S608 - SQL identifiers are module constants; runtime values are parametrized.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.scheduler.continuation_retention import RetentionTarget
from fdai.delivery.persistence.postgres_scheduled_continuation import (
    PostgresScheduledContinuationStoreConfig,
    psycopg_dsn,
)
from fdai.shared.providers.scheduled_continuation import (
    ScheduledConversationAnchor,
    projected_turn_id_for_anchor,
)


class RetentionReadbackError(RuntimeError):
    """A copy survived its deletion statement, so the purge MUST stay pending."""


@dataclass(frozen=True, slots=True)
class RetentionStatement:
    """One target's delete statement plus the independent absence readback."""

    delete_sql: str
    readback_sql: str
    params: tuple[object, ...]


_TURN_PREDICATE: Final = (
    "FROM conversation_turn WHERE principal_id = %s AND conversation_id = %s "
    "AND (turn_id = %s OR metadata->>'anchor_id' = %s)"
)
_RESULT_PREDICATE: Final = "FROM briefing_run WHERE principal_id = %s AND run_id = %s"
_ANCHOR_PREDICATE: Final = "FROM scheduled_conversation_anchor WHERE anchor_id = %s"


def retention_statement(
    *, target: RetentionTarget, anchor: ScheduledConversationAnchor
) -> RetentionStatement:
    """Return the scoped deletion and readback for one target.

    Every predicate is bound to this anchor's principal, conversation, run, or anchor id,
    so unrelated scopes and unrelated turns in the same conversation are never touched.
    The anchor delete additionally requires the `expired` state, which fences a late
    writer that reactivated the row between the worker's read and this statement.
    """
    match target:
        case RetentionTarget.PROJECTED_TURN:
            params: tuple[object, ...] = (
                anchor.owner_principal_id,
                anchor.origin.conversation_ref,
                projected_turn_id_for_anchor(anchor.anchor_id),
                anchor.anchor_id,
            )
            return RetentionStatement(
                delete_sql=f"DELETE {_TURN_PREDICATE}",
                readback_sql=f"SELECT 1 {_TURN_PREDICATE} LIMIT 1",
                params=params,
            )
        case RetentionTarget.SOURCE_RESULT:
            return RetentionStatement(
                delete_sql=f"DELETE {_RESULT_PREDICATE}",
                readback_sql=f"SELECT 1 {_RESULT_PREDICATE} LIMIT 1",
                params=(anchor.owner_principal_id, anchor.run_id),
            )
        case RetentionTarget.ANCHOR:
            return RetentionStatement(
                delete_sql=f"DELETE {_ANCHOR_PREDICATE} AND state = 'expired'",
                readback_sql=f"SELECT 1 {_ANCHOR_PREDICATE} LIMIT 1",
                params=(anchor.anchor_id,),
            )
        case _:
            raise ValueError(f"unsupported scheduled continuation retention target: {target!r}")


class PostgresScheduledContinuationDeleter:
    """Delete one retained copy and prove its absence on an independent connection."""

    def __init__(self, *, config: PostgresScheduledContinuationStoreConfig) -> None:
        self._config: Final = config

    async def delete(self, *, target: RetentionTarget, anchor: ScheduledConversationAnchor) -> None:
        """Delete the target, then fail when an independent read still finds it.

        Deleting an absent copy is a successful no-op. A surviving row raises
        `RetentionReadbackError`, which the worker records as a resumable partial purge.
        """
        statement = retention_statement(target=target, anchor=anchor)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await connection.execute(statement.delete_sql, statement.params)
        async with await self._connect() as readback:
            await self._timeout(readback)
            cursor = await readback.execute(statement.readback_sql, statement.params)
            if await cursor.fetchone() is not None:
                raise RetentionReadbackError(
                    f"scheduled continuation {target.value} survived deletion"
                )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            psycopg_dsn(self._config.dsn),
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout}")


__all__ = [
    "PostgresScheduledContinuationDeleter",
    "RetentionReadbackError",
    "RetentionStatement",
    "retention_statement",
]
