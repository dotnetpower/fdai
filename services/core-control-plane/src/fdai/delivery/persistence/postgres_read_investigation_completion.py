"""Durable completion outbox for interactive read investigations."""

# ruff: noqa: S608 - interpolated SQL is a module-owned constant column list.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import psycopg
from fdai_service_contracts.read_investigation import (
    ReadInvestigationCompletion,
    ReadInvestigationCompletionUsage,
    ReadInvestigationOrigin,
    build_read_investigation_completion,
)
from psycopg.rows import dict_row

from fdai.core.read_investigation.idempotency import (
    ReadInvestigationRunRecord,
    ReadInvestigationRunState,
)


class ReadInvestigationRunCompletionState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    FAILED = "failed"
    DELIVERED = "delivered"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class ReadInvestigationRunCompletionRecord:
    completion_id: str
    task_id: str
    run_attempt_count: int
    payload: ReadInvestigationCompletion
    state: ReadInvestigationRunCompletionState
    delivery_attempt_count: int
    next_attempt_at: datetime
    retention_until: datetime
    created_at: datetime
    updated_at: datetime
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PostgresReadInvestigationCompletionStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("completion store dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("completion store timeouts MUST be positive")


class PostgresReadInvestigationCompletionStore:
    """Lease and close immutable terminal payloads without rerunning reads."""

    def __init__(self, *, config: PostgresReadInvestigationCompletionStoreConfig) -> None:
        self._config = config

    async def verify_schema(self) -> None:
        """Fail startup before execution when the outbox schema is absent."""

        async with await self._connect() as connection:
            await self._timeout(connection)
            await connection.execute("SELECT 1 FROM read_investigation_run_completion LIMIT 0")

    async def claim_due(
        self,
        *,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        limit: int = 16,
    ) -> tuple[ReadInvestigationRunCompletionRecord, ...]:
        _aware(now)
        if lease_seconds < 1:
            raise ValueError("completion lease_seconds MUST be positive")
        if not 1 <= limit <= 100:
            raise ValueError("completion claim limit MUST be in [1, 100]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH candidate AS ("
                "SELECT completion_id FROM read_investigation_run_completion "
                "WHERE state = ANY(%s) AND next_attempt_at <= %s "
                "AND retention_until > %s AND delivery_attempt_count < 8 "
                "ORDER BY next_attempt_at, completion_id FOR UPDATE SKIP LOCKED LIMIT %s"
                ") UPDATE read_investigation_run_completion AS completion SET "
                "state = %s, delivery_attempt_count = delivery_attempt_count + 1, "
                "lease_token = %s, lease_expires_at = %s, updated_at = %s, "
                "failure_reason = NULL FROM candidate "
                "WHERE completion.completion_id = candidate.completion_id RETURNING "
                f"{_qualified_columns('completion')}",
                (
                    [
                        ReadInvestigationRunCompletionState.PENDING.value,
                        ReadInvestigationRunCompletionState.FAILED.value,
                    ],
                    now,
                    now,
                    limit,
                    ReadInvestigationRunCompletionState.SENDING.value,
                    lease_token,
                    now + timedelta(seconds=lease_seconds),
                    now,
                ),
            )
            rows = await cursor.fetchall()
        return tuple(_record(row) for row in rows)

    async def mark_delivered(
        self,
        *,
        completion_id: str,
        lease_token: str,
        now: datetime,
    ) -> ReadInvestigationRunCompletionRecord:
        return await self._finish(
            completion_id=completion_id,
            lease_token=lease_token,
            now=now,
            state=ReadInvestigationRunCompletionState.DELIVERED,
            next_attempt_at=now,
            failure_reason=None,
        )

    async def mark_failed(
        self,
        *,
        completion_id: str,
        lease_token: str,
        now: datetime,
        retry_seconds: int,
    ) -> ReadInvestigationRunCompletionRecord:
        if not 1 <= retry_seconds <= 3_600:
            raise ValueError("completion retry_seconds MUST be in [1, 3600]")
        current = await self.get(completion_id=completion_id)
        if current is None:
            raise LookupError("read investigation completion was not found")
        abandoned = (
            current.delivery_attempt_count >= 8
            or now + timedelta(seconds=retry_seconds) >= current.retention_until
        )
        return await self._finish(
            completion_id=completion_id,
            lease_token=lease_token,
            now=now,
            state=(
                ReadInvestigationRunCompletionState.ABANDONED
                if abandoned
                else ReadInvestigationRunCompletionState.FAILED
            ),
            next_attempt_at=(now if abandoned else now + timedelta(seconds=retry_seconds)),
            failure_reason=("delivery_attempts_exhausted" if abandoned else "delivery_failed"),
        )

    async def reconcile(self, *, now: datetime, limit: int = 100) -> int:
        _aware(now)
        if not 1 <= limit <= 1_000:
            raise ValueError("completion reconcile limit MUST be in [1, 1000]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH candidate AS ("
                "SELECT completion_id FROM read_investigation_run_completion "
                "WHERE (state = %s AND lease_expires_at <= %s) "
                "OR (state = ANY(%s) AND retention_until <= %s) "
                "ORDER BY updated_at, completion_id FOR UPDATE SKIP LOCKED LIMIT %s"
                ") UPDATE read_investigation_run_completion AS completion SET "
                "state = CASE WHEN completion.retention_until <= %s "
                "OR completion.delivery_attempt_count >= 8 THEN %s ELSE %s END, "
                "next_attempt_at = %s, lease_token = NULL, lease_expires_at = NULL, "
                "failure_reason = CASE WHEN completion.retention_until <= %s "
                "THEN %s ELSE %s END, updated_at = %s FROM candidate "
                "WHERE completion.completion_id = candidate.completion_id",
                (
                    ReadInvestigationRunCompletionState.SENDING.value,
                    now,
                    [
                        ReadInvestigationRunCompletionState.PENDING.value,
                        ReadInvestigationRunCompletionState.FAILED.value,
                        ReadInvestigationRunCompletionState.SENDING.value,
                    ],
                    now,
                    limit,
                    now,
                    ReadInvestigationRunCompletionState.ABANDONED.value,
                    ReadInvestigationRunCompletionState.FAILED.value,
                    now,
                    now,
                    "retention_expired",
                    "delivery_lease_lost",
                    now,
                ),
            )
            return cursor.rowcount

    async def get(
        self,
        *,
        completion_id: str,
    ) -> ReadInvestigationRunCompletionRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM read_investigation_run_completion "
                "WHERE completion_id = %s",
                (completion_id,),
            )
            row = await cursor.fetchone()
        return _record(row) if row is not None else None

    async def _finish(
        self,
        *,
        completion_id: str,
        lease_token: str,
        now: datetime,
        state: ReadInvestigationRunCompletionState,
        next_attempt_at: datetime,
        failure_reason: str | None,
    ) -> ReadInvestigationRunCompletionRecord:
        _aware(now)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE read_investigation_run_completion SET state = %s, "
                "next_attempt_at = %s, lease_token = NULL, lease_expires_at = NULL, "
                "failure_reason = %s, updated_at = %s WHERE completion_id = %s "
                "AND state = %s AND lease_token = %s AND lease_expires_at > %s RETURNING "
                f"{_COLUMNS}",
                (
                    state.value,
                    next_attempt_at,
                    failure_reason,
                    now,
                    completion_id,
                    ReadInvestigationRunCompletionState.SENDING.value,
                    lease_token,
                    now,
                ),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("read investigation completion lease conflict")
        return _record(row)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def completion_payload(record: ReadInvestigationRunRecord) -> ReadInvestigationCompletion:
    """Build the stable authority-free completion for one terminal run."""

    if not record.state.terminal or record.usage is None or record.terminal_at is None:
        raise ValueError("interactive completion requires a terminal run")
    request = record.request
    result = record.result
    status = {
        ReadInvestigationRunState.COMPLETED: "succeeded",
        ReadInvestigationRunState.CANCELLED: "cancelled",
        ReadInvestigationRunState.FAILED: "failed",
        ReadInvestigationRunState.EXPIRED: "unknown",
    }[record.state]
    summary = (
        f"Read investigation finished with outcome {result.outcome.value}; "
        f"evidence envelopes={len(result.evidence)}; receipts={len(result.receipts)}."
        if result is not None
        else None
    )
    started_at = result.started_at if result is not None else record.created_at
    finished_at = result.finished_at if result is not None else record.terminal_at
    return build_read_investigation_completion(
        task_id=record.task_id,
        attempt_id=f"interactive-{record.attempt_count}",
        attempt_number=record.attempt_count,
        owner_principal_id=record.owner_principal_id,
        request_idempotency_key=record.idempotency_key,
        correlation_id=request.correlation_ref,
        origin=ReadInvestigationOrigin(
            conversation_id=request.conversation_ref,
            channel_kind=request.origin_channel_kind,
            channel_id=request.origin_channel_id or request.requester_ref,
            thread_id=request.origin_thread_id,
            message_id=request.origin_message_id,
        ),
        status=status,  # type: ignore[arg-type]
        terminal_reason=(
            result.outcome.value if result is not None else record.failure_reason or "unknown"
        ),
        summary=summary,
        evidence_refs=result.evidence_refs if result is not None else (),
        usage=ReadInvestigationCompletionUsage(
            cost_microusd=(
                record.usage.measured_cost_microusd
                if record.usage.measured_cost_microusd is not None
                else record.usage.reserved_cost_microusd
            ),
            tool_calls=record.usage.tool_calls,
        ),
        started_at=started_at,
        finished_at=finished_at,
        completed_at=record.terminal_at,
        retention_until=record.retention_until,
    )


