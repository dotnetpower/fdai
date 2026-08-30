"""Persist Core background-task projections under Operator-owned tables."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.background_task_projection import BackgroundTaskProjectionEnvelope
from psycopg.rows import dict_row

from fdai_operator_service.postgres_dsn import normalize_psycopg_dsn

FetchAll = Callable[[str, Mapping[str, object]], Awaitable[list[dict[str, Any]]]]


class BackgroundTaskProjectionConflictError(RuntimeError):
    """A projection conflicts with the immutable Operator-owned read model."""


class BackgroundTaskProjectionStoreError(RuntimeError):
    """The Operator background-task projection store is unavailable."""


@dataclass(frozen=True, slots=True)
class StoredBackgroundTaskProjectionRecord:
    """One idempotent background-task record accepted by the Operator."""

    task_id: str
    principal_id: str
    record_kind: str
    sequence: int
    projection_id: str
    duplicate: bool


@dataclass(frozen=True, slots=True)
class PostgresBackgroundTaskProjectionConfig:
    """Configure bounded Operator projection-store connections."""

    dsn: str
    statement_timeout_ms: int = 20_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("background task projection dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("background task projection timeouts MUST be positive")


class PostgresBackgroundTaskProjectionRepository:
    """Accept snapshot and progress records only through Operator-owned tables."""

    def __init__(
        self,
        *,
        fetch_all: FetchAll | None = None,
        config: PostgresBackgroundTaskProjectionConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (fetch_all is None) == (config is None):
            raise ValueError(
                "background task projection repository requires one PostgreSQL binding"
            )
        self._injected_fetch_all = fetch_all
        self._config = config
        self._clock = clock or _utc_now

    async def project_background_task_projection(
        self,
        record: BackgroundTaskProjectionEnvelope,
    ) -> StoredBackgroundTaskProjectionRecord:
        """Project one validated transport record into the Operator read model."""

        if record.retention_until <= self._clock():
            return StoredBackgroundTaskProjectionRecord(
                task_id=record.task_id,
                principal_id=record.owner_principal_id,
                record_kind=record.record_kind,
                sequence=_record_sequence(record),
                projection_id=record.projection_id,
                duplicate=True,
            )
        if record.record_kind == "snapshot":
            return await self._project_snapshot(record)
        return await self._project_progress(record)

    async def purge_expired_background_task_projections(
        self,
        *,
        now: datetime,
        limit: int = 200,
    ) -> int:
        """Delete expired task projections and their progress history in bounded batches."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("background task retention time MUST be timezone-aware")
        if not 1 <= limit <= 500:
            raise ValueError("background task retention limit MUST be between 1 and 500")
        deleted_projection = await self._fetch_all(
            """
            WITH expired AS (
                SELECT task_id
                  FROM operator_background_task_projection
                 WHERE retention_until <= %(now)s
                 ORDER BY retention_until, task_id
                 FOR UPDATE SKIP LOCKED
                 LIMIT %(limit)s
            ), deleted_progress AS (
                DELETE FROM operator_background_task_progress AS progress
                 USING expired
                 WHERE progress.task_id = expired.task_id
                 RETURNING progress.task_id
            ), deleted_projection AS (
                DELETE FROM operator_background_task_projection AS projection
                 USING expired
                 WHERE projection.task_id = expired.task_id
                 RETURNING projection.task_id
            )
            SELECT task_id FROM deleted_projection
            """,
            {"now": now, "limit": limit},
        )
        deleted_orphan_progress = await self._fetch_all(
            """
            WITH expired AS (
                SELECT task_id, progress_sequence
                  FROM operator_background_task_progress AS progress
                 WHERE progress.retention_until <= %(now)s
                   AND NOT EXISTS (
                       SELECT 1
                         FROM operator_background_task_projection AS projection
                        WHERE projection.task_id = progress.task_id
                   )
                 ORDER BY progress.retention_until, progress.task_id, progress.progress_sequence
                 FOR UPDATE SKIP LOCKED
                 LIMIT %(limit)s
            )
            DELETE FROM operator_background_task_progress AS progress
             USING expired
             WHERE progress.task_id = expired.task_id
               AND progress.progress_sequence = expired.progress_sequence
            RETURNING progress.task_id
            """,
            {"now": now, "limit": limit},
        )
        return len(deleted_projection) + len(deleted_orphan_progress)

    async def _project_snapshot(
        self,
        record: BackgroundTaskProjectionEnvelope,
    ) -> StoredBackgroundTaskProjectionRecord:
        rows = await self._fetch_all(
            """
            WITH existing AS (
                SELECT task_id,
                       principal_id,
                       projection_id,
                       projection_digest,
                       projection_sequence
                  FROM operator_background_task_projection
                 WHERE task_id = %(task_id)s
            ), upserted AS (
                INSERT INTO operator_background_task_projection (
                    task_id,
                    principal_id,
                    attempt_id,
                    task_kind,
                    status,
                    revision,
                    projection_sequence,
                    created_at,
                    updated_at,
                    retention_until,
                    lease_expires_at,
                    budget,
                    usage,
                    request_summary,
                    request_truncated,
                    accountable_agent,
                    result_summary,
                    result_truncated,
                    evidence_refs,
                    evidence_truncated,
                    terminal_reason,
                    started_at,
                    finished_at,
                    completion_state,
                    completion_attempt_count,
                    progress_watermark,
                    recorded_at,
                    projection_id,
                    projection_digest
                ) VALUES (
                    %(task_id)s,
                    %(principal_id)s,
                    %(attempt_id)s,
                    %(task_kind)s,
                    %(status)s,
                    %(revision)s,
                    %(projection_sequence)s,
                    %(created_at)s,
                    %(updated_at)s,
                    %(retention_until)s,
                    %(lease_expires_at)s,
                    %(budget)s::jsonb,
                    %(usage)s::jsonb,
                    %(request_summary)s,
                    %(request_truncated)s,
                    %(accountable_agent)s,
                    %(result_summary)s,
                    %(result_truncated)s,
                    %(evidence_refs)s::jsonb,
                    %(evidence_truncated)s,
                    %(terminal_reason)s,
                    %(started_at)s,
                    %(finished_at)s,
                    %(completion_state)s,
                    %(completion_attempt_count)s,
                    %(progress_watermark)s,
                    %(recorded_at)s,
                    %(projection_id)s,
                    %(projection_digest)s
                )
                ON CONFLICT (task_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        attempt_id = EXCLUDED.attempt_id,
                        task_kind = EXCLUDED.task_kind,
                        status = EXCLUDED.status,
                        revision = EXCLUDED.revision,
                        projection_sequence = EXCLUDED.projection_sequence,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at,
                        retention_until = EXCLUDED.retention_until,
                        lease_expires_at = EXCLUDED.lease_expires_at,
                        budget = EXCLUDED.budget,
                        usage = EXCLUDED.usage,
                        request_summary = EXCLUDED.request_summary,
                        request_truncated = EXCLUDED.request_truncated,
                        accountable_agent = EXCLUDED.accountable_agent,
                        result_summary = EXCLUDED.result_summary,
                        result_truncated = EXCLUDED.result_truncated,
                        evidence_refs = EXCLUDED.evidence_refs,
                        evidence_truncated = EXCLUDED.evidence_truncated,
                        terminal_reason = EXCLUDED.terminal_reason,
                        started_at = EXCLUDED.started_at,
                        finished_at = EXCLUDED.finished_at,
                        completion_state = EXCLUDED.completion_state,
                        completion_attempt_count = EXCLUDED.completion_attempt_count,
                        progress_watermark = EXCLUDED.progress_watermark,
                        recorded_at = EXCLUDED.recorded_at,
                        projection_id = EXCLUDED.projection_id,
                        projection_digest = EXCLUDED.projection_digest
                  WHERE operator_background_task_projection.principal_id = EXCLUDED.principal_id
                    AND operator_background_task_projection.projection_sequence
                        < EXCLUDED.projection_sequence
                RETURNING task_id,
                          principal_id,
                          projection_id,
                          projection_digest,
                          projection_sequence,
                          TRUE AS applied
            )
            SELECT task_id,
                   principal_id,
                   projection_id,
                   projection_digest,
                   projection_sequence,
                   applied
              FROM upserted
            UNION ALL
            SELECT task_id,
                   principal_id,
                   projection_id,
                   projection_digest,
                   projection_sequence,
                   FALSE AS applied
              FROM existing
             WHERE NOT EXISTS (SELECT 1 FROM upserted)
             LIMIT 1
            """,
            _snapshot_params(record),
        )
        return _stored_snapshot(record, rows)

    async def _project_progress(
        self,
        record: BackgroundTaskProjectionEnvelope,
    ) -> StoredBackgroundTaskProjectionRecord:
        rows = await self._fetch_all(
            """
            WITH inserted AS (
                INSERT INTO operator_background_task_progress (
                    task_id,
                    progress_sequence,
                    progress_order,
                    principal_id,
                    attempt_id,
                    progress_id,
                    progress_digest,
                    progress_kind,
                    progress_message,
                    progress_at,
                    usage,
                    retention_until,
                    recorded_at
                ) VALUES (
                    %(task_id)s,
                    %(progress_sequence)s,
                    %(progress_order)s,
                    %(principal_id)s,
                    %(attempt_id)s,
                    %(projection_id)s,
                    %(projection_digest)s,
                    %(progress_kind)s,
                    %(progress_message)s,
                    %(progress_at)s,
                    %(usage)s::jsonb,
                    %(retention_until)s,
                    %(recorded_at)s
                )
                ON CONFLICT (task_id, progress_sequence) DO NOTHING
                RETURNING task_id,
                          principal_id,
                          progress_id,
                          progress_digest,
                          progress_order,
                          progress_sequence,
                          TRUE AS inserted
            )
            SELECT task_id,
                   principal_id,
                   progress_id,
                   progress_digest,
                   progress_order,
                   progress_sequence,
                   inserted
              FROM inserted
            UNION ALL
            SELECT task_id,
                   principal_id,
                   progress_id,
                   progress_digest,
                   progress_order,
                   progress_sequence,
                   FALSE AS inserted
              FROM operator_background_task_progress
             WHERE task_id = %(task_id)s
               AND progress_sequence = %(progress_sequence)s
               AND NOT EXISTS (SELECT 1 FROM inserted)
             LIMIT 1
            """,
            _progress_params(record),
        )
        return _stored_progress(record, rows)

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        try:
            if self._injected_fetch_all is not None:
                return await self._injected_fetch_all(statement, parameters)
            config = self._config
            if config is None:  # pragma: no cover - constructor invariant
                raise RuntimeError("background task projection PostgreSQL binding is unavailable")
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
                rows = await cursor.fetchall()
        except psycopg.Error as exc:  # pragma: no cover - exercised by integration tests
            raise BackgroundTaskProjectionStoreError(
                "background task projection store is unavailable"
            ) from exc
        return [dict(row) for row in rows]


