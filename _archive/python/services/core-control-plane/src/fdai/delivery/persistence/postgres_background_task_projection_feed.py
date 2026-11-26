"""Durable outbox for Core background-task projection transport."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import psycopg
from fdai_core_service.background_task_projection import (
    BackgroundTaskProjectionOutbox,
    ClaimedBackgroundTaskProjection,
)
from fdai_service_contracts.background_task_projection import (
    BackgroundTaskProjectionBudget,
    BackgroundTaskProjectionEnvelope,
    BackgroundTaskProjectionUsage,
    CompletionState,
    TaskStatus,
    build_background_task_progress,
    build_background_task_snapshot,
)
from psycopg.rows import dict_row

from fdai.core.background_task import BackgroundTaskAttempt, BackgroundTaskProgress

FetchAll = Callable[[str, Mapping[str, object]], Awaitable[list[dict[str, Any]]]]
Connection = psycopg.AsyncConnection[dict[str, Any]]

_SNAPSHOT_QUERY = """
SELECT attempt.task_id,
       attempt.owner_principal_id,
       attempt.attempt_id,
       attempt.task ->> 'kind' AS task_kind,
       attempt.status,
       attempt.revision,
       attempt.created_at,
       attempt.updated_at,
       attempt.retention_until,
       attempt.lease_expires_at,
       attempt.task -> 'budget' AS budget,
       attempt.usage,
       LEFT(attempt.task ->> 'prompt', 500) AS request_summary,
       LENGTH(attempt.task ->> 'prompt') > 500 AS request_truncated,
       attempt.task ->> 'accountable_agent' AS accountable_agent,
       LEFT(attempt.result ->> 'summary', 2000) AS result_summary,
       COALESCE(LENGTH(attempt.result ->> 'summary') > 2000, FALSE) AS result_truncated,
       ARRAY(
           SELECT evidence.value
             FROM jsonb_array_elements_text(
                 COALESCE(attempt.result -> 'evidence_refs', '[]'::jsonb)
             ) WITH ORDINALITY AS evidence(value, ordinal)
            ORDER BY evidence.ordinal
            LIMIT 16
       ) AS evidence_refs,
       COALESCE(jsonb_array_length(attempt.result -> 'evidence_refs'), 0) > 16
           AS evidence_truncated,
       attempt.result ->> 'terminal_reason' AS terminal_reason,
       (attempt.result ->> 'started_at')::timestamptz AS started_at,
       (attempt.result ->> 'finished_at')::timestamptz AS finished_at,
       completion.state AS completion_state,
       completion.attempt_count AS completion_attempt_count,
       completion.progress_watermark,
       GREATEST(
           attempt.updated_at,
           COALESCE(completion.updated_at, attempt.updated_at)
       ) AS recorded_at,
       (
           (attempt.revision * 100)
           + (COALESCE(completion.attempt_count, 0) * 10)
           + CASE completion.state
               WHEN 'pending' THEN 1
               WHEN 'sending' THEN 2
               WHEN 'failed' THEN 3
               WHEN 'delivered' THEN 4
               WHEN 'abandoned' THEN 5
               ELSE 0
             END
       ) AS projection_sequence
  FROM background_task_attempt AS attempt
  LEFT JOIN background_task_completion AS completion
    ON completion.attempt_id = attempt.attempt_id
 WHERE attempt.retention_until > CURRENT_TIMESTAMP
"""

_PROGRESS_QUERY = """
SELECT attempt.task_id,
       attempt.owner_principal_id,
       progress.attempt_id,
       progress.sequence AS progress_sequence,
       progress.kind AS progress_kind,
       progress.message AS progress_message,
       progress.at AS progress_at,
       progress.append_order AS progress_order,
       progress.at AS recorded_at,
       attempt.retention_until,
       progress.usage
  FROM background_task_progress AS progress
  JOIN background_task_attempt AS attempt
    ON attempt.attempt_id = progress.attempt_id
 WHERE attempt.retention_until > CURRENT_TIMESTAMP
 ORDER BY progress.append_order ASC
