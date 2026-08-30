"""Owner-scoped durable replay for interactive read investigations."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai_operator_service.families.operations.contracts import (
    ProjectionUnavailableError,
    ReplayBatch,
    ReplayEvent,
    ReplayQuery,
)
from fdai_operator_service.postgres_dsn import normalize_psycopg_dsn


@dataclass(frozen=True, slots=True)
class PostgresReadInvestigationReplayConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("read investigation replay dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("read investigation replay timeouts MUST be positive")


class PostgresReadInvestigationReplayStore:
    """Merge Core progress and Operator terminal rows behind an owner predicate."""

    def __init__(
        self,
        *,
        config: PostgresReadInvestigationReplayConfig | None = None,
        fetch_all: FetchAll | None = None,
    ) -> None:
        if (config is None) == (fetch_all is None):
            raise ValueError("replay store requires exactly one PostgreSQL binding")
        self._config = config
        self._injected_fetch_all = fetch_all

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        """Return progress 1-256 and terminal 1001+ in one stable cursor space."""

        if not query.stream.startswith("read-investigation:"):
            raise ValueError("read investigation replay requires its canonical stream")
        request_id = query.stream.removeprefix("read-investigation:")
        after_sequence = query.after_sequence or 0
        rows = await self._fetch_all(
            """
            WITH selected_run AS (
                SELECT task_id, mode, state
                  FROM read_investigation_run
                 WHERE owner_principal_id = %(principal_id)s
                   AND request ->> 'conversation_ref' = %(request_id)s
                 LIMIT 1
            ), replay AS (
                SELECT progress.sequence AS sequence,
                       progress.kind AS event,
                       jsonb_build_object(
                           'task_id', progress.task_id,
                           'mode', selected_run.mode,
                           'state', selected_run.state,
                           'kind', progress.kind,
                           'recorded_at', progress.recorded_at
                       ) AS data
                  FROM read_investigation_run_progress AS progress
                  JOIN selected_run ON selected_run.task_id = progress.task_id
                 WHERE progress.owner_principal_id = %(principal_id)s
                UNION ALL
                SELECT 1000 + completion.sequence AS sequence,
                       completion.event AS event,
                       completion.data AS data
                  FROM operator_read_investigation_completion AS completion
                 WHERE completion.stream = %(stream)s
                   AND completion.principal_id = %(principal_id)s
            )
            SELECT sequence, event, data
              FROM replay
             WHERE sequence > %(after_sequence)s
             ORDER BY sequence
             LIMIT %(limit)s
            """,
            {
                "principal_id": query.principal_id,
                "request_id": request_id,
                "stream": query.stream,
                "after_sequence": after_sequence,
                "limit": query.limit,
            },
        )
        events = tuple(
            ReplayEvent(
                sequence=int(row["sequence"]),
                event=str(row["event"]),
                data=_object(row["data"]),
            )
            for row in rows
        )
        return ReplayBatch(
            events=events,
            watermark=events[-1].sequence if events else after_sequence,
        )

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        if self._injected_fetch_all is not None:
            return await self._injected_fetch_all(statement, parameters)
        config = self._config
        if config is None:  # pragma: no cover - constructor invariant
            raise ProjectionUnavailableError
        try:
            async with await psycopg.AsyncConnection.connect(
                normalize_psycopg_dsn(config.dsn),
                row_factory=dict_row,
                connect_timeout=config.connect_timeout_s,
            ) as connection:
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(config.statement_timeout_ms),),
                )
                cursor = await connection.execute(statement, parameters)
                return list(await cursor.fetchall())
        except psycopg.Error as exc:
            raise ProjectionUnavailableError from exc


def _object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProjectionUnavailableError
    return dict(value)


FetchAll = Callable[
    [str, Mapping[str, object]],
    Awaitable[list[dict[str, Any]]],
]


__all__ = [
    "PostgresReadInvestigationReplayConfig",
    "PostgresReadInvestigationReplayStore",
]