def completion_insert_values(record: ReadInvestigationRunRecord) -> tuple[object, ...]:
    """Return immutable outbox values for use inside the run terminal transaction."""

    payload = completion_payload(record)
    serialized = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return (
        payload.completion_id,
        record.task_id,
        record.attempt_count,
        serialized,
        ReadInvestigationRunCompletionState.PENDING.value,
        record.terminal_at,
        record.retention_until,
        record.terminal_at,
        record.terminal_at,
    )


def _record(row: dict[str, Any]) -> ReadInvestigationRunCompletionRecord:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return ReadInvestigationRunCompletionRecord(
        completion_id=str(row["completion_id"]),
        task_id=str(row["task_id"]),
        run_attempt_count=int(row["run_attempt_count"]),
        payload=ReadInvestigationCompletion.model_validate(payload),
        state=ReadInvestigationRunCompletionState(str(row["state"])),
        delivery_attempt_count=int(row["delivery_attempt_count"]),
        next_attempt_at=row["next_attempt_at"],
        lease_token=str(row["lease_token"]) if row["lease_token"] is not None else None,
        lease_expires_at=row["lease_expires_at"],
        failure_reason=(str(row["failure_reason"]) if row["failure_reason"] is not None else None),
        retention_until=row["retention_until"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError("completion timestamp MUST be timezone-aware")


def _qualified_columns(alias: str) -> str:
    return ", ".join(f"{alias}.{column.strip()}" for column in _COLUMNS.split(","))


_COLUMNS = (
    "completion_id, task_id, run_attempt_count, payload, state, delivery_attempt_count, "
    "next_attempt_at, lease_token, lease_expires_at, failure_reason, retention_until, "
    "created_at, updated_at"
)

__all__ = [
    "PostgresReadInvestigationCompletionStore",
    "PostgresReadInvestigationCompletionStoreConfig",
    "ReadInvestigationRunCompletionRecord",
    "ReadInvestigationRunCompletionState",
    "completion_insert_values",
    "completion_payload",
]
