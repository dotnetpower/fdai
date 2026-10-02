"""Read-only Thor/Saga action audit pages for forecast action history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.delivery.forecast_history_sources import (
    ActionAuditHistoryRead,
    ActionAuditHistoryRow,
)

_MAX_WINDOW = timedelta(days=31)


@dataclass(frozen=True, slots=True)
class PostgresForecastActionHistoryConfig:
    dsn: str
    statement_timeout_ms: int = 3_000
    connect_timeout_s: int = 3

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("forecast action history DSN MUST NOT be empty")
        if not 1 <= self.statement_timeout_ms <= 10_000 or not 1 <= self.connect_timeout_s <= 10:
            raise ValueError("forecast action history database deadlines are out of bounds")


class PostgresForecastActionHistoryReader:
    """Read bounded action-save audit rows through the reviewed definer function."""

    def __init__(self, *, config: PostgresForecastActionHistoryConfig) -> None:
        self._config = config

    async def read_action_audit(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        limit: int,
    ) -> ActionAuditHistoryRead:
        if not subject_ref or subject_ref != subject_ref.strip() or len(subject_ref) > 512:
            raise ValueError("forecast action history requires one exact bounded subject")
        if (
            not _aware(start_at)
            or not _aware(end_at)
            or not _aware(known_at)
            or not start_at <= end_at <= known_at
            or end_at - start_at > _MAX_WINDOW
            or not 1 <= limit <= 512
        ):
            raise ValueError("forecast action history query is not causally bounded")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(
                "SELECT * FROM fdai_forecast_action_history_audit(%s, %s, %s, %s)",
                (subject_ref, start_at, end_at, limit + 1),
            )
            rows = await cursor.fetchall()
        selected = rows[:limit]
        return ActionAuditHistoryRead(
            rows=tuple(
                ActionAuditHistoryRow(
                    seq=int(row["seq"]),
                    recorded_at=row["recorded_at"],
                    entry=row["entry"],
                    previous_hash=str(row["previous_hash"]),
                    entry_hash=str(row["entry_hash"]),
                    state=row["state_value"],
                )
                for row in selected
            ),
            truncated=len(rows) > limit,
        )


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "PostgresForecastActionHistoryConfig",
    "PostgresForecastActionHistoryReader",
]