"""


@dataclass(frozen=True, slots=True)
class PostgresBackgroundTaskProjectionFeedConfig:
    """Configure bounded Core-owned projection outbox access."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("background task projection outbox dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("background task projection outbox timeouts MUST be positive")


class PostgresBackgroundTaskProjectionFeed(BackgroundTaskProjectionOutbox):
    """Claim durable background-task projection rows and replay missing history."""

    def __init__(
        self,
        *,
        fetch_all: FetchAll | None = None,
        config: PostgresBackgroundTaskProjectionFeedConfig | None = None,
    ) -> None:
        if (fetch_all is None) == (config is None):
            raise ValueError("projection outbox requires exactly one PostgreSQL binding")
        self._injected_fetch_all = fetch_all
        self._config = config

    async def verify_schema(self) -> None:
        """Fail closed on schema drift and backfill missing durable projection rows."""

        if self._injected_fetch_all is not None:
            await self._fetch_all(
                "SELECT payload, progress_order, progress_watermark "
                "FROM background_task_projection_outbox LIMIT 0",
                {},
            )
            await self._fetch_all(
                "SELECT updated_at, progress_watermark FROM background_task_completion LIMIT 0",
                {},
            )
            await self._fetch_all(
                "SELECT append_order FROM background_task_progress LIMIT 0",
                {},
            )
            return
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await connection.execute(
                "SELECT payload, progress_order, progress_watermark "
                "FROM background_task_projection_outbox LIMIT 0"
            )
            await connection.execute(
                "SELECT updated_at, progress_watermark FROM background_task_completion LIMIT 0"
            )
            await connection.execute("SELECT append_order FROM background_task_progress LIMIT 0")
            await _backfill_current_rows(connection)

    async def claim_batch(
        self,
        *,
        worker_id: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
    ) -> tuple[ClaimedBackgroundTaskProjection, ...]:
        """Lease one bounded batch of unpublished projection rows."""

        _lease_input(worker_id, lease_token, now, lease_seconds)
        _limit(limit, 500)
        rows = await self._fetch_all(
            """
            WITH candidate AS (
                SELECT outbox.projection_id
                  FROM background_task_projection_outbox AS outbox
                 WHERE outbox.published_at IS NULL
                   AND outbox.retention_until > %(now)s
                   AND (
                       outbox.lease_expires_at IS NULL
                       OR outbox.lease_expires_at <= %(now)s
                   )
                   AND (
                       outbox.record_kind <> 'snapshot'
                       OR outbox.progress_watermark IS NULL
                       OR NOT EXISTS (
                           SELECT 1
                             FROM background_task_projection_outbox AS progress
                            WHERE progress.attempt_id = outbox.attempt_id
                              AND progress.record_kind = 'progress'
                              AND progress.progress_order <= outbox.progress_watermark
                              AND progress.published_at IS NULL
                       )
                   )
                 ORDER BY outbox.outbox_sequence ASC
                 FOR UPDATE SKIP LOCKED
                 LIMIT %(limit)s
            )
            UPDATE background_task_projection_outbox AS outbox
               SET claim_count = outbox.claim_count + 1,
                   claimed_at = %(now)s,
                   lease_owner = %(worker_id)s,
                   lease_token = %(lease_token)s,
                   lease_expires_at = %(lease_expires_at)s,
                   last_error_code = NULL
              FROM candidate
             WHERE outbox.projection_id = candidate.projection_id
             RETURNING outbox.outbox_sequence,
                       outbox.projection_id,
                       outbox.task_id,
                       outbox.attempt_id,
                       outbox.record_kind,
                       outbox.payload
            """,
            {
                "now": now,
                "limit": limit,
                "worker_id": worker_id,
                "lease_token": lease_token,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
            },
        )
        return tuple(_claimed_record(row) for row in rows)

    async def acknowledge(
        self,
        projection_id: str,
        *,
        lease_token: str,
        published_at: datetime,
    ) -> bool:
        """Close a leased projection row after the broker accepts its payload."""

        _transition_input(projection_id, lease_token, published_at)
        rows = await self._fetch_all(
            """
            UPDATE background_task_projection_outbox
               SET published_at = %(published_at)s,
                   lease_owner = NULL,
                   lease_token = NULL,
                   lease_expires_at = NULL,
                   last_error_code = NULL
             WHERE projection_id = %(projection_id)s
               AND lease_token = %(lease_token)s
               AND published_at IS NULL
             RETURNING projection_id
            """,
            {
                "projection_id": projection_id,
                "lease_token": lease_token,
                "published_at": published_at,
            },
        )
        return bool(rows)

    async def release(
        self,
        projection_id: str,
        *,
        lease_token: str,
        released_at: datetime,
        error_code: str,
    ) -> bool:
        """Release a leased projection row so another worker can retry it."""

        _transition_input(projection_id, lease_token, released_at)
        if not error_code.strip() or len(error_code) > 256:
            raise ValueError("background task projection error_code MUST be bounded text")
        rows = await self._fetch_all(
            """
            UPDATE background_task_projection_outbox
               SET lease_owner = NULL,
                   lease_token = NULL,
                   lease_expires_at = NULL,
                   last_error_code = %(error_code)s
             WHERE projection_id = %(projection_id)s
               AND lease_token = %(lease_token)s
               AND published_at IS NULL
             RETURNING projection_id
            """,
            {
                "projection_id": projection_id,
                "lease_token": lease_token,
                "error_code": error_code,
            },
        )
        return bool(rows)

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        try:
            if self._injected_fetch_all is not None:
                return await self._injected_fetch_all(statement, parameters)
            async with await self._connect() as connection, connection.transaction():
                await self._timeout(connection)
                cursor = await connection.execute(statement, parameters)
                rows = await cursor.fetchall()
        except psycopg.Error as exc:  # pragma: no cover - exercised by integration tests
            raise RuntimeError("background task projection outbox is unavailable") from exc
        return [dict(row) for row in rows]

    async def _connect(self) -> Connection:
        config = self._config
        if config is None:  # pragma: no cover - constructor invariant
            raise RuntimeError("background task projection PostgreSQL binding is unavailable")
        return await psycopg.AsyncConnection.connect(
            config.dsn,
            row_factory=dict_row,
            connect_timeout=config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        config = self._config
        if config is None:  # pragma: no cover - constructor invariant
            raise RuntimeError("background task projection PostgreSQL binding is unavailable")
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(config.statement_timeout_ms),),
        )


