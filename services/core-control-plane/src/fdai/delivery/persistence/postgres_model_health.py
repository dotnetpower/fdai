"""Append-only PostgreSQL model health transition telemetry."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.azure.llm.latency_routed_cross_check import (
    ModelFailureKind,
    ModelHealthTransition,
)


@dataclass(frozen=True, slots=True)
class PostgresModelHealthTransitionSinkConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresModelHealthTransitionSinkConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresModelHealthTransitionSinkConfig timeouts MUST be positive")


class PostgresModelHealthTransitionSink:
    """Persist redacted failure/recovery transitions for every model role."""

    def __init__(self, *, config: PostgresModelHealthTransitionSinkConfig) -> None:
        self._config = config

    async def append(self, transition: ModelHealthTransition) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            await connection.execute(
                """
                INSERT INTO model_health_transition (
                    model_role, deployment, status, failure_kind, failure_count,
                    cooldown_seconds, recorded_at, reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    transition.model_role,
                    transition.deployment,
                    transition.status,
                    transition.failure_kind.value if transition.failure_kind is not None else None,
                    transition.failure_count,
                    transition.cooldown_seconds,
                    transition.recorded_at,
                    transition.reason,
                ),
            )

    async def list_for(
        self,
        *,
        model_role: str,
        deployment: str,
        limit: int = 100,
    ) -> Sequence[ModelHealthTransition]:
        if not 1 <= limit <= 1000:
            raise ValueError("model health transition limit MUST be in [1, 1000]")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                SELECT model_role, deployment, status, failure_kind, failure_count,
                      cooldown_seconds, recorded_at, reason
                  FROM model_health_transition
                 WHERE model_role = %s AND deployment = %s
                 ORDER BY transition_id DESC
                 LIMIT %s
                """,
                (model_role, deployment, limit),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_transition(row) for row in rows)

    async def list_recent(self, *, limit: int = 200) -> Sequence[ModelHealthTransition]:
        if not 1 <= limit <= 1000:
            raise ValueError("model health transition limit MUST be in [1, 1000]")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                SELECT model_role, deployment, status, failure_kind, failure_count,
                       cooldown_seconds, recorded_at, reason
                  FROM model_health_transition
                 ORDER BY transition_id DESC
                 LIMIT %s
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_transition(row) for row in rows)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _row_to_transition(row: dict[str, Any]) -> ModelHealthTransition:
    failure_kind = row["failure_kind"]
    return ModelHealthTransition(
        model_role=str(row["model_role"]),
        deployment=str(row["deployment"]),
        status=str(row["status"]),
        failure_kind=(ModelFailureKind(str(failure_kind)) if failure_kind is not None else None),
        failure_count=int(row["failure_count"]),
        cooldown_seconds=int(row["cooldown_seconds"]),
        recorded_at=row["recorded_at"],
        reason=str(row["reason"]),
    )


__all__ = [
    "PostgresModelHealthTransitionSink",
    "PostgresModelHealthTransitionSinkConfig",
]