def _snapshot_params(record: BackgroundTaskProjectionEnvelope) -> dict[str, object]:
    budget = record.budget
    if budget is None:  # pragma: no cover - validated before repository entry
        raise BackgroundTaskProjectionStoreError("background task snapshot budget is missing")
    return {
        "task_id": record.task_id,
        "principal_id": record.owner_principal_id,
        "attempt_id": record.attempt_id,
        "task_kind": record.task_kind,
        "status": record.status,
        "revision": record.revision,
        "projection_sequence": record.projection_sequence,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "retention_until": record.retention_until,
        "lease_expires_at": record.lease_expires_at,
        "budget": json.dumps(budget.model_dump(mode="json"), separators=(",", ":")),
        "usage": json.dumps(record.usage.model_dump(mode="json"), separators=(",", ":")),
        "request_summary": record.request_summary,
        "request_truncated": record.request_truncated,
        "accountable_agent": record.accountable_agent,
        "result_summary": record.result_summary,
        "result_truncated": record.result_truncated,
        "evidence_refs": json.dumps(list(record.evidence_refs), separators=(",", ":")),
        "evidence_truncated": record.evidence_truncated,
        "terminal_reason": record.terminal_reason,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "completion_state": record.completion_state,
        "completion_attempt_count": record.completion_attempt_count,
        "progress_watermark": record.progress_watermark,
        "recorded_at": record.recorded_at,
        "projection_id": record.projection_id,
        "projection_digest": record.projection_digest,
    }