async def enqueue_background_task_snapshot(
    connection: Connection,
    attempt: BackgroundTaskAttempt,
    *,
    completion: Mapping[str, object] | None = None,
) -> None:
    """Persist one replay-stable snapshot record inside the mutating transaction."""

    record = _snapshot_record(attempt, completion=completion)
    if record is None:
        return
    await _insert_projection_record(connection, record)


async def enqueue_background_task_progress(
    connection: Connection,
    attempt: BackgroundTaskAttempt,
    progress: BackgroundTaskProgress,
    *,
    progress_order: int,
) -> None:
    """Persist one replay-stable progress record inside the mutating transaction."""

    record = _progress_record(
        attempt,
        progress,
        progress_order=progress_order,
    )
    if record is None:
        return
    await _insert_projection_record(connection, record)


async def load_background_task_projection_completion(
    connection: Connection,
    attempt_id: str,
) -> dict[str, object] | None:
    """Load the projection-only completion fields for the current attempt."""

    cursor = await connection.execute(
        "SELECT state, attempt_count, updated_at, progress_watermark "
        "FROM background_task_completion WHERE attempt_id = %s",
        (attempt_id,),
    )
    row = await cursor.fetchone()
    return None if row is None else dict(row)


async def _backfill_current_rows(connection: Connection) -> None:
    snapshot_cursor = await connection.execute(_SNAPSHOT_QUERY)
    for row in await snapshot_cursor.fetchall():
        await _insert_projection_record(connection, _snapshot(dict(row)))
    progress_cursor = await connection.execute(_PROGRESS_QUERY)
    for row in await progress_cursor.fetchall():
        await _insert_projection_record(connection, _progress(dict(row)))


