"""Read the content-free Operator goal projection under Core's SQL identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
from fdai_service_contracts.handover_observation import handover_observation_fields
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres import PostgresStateStoreConfig


@dataclass(frozen=True, slots=True)
class PostgresHandoverGoalReader:
    """Observe only Operator goal revisions; the migration prohibits Core writes there."""

    config: PostgresStateStoreConfig

    async def read_page(
        self, *, limit: int, offset: int
    ) -> tuple[Sequence[Mapping[str, Any]], int]:
        """Bound one exact namespace page and remove private source fields before return."""
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("handover projection page bounds are invalid")
        async with await psycopg.AsyncConnection.connect(
            self.config.dsn, row_factory=dict_row, connect_timeout=self.config.connect_timeout_s
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self.config.statement_timeout_ms),),
                )
                role = await (await connection.execute("SELECT current_user AS role")).fetchone()
                if role is None or role["role"] != "fdai_core":
                    raise PermissionError("handover projection reader requires the Core SQL role")
                count_cursor = await connection.execute(
                    "SELECT count(*) AS total FROM state_kv "
                    "WHERE starts_with(key, 'operator-handover-goal:')"
                )
                count_row = await count_cursor.fetchone()
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE starts_with(key, 'operator-handover-goal:') "
                    "ORDER BY updated_at DESC, key LIMIT %s OFFSET %s",
                    (limit, offset),
                )
                rows = await cursor.fetchall()
        return (
            tuple(
                handover_observation_fields(row["value"])
                if isinstance(row["value"], Mapping)
                else {}
                for row in rows
            ),
            int(count_row["total"]) if count_row is not None else 0,
        )


__all__ = ["PostgresHandoverGoalReader"]