def _progress_params(record: BackgroundTaskProjectionEnvelope) -> dict[str, object]:
    return {
        "task_id": record.task_id,
        "progress_sequence": record.progress_sequence,
        "progress_order": record.progress_order,
        "principal_id": record.owner_principal_id,
        "attempt_id": record.attempt_id,
        "projection_id": record.projection_id,
        "projection_digest": record.projection_digest,
        "progress_kind": record.progress_kind,
        "progress_message": record.progress_message,
        "progress_at": record.progress_at,
        "usage": json.dumps(record.usage.model_dump(mode="json"), separators=(",", ":")),
        "retention_until": record.retention_until,
        "recorded_at": record.recorded_at,
    }


def _stored_snapshot(
    record: BackgroundTaskProjectionEnvelope,
    rows: list[dict[str, Any]],
) -> StoredBackgroundTaskProjectionRecord:
    if not rows:
        raise BackgroundTaskProjectionConflictError(
            "background task snapshot has no matching durable projection row"
        )
    row = rows[0]
    stored_principal = row.get("principal_id")
    stored_id = row.get("projection_id")
    stored_digest = row.get("projection_digest")
    stored_sequence = row.get("projection_sequence")
    if stored_principal != record.owner_principal_id:
        raise BackgroundTaskProjectionConflictError(
            "background task snapshot owner conflicts with immutable durable state"
        )
    if not isinstance(stored_id, str) or not isinstance(stored_digest, str):
        raise BackgroundTaskProjectionStoreError("background task snapshot identity is malformed")
    if not isinstance(stored_sequence, int) or isinstance(stored_sequence, bool):
        raise BackgroundTaskProjectionStoreError("background task snapshot sequence is malformed")
    if stored_sequence == record.projection_sequence:
        if stored_id != record.projection_id or stored_digest != record.projection_digest:
            raise BackgroundTaskProjectionConflictError(
                "background task snapshot identity conflicts with immutable durable state"
            )
        duplicate = row.get("applied") is not True
    elif stored_sequence > (record.projection_sequence or 0):
        duplicate = True
    else:
        if row.get("applied") is not True:
            raise BackgroundTaskProjectionConflictError(
                "background task snapshot update lost ordering ownership"
            )
        duplicate = False
    return StoredBackgroundTaskProjectionRecord(
        task_id=record.task_id,
        principal_id=record.owner_principal_id,
        record_kind="snapshot",
        sequence=stored_sequence,
        projection_id=stored_id,
        duplicate=duplicate,
    )