async def _insert_projection_record(
    connection: Connection,
    record: BackgroundTaskProjectionEnvelope,
) -> None:
    await connection.execute(
        """
        INSERT INTO background_task_projection_outbox (
            projection_id,
            task_id,
            attempt_id,
            record_kind,
            projection_sequence,
            progress_sequence,
            progress_order,
            progress_watermark,
            retention_until,
            payload
        ) VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s::jsonb
        )
        ON CONFLICT (projection_id) DO NOTHING
        """,
        (
            record.projection_id,
            record.task_id,
            record.attempt_id,
            record.record_kind,
            record.projection_sequence,
            record.progress_sequence,
            record.progress_order,
            record.progress_watermark,
            record.retention_until,
            json.dumps(record.model_dump(mode="json"), separators=(",", ":")),
        ),
    )


def _claimed_record(row: Mapping[str, object]) -> ClaimedBackgroundTaskProjection:
    outbox_sequence = _integer(row, "outbox_sequence")
    projection_id = _text(row, "projection_id")
    task_id = _text(row, "task_id")
    attempt_id = _text(row, "attempt_id")
    record_kind = _text(row, "record_kind", maximum=32)
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        raise RuntimeError("background task projection payload is malformed")
    record = BackgroundTaskProjectionEnvelope.model_validate(dict(payload))
    if (
        record.projection_id != projection_id
        or record.task_id != task_id
        or record.attempt_id != attempt_id
        or record.record_kind != record_kind
    ):
        raise RuntimeError("background task projection outbox row conflicts with its payload")
    return ClaimedBackgroundTaskProjection(
        outbox_sequence=outbox_sequence,
        projection_id=projection_id,
        task_id=task_id,
        attempt_id=attempt_id,
        record=record,
    )


def _snapshot_record(
    attempt: BackgroundTaskAttempt,
    *,
    completion: Mapping[str, object] | None,
) -> BackgroundTaskProjectionEnvelope | None:
    budget = attempt.task.budget
    result = attempt.result
    completion_state = _optional_completion_state(completion)
    completion_attempt_count = _optional_completion_attempt_count(completion)
    progress_watermark = _optional_completion_progress_watermark(completion)
    if attempt.result is not None and progress_watermark is None:
        raise RuntimeError("terminal background task projection requires a completion watermark")
    recorded_at = attempt.updated_at
    if completion is not None:
        completion_updated_at = _timestamp(completion.get("updated_at"), field="updated_at")
        recorded_at = max(recorded_at, completion_updated_at)
    if recorded_at > attempt.task.retention_until:
        return None
    return build_background_task_snapshot(
        task_id=attempt.task.task_id,
        owner_principal_id=attempt.task.owner_principal_id,
        attempt_id=attempt.attempt_id,
        task_kind="read_only_investigation",
        status=attempt.status.value,
        revision=attempt.revision,
        created_at=attempt.task.created_at,
        updated_at=attempt.updated_at,
        retention_until=attempt.task.retention_until,
        recorded_at=recorded_at,
        lease_expires_at=(attempt.lease.expires_at if attempt.lease is not None else None),
        budget=BackgroundTaskProjectionBudget(
            max_wall_seconds=budget.max_wall_seconds,
            max_tokens=budget.max_tokens,
            max_cost_microusd=budget.max_cost_microusd,
            max_tool_calls=budget.max_tool_calls,
            max_progress_events=budget.max_progress_events,
        ),
        usage=_projection_usage(attempt.usage),
        request_summary=attempt.task.prompt[:500],
        request_truncated=len(attempt.task.prompt) > 500,
        accountable_agent=_accountable_agent(attempt.task.accountable_agent),
        result_summary=(
            None if result is None or result.summary is None else result.summary[:2000]
        ),
        result_truncated=bool(
            result is not None and result.summary is not None and len(result.summary) > 2000
        ),
        evidence_refs=(() if result is None else result.evidence_refs[:16]),
        evidence_truncated=bool(result is not None and len(result.evidence_refs) > 16),
        terminal_reason=None if result is None else result.terminal_reason,
        started_at=None if result is None else result.started_at,
        finished_at=None if result is None else result.finished_at,
        completion_state=completion_state,
        completion_attempt_count=completion_attempt_count,
        progress_watermark=progress_watermark,
    )


