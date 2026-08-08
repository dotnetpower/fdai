"""PostgreSQL CAS ledger for execution backend submissions and attempts."""

# ruff: noqa: S608 - interpolated identifiers are fixed module constants; values are bound.

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.execution_backend import (
    ExecutionAttempt,
    ExecutionAttemptOperation,
    ExecutionCleanupState,
    ExecutionLedgerRecord,
    ExecutionOwnerTrace,
    ExecutionStatus,
)

_COLUMNS: Final = (
    "idempotency_key, workload_id, artifact_digest, profile_id, profile_version, "
    "backend_kind, owner_trace, stop_condition, audit_ref, scope_ref, region, status, "
    "submission_ref, receipt_ref, detail, cancel_requested, cleanup_state, created_at, "
    "updated_at, retention_until, revision"
)


@dataclass(frozen=True, slots=True)
class PostgresExecutionSubmissionLedgerConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("execution submission ledger dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("execution submission ledger timeouts MUST be positive")


class PostgresExecutionSubmissionLedger:
    """Durable idempotency, reconciliation, cancellation, and cleanup state."""

    def __init__(self, *, config: PostgresExecutionSubmissionLedgerConfig) -> None:
        self._config = config

    async def create(self, record: ExecutionLedgerRecord) -> ExecutionLedgerRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO execution_submission ({_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (idempotency_key) DO NOTHING "
                f"RETURNING {_COLUMNS}",  # noqa: S608 - fixed column constant
                _record_params(record),
            )
            row = await cursor.fetchone()
            if row is None:
                existing = await connection.execute(
                    f"SELECT {_COLUMNS} FROM execution_submission "  # noqa: S608
                    "WHERE idempotency_key = %s",
                    (record.idempotency_key,),
                )
                row = await existing.fetchone()
        if row is None:
            raise RuntimeError("execution submission insert returned no row")
        return _record(row)

    async def get(self, idempotency_key: str) -> ExecutionLedgerRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM execution_submission "  # noqa: S608
                "WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            row = await cursor.fetchone()
        return _record(row) if row is not None else None

    async def update(
        self,
        record: ExecutionLedgerRecord,
        *,
        expected_revision: int,
    ) -> ExecutionLedgerRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE execution_submission SET status = %s, submission_ref = %s, "
                "receipt_ref = %s, detail = %s, cancel_requested = %s, cleanup_state = %s, "
                "updated_at = %s, retention_until = %s, revision = revision + 1 "
                "WHERE idempotency_key = %s AND revision = %s "
                f"RETURNING {_COLUMNS}",  # noqa: S608 - fixed column constant
                (
                    record.status.value,
                    record.submission_ref,
                    record.receipt_ref,
                    record.detail,
                    record.cancel_requested,
                    record.cleanup_state.value,
                    record.updated_at,
                    record.retention_until,
                    record.idempotency_key,
                    expected_revision,
                ),
            )
            row = await cursor.fetchone()
        if row is None:
            current = await self.get(record.idempotency_key)
            if current is None:
                raise LookupError("execution ledger record disappeared")
            raise RuntimeError("execution ledger revision conflict")
        return _record(row)

    async def append_attempt(self, attempt: ExecutionAttempt) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await connection.execute(
                "INSERT INTO execution_submission_attempt "
                "(idempotency_key, sequence, operation, status, detail, recorded_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (idempotency_key, sequence) DO NOTHING",
                (
                    attempt.idempotency_key,
                    attempt.sequence,
                    attempt.operation.value,
                    attempt.status.value,
                    attempt.detail,
                    attempt.recorded_at,
                ),
            )

    async def attempts(self, idempotency_key: str) -> tuple[ExecutionAttempt, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT idempotency_key, sequence, operation, status, detail, recorded_at "
                "FROM execution_submission_attempt WHERE idempotency_key = %s "
                "ORDER BY sequence",
                (idempotency_key,),
            )
            rows = await cursor.fetchall()
        return tuple(_attempt(row) for row in rows)

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


def _record_params(record: ExecutionLedgerRecord) -> tuple[object, ...]:
    owner = {
        "event_ref": record.owner_trace.event_ref,
        "action_ref": record.owner_trace.action_ref,
        "correlation_ref": record.owner_trace.correlation_ref,
        "executor_role": record.owner_trace.executor_role,
    }
    return (
        record.idempotency_key,
        record.workload_id,
        record.artifact_digest,
        record.profile_id,
        record.profile_version,
        record.backend_kind,
        json.dumps(owner, separators=(",", ":")),
        record.stop_condition,
        record.audit_ref,
        record.scope_ref,
        record.region,
        record.status.value,
        record.submission_ref,
        record.receipt_ref,
        record.detail,
        record.cancel_requested,
        record.cleanup_state.value,
        record.created_at,
        record.updated_at,
        record.retention_until,
        record.revision,
    )


def _record(row: dict[str, Any]) -> ExecutionLedgerRecord:
    owner = _mapping(row["owner_trace"])
    return ExecutionLedgerRecord(
        idempotency_key=str(row["idempotency_key"]),
        workload_id=str(row["workload_id"]),
        artifact_digest=str(row["artifact_digest"]),
        profile_id=str(row["profile_id"]),
        profile_version=str(row["profile_version"]),
        backend_kind=str(row["backend_kind"]),
        owner_trace=ExecutionOwnerTrace(
            event_ref=str(owner["event_ref"]),
            action_ref=str(owner["action_ref"]),
            correlation_ref=str(owner["correlation_ref"]),
            executor_role=str(owner["executor_role"]),
        ),
        stop_condition=str(row["stop_condition"]),
        audit_ref=str(row["audit_ref"]),
        scope_ref=str(row["scope_ref"]),
        region=str(row["region"]),
        status=ExecutionStatus(str(row["status"])),
        submission_ref=(str(row["submission_ref"]) if row["submission_ref"] is not None else None),
        receipt_ref=str(row["receipt_ref"]) if row["receipt_ref"] is not None else None,
        detail=str(row["detail"]),
        cancel_requested=bool(row["cancel_requested"]),
        cleanup_state=ExecutionCleanupState(str(row["cleanup_state"])),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        retention_until=row["retention_until"],
        revision=int(row["revision"]),
    )


def _attempt(row: dict[str, Any]) -> ExecutionAttempt:
    return ExecutionAttempt(
        idempotency_key=str(row["idempotency_key"]),
        sequence=int(row["sequence"]),
        operation=ExecutionAttemptOperation(str(row["operation"])),
        status=ExecutionStatus(str(row["status"])),
        detail=str(row["detail"]),
        recorded_at=row["recorded_at"],
    )


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise RuntimeError("execution ledger JSON column is not an object")


__all__ = [
    "PostgresExecutionSubmissionLedger",
    "PostgresExecutionSubmissionLedgerConfig",
]