def _stored_progress(
    record: BackgroundTaskProjectionEnvelope,
    rows: list[dict[str, Any]],
) -> StoredBackgroundTaskProjectionRecord:
    if not rows:
        raise BackgroundTaskProjectionConflictError(
            "background task progress has no matching durable projection row"
        )
    row = rows[0]
    stored_principal = row.get("principal_id")
    stored_id = row.get("progress_id")
    stored_digest = row.get("progress_digest")
    stored_order = row.get("progress_order")
    stored_sequence = row.get("progress_sequence")
    if stored_principal != record.owner_principal_id:
        raise BackgroundTaskProjectionConflictError(
            "background task progress owner conflicts with immutable durable state"
        )
    if not isinstance(stored_id, str) or not isinstance(stored_digest, str):
        raise BackgroundTaskProjectionStoreError("background task progress identity is malformed")
    if (
        not isinstance(stored_order, int)
        or isinstance(stored_order, bool)
        or stored_id != record.projection_id
        or stored_digest != record.projection_digest
        or stored_order != record.progress_order
    ):
        raise BackgroundTaskProjectionConflictError(
            "background task progress identity conflicts with immutable durable state"
        )
    if not isinstance(stored_sequence, int) or isinstance(stored_sequence, bool):
        raise BackgroundTaskProjectionStoreError("background task progress sequence is malformed")
    return StoredBackgroundTaskProjectionRecord(
        task_id=record.task_id,
        principal_id=record.owner_principal_id,
        record_kind="progress",
        sequence=stored_sequence,
        projection_id=record.projection_id,
        duplicate=row.get("inserted") is not True,
    )


def _record_sequence(record: BackgroundTaskProjectionEnvelope) -> int:
    sequence = (
        record.projection_sequence if record.record_kind == "snapshot" else record.progress_sequence
    )
    if sequence is None:  # pragma: no cover - validated before persistence entry
        raise BackgroundTaskProjectionStoreError("background task projection sequence is missing")
    return sequence


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "BackgroundTaskProjectionConflictError",
    "BackgroundTaskProjectionStoreError",
    "PostgresBackgroundTaskProjectionConfig",
    "PostgresBackgroundTaskProjectionRepository",
    "StoredBackgroundTaskProjectionRecord",
]
