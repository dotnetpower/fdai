"""Read legacy T2 proposer failures for one-way recovery backfill."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.runtime.t2_recovery import T2RecoveryLegacyReader


class PostgresT2RecoveryLegacyReader(T2RecoveryLegacyReader):
    """Project only sanitized legacy failure fields from the audit chain."""

    __slots__ = ("_config",)

    def __init__(self, *, config: PostgresStateStoreConfig) -> None:
        self._config = config

    async def read_failures(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        if not 1 <= limit <= 1_000:
            raise ValueError("T2 recovery legacy read limit MUST be in [1, 1000]")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                cursor = await connection.execute(
                    """
                    SELECT event_id::text AS event_id,
                           correlation_id,
                           entry->>'t2_reason' AS t2_reason,
                           COALESCE(entry->>'recorded_at', created_at::text) AS recorded_at
                      FROM audit_log
                     WHERE action_kind = 'control_loop.t2_evaluate'
                       AND entry->>'t2_reason' LIKE 't2_proposer_error:%'
                     ORDER BY seq DESC
                     LIMIT %s
                    """,
                    (limit,),
                )
                rows = await cursor.fetchall()
        return tuple(
            {
                "event_id": str(row["event_id"]),
                "correlation_id": str(row.get("correlation_id") or row["event_id"]),
                "t2_reason": str(row["t2_reason"]),
                "recorded_at": str(row["recorded_at"]),
            }
            for row in rows
        )


__all__ = ["PostgresT2RecoveryLegacyReader"]