def _progress_record(
    attempt: BackgroundTaskAttempt,
    progress: BackgroundTaskProgress,
    *,
    progress_order: int,
) -> BackgroundTaskProjectionEnvelope | None:
    if progress.at > attempt.task.retention_until:
        return None
    return build_background_task_progress(
        task_id=attempt.task.task_id,
        owner_principal_id=attempt.task.owner_principal_id,
        attempt_id=attempt.attempt_id,
        progress_sequence=progress.sequence,
        progress_order=progress_order,
        progress_kind=progress.kind,
        progress_message=progress.message,
        progress_at=progress.at,
        retention_until=attempt.task.retention_until,
        usage=_projection_usage(progress.usage),
    )


def _projection_usage(usage: object) -> BackgroundTaskProjectionUsage:
    if not all(hasattr(usage, field) for field in ("tokens", "cost_microusd", "tool_calls")):
        raise RuntimeError("background task projection usage is malformed")
    projected = cast(Any, usage)
    return BackgroundTaskProjectionUsage(
        tokens=int(projected.tokens),
        cost_microusd=int(projected.cost_microusd),
        tool_calls=int(projected.tool_calls),
    )


def _accountable_agent(value: str | None) -> Literal["Heimdall"] | None:
    if value is None:
        return None
    if value != "Heimdall":
        raise RuntimeError("background task projection accountable_agent is malformed")
    return "Heimdall"


def _optional_completion_state(completion: Mapping[str, object] | None) -> CompletionState | None:
    if completion is None:
        return None
    state = completion.get("state")
    if not isinstance(state, str):
        raise RuntimeError("background task projection completion state is malformed")
    return cast(CompletionState, state)


def _optional_completion_attempt_count(completion: Mapping[str, object] | None) -> int | None:
    if completion is None:
        return None
    return _integer(completion, "attempt_count")


def _optional_completion_progress_watermark(completion: Mapping[str, object] | None) -> int | None:
    if completion is None:
        return None
    return _integer(completion, "progress_watermark")


def _snapshot(row: Mapping[str, object]) -> BackgroundTaskProjectionEnvelope:
    return build_background_task_snapshot(
        task_id=_text(row, "task_id"),
        owner_principal_id=_text(row, "owner_principal_id"),
        attempt_id=_text(row, "attempt_id"),
        task_kind="read_only_investigation",
        status=cast(TaskStatus, _text(row, "status", maximum=32)),
        revision=_integer(row, "revision"),
        created_at=_timestamp(row.get("created_at"), field="created_at"),
        updated_at=_timestamp(row.get("updated_at"), field="updated_at"),
        retention_until=_timestamp(row.get("retention_until"), field="retention_until"),
        recorded_at=_timestamp(row.get("recorded_at"), field="recorded_at"),
        lease_expires_at=_optional_timestamp(row.get("lease_expires_at"), field="lease_expires_at"),
        budget=BackgroundTaskProjectionBudget.model_validate(_mapping(row.get("budget"))),
        usage=BackgroundTaskProjectionUsage.model_validate(_mapping(row.get("usage"))),
        request_summary=_optional_text(row, "request_summary", maximum=500),
        request_truncated=_boolean(row, "request_truncated"),
        accountable_agent=_optional_text(row, "accountable_agent", maximum=256),  # type: ignore[arg-type]
        result_summary=_optional_text(row, "result_summary", maximum=2_000),
        result_truncated=_boolean(row, "result_truncated"),
        evidence_refs=_refs(row.get("evidence_refs")),
        evidence_truncated=_boolean(row, "evidence_truncated"),
        terminal_reason=_optional_text(row, "terminal_reason", maximum=256),
        started_at=_optional_timestamp(row.get("started_at"), field="started_at"),
        finished_at=_optional_timestamp(row.get("finished_at"), field="finished_at"),
        completion_state=_optional_text(row, "completion_state", maximum=32),  # type: ignore[arg-type]
        completion_attempt_count=_optional_integer(row, "completion_attempt_count"),
        progress_watermark=_optional_integer(row, "progress_watermark"),
    )


def _progress(row: Mapping[str, object]) -> BackgroundTaskProjectionEnvelope:
    return build_background_task_progress(
        task_id=_text(row, "task_id"),
        owner_principal_id=_text(row, "owner_principal_id"),
        attempt_id=_text(row, "attempt_id"),
        progress_sequence=_integer(row, "progress_sequence"),
        progress_order=_integer(row, "progress_order"),
        progress_kind=_text(row, "progress_kind"),
        progress_message=_text(row, "progress_message", maximum=1_000),
        progress_at=_timestamp(row.get("progress_at"), field="progress_at"),
        retention_until=_timestamp(row.get("retention_until"), field="retention_until"),
        recorded_at=_timestamp(row.get("recorded_at"), field="recorded_at"),
        usage=BackgroundTaskProjectionUsage.model_validate(_mapping(row.get("usage"))),
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError("background task projection JSON column is malformed")
    return dict(value)


def _text(row: Mapping[str, object], field: str, *, maximum: int = 256) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RuntimeError(f"background task projection {field} is malformed")
    return value


def _optional_text(
    row: Mapping[str, object],
    field: str,
    *,
    maximum: int = 256,
) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    return _text(row, field, maximum=maximum)


def _integer(row: Mapping[str, object], field: str) -> int:
    value = row.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"background task projection {field} is malformed")
    return value


def _optional_integer(row: Mapping[str, object], field: str) -> int | None:
    value = row.get(field)
    if value is None:
        return None
    return _integer(row, field)


def _boolean(row: Mapping[str, object], field: str) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise RuntimeError(f"background task projection {field} is malformed")
    return value


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError(f"background task projection {field} is malformed")
    return value.astimezone(UTC)


def _optional_timestamp(value: object, *, field: str) -> datetime | None:
    if value is None:
        return None
    return _timestamp(value, field=field)


def _refs(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError("background task projection evidence_refs are malformed")
    return tuple(value)


def _lease_input(worker_id: str, lease_token: str, now: datetime, lease_seconds: int) -> None:
    if not worker_id.strip() or not lease_token.strip():
        raise ValueError("background task projection lease identifiers MUST be non-empty")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("background task projection lease time MUST be timezone-aware")
    if not 1 <= lease_seconds <= 300:
        raise ValueError("background task projection lease_seconds MUST be in [1, 300]")


def _transition_input(projection_id: str, lease_token: str, now: datetime) -> None:
    if not projection_id.strip() or not lease_token.strip():
        raise ValueError("background task projection transition identifiers MUST be non-empty")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("background task projection transition time MUST be timezone-aware")


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")


__all__ = [
    "PostgresBackgroundTaskProjectionFeed",
    "PostgresBackgroundTaskProjectionFeedConfig",
    "enqueue_background_task_progress",
    "enqueue_background_task_snapshot",
    "load_background_task_projection_completion",
]
