"""PostgreSQL run store for read-investigation idempotency and result replay."""

# ruff: noqa: S608 - interpolated SQL identifiers are module constants; values are bound.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.read_investigation.idempotency import (
    MAX_READ_INVESTIGATION_ATTEMPTS,
    ReadInvestigationRunConflictError,
    ReadInvestigationRunMode,
    ReadInvestigationRunRecord,
    ReadInvestigationRunState,
    ReadInvestigationRunUsage,
    read_investigation_request_digest,
)
from fdai.core.read_investigation.models import ReadInvestigationRequest, ReadInvestigationResult
from fdai.delivery.persistence.postgres_read_investigation_run_serialization import (
    COLUMNS as _COLUMNS,
)
from fdai.delivery.persistence.postgres_read_investigation_run_serialization import (
    qualified_columns as _qualified_columns,
)
from fdai.delivery.persistence.postgres_read_investigation_run_serialization import (
    request_to_dict as _request_to_dict,
)
from fdai.delivery.persistence.postgres_read_investigation_run_serialization import (
    result_to_dict as _result_to_dict,
)
from fdai.delivery.persistence.postgres_read_investigation_run_serialization import (
    run_from_row as _run,
)
from fdai.delivery.persistence.postgres_read_investigation_run_serialization import (
    usage_to_dict as _usage_to_dict,
)


@dataclass(frozen=True, slots=True)
class PostgresReadInvestigationRunStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresReadInvestigationRunStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresReadInvestigationRunStoreConfig timeouts MUST be positive")


class PostgresReadInvestigationRunStore:
    """Atomic owner-scoped idempotency and replay for read investigations."""

    def __init__(self, *, config: PostgresReadInvestigationRunStoreConfig) -> None:
        self._config = config

    async def verify_schema(self) -> None:
        """Fail startup before traffic when the optional ledger migration is missing."""
        async with await self._connect() as connection:
            await self._timeout(connection)
            await connection.execute("SELECT 1 FROM read_investigation_run LIMIT 0")

    async def claim(
        self,
        *,
        owner_principal_id: str,
        request: ReadInvestigationRequest,
        mode: ReadInvestigationRunMode,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        retention_seconds: int,
    ) -> tuple[ReadInvestigationRunRecord, bool]:
        _aware("claim now", now)
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        if retention_seconds < 1:
            raise ValueError("retention_seconds MUST be >= 1")

        digest = read_investigation_request_digest(request)
        request_payload = json.dumps(
            _request_to_dict(request),
            sort_keys=True,
            separators=(",", ":"),
        )
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        retention_until = now + timedelta(seconds=retention_seconds)

        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            insert = await connection.execute(
                "INSERT INTO read_investigation_run ("
                f"{_COLUMNS}) VALUES ("
                "%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, "
                "%s::jsonb, %s::jsonb, %s, %s, %s, %s, %s) "
                "ON CONFLICT (owner_principal_id, idempotency_key) DO NOTHING "
                f"RETURNING {_COLUMNS}",
                (
                    owner_principal_id,
                    request.idempotency_key,
                    digest,
                    request_payload,
                    mode.value,
                    ReadInvestigationRunState.CLAIMED.value,
                    1,
                    1,
                    lease_owner,
                    lease_token,
                    lease_expires_at,
                    None,
                    None,
                    None,
                    now,
                    now,
                    retention_until,
                    None,
                ),
            )
            inserted = await insert.fetchone()
            if inserted is not None:
                return _run(inserted), True

            select = await connection.execute(
                f"SELECT {_COLUMNS} FROM read_investigation_run "
                "WHERE owner_principal_id = %s AND idempotency_key = %s FOR UPDATE",
                (owner_principal_id, request.idempotency_key),
            )
            row = await select.fetchone()
            if row is None:
                raise LookupError("read investigation run was not found after claim conflict")
            current = _run(row)
            if current.request_digest != digest:
                raise ReadInvestigationRunConflictError(
                    "read investigation idempotency key was reused with another request"
                )
            return current, False

    async def reclaim(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        request_digest: str,
        mode: ReadInvestigationRunMode,
        expected_revision: int,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        retention_seconds: int,
    ) -> ReadInvestigationRunRecord:
        _aware("reclaim now", now)
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        if retention_seconds < 1:
            raise ValueError("retention_seconds MUST be >= 1")
        row = await self._leased_update(
            "UPDATE read_investigation_run SET state = %s, mode = %s, revision = revision + 1, "
            "attempt_count = attempt_count + 1, updated_at = %s, "
            "retention_until = GREATEST(retention_until, %s), "
            "terminal_at = NULL, lease_owner = %s, lease_token = %s, lease_expires_at = %s, "
            "result = NULL, usage = NULL, failure_reason = NULL "
            "WHERE owner_principal_id = %s AND idempotency_key = %s AND request_digest = %s "
            "AND revision = %s AND state = ANY(%s) AND attempt_count < %s RETURNING "
            f"{_COLUMNS}",
            (
                ReadInvestigationRunState.CLAIMED.value,
                mode.value,
                now,
                now + timedelta(seconds=retention_seconds),
                lease_owner,
                lease_token,
                now + timedelta(seconds=lease_seconds),
                owner_principal_id,
                idempotency_key,
                request_digest,
                expected_revision,
                [
                    ReadInvestigationRunState.FAILED.value,
                    ReadInvestigationRunState.EXPIRED.value,
                ],
                MAX_READ_INVESTIGATION_ATTEMPTS,
            ),
            owner_principal_id,
            idempotency_key,
        )
        return _run(row)

    async def get(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
    ) -> ReadInvestigationRunRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM read_investigation_run "
                "WHERE owner_principal_id = %s AND idempotency_key = %s",
                (owner_principal_id, idempotency_key),
            )
            row = await cursor.fetchone()
        return _run(row) if row is not None else None

    async def start(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        now: datetime,
    ) -> ReadInvestigationRunRecord:
        _aware("start now", now)
        row = await self._leased_update(
            "UPDATE read_investigation_run SET state = %s, revision = revision + 1, "
            "updated_at = %s WHERE owner_principal_id = %s AND idempotency_key = %s "
            "AND revision = %s AND lease_token = %s AND lease_expires_at > %s "
            "AND state = %s RETURNING "
            f"{_COLUMNS}",
            (
                ReadInvestigationRunState.RUNNING.value,
                now,
                owner_principal_id,
                idempotency_key,
                expected_revision,
                lease_token,
                now,
                ReadInvestigationRunState.CLAIMED.value,
            ),
            owner_principal_id,
            idempotency_key,
        )
        return _run(row)

    async def renew(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        lease_ceiling_at: datetime,
    ) -> ReadInvestigationRunRecord:
        _aware("renew now", now)
        _aware("renew lease_ceiling_at", lease_ceiling_at)
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        if lease_ceiling_at < now:
            raise ValueError("lease_ceiling_at MUST be >= now")
        row = await self._leased_update(
            "UPDATE read_investigation_run SET revision = revision + 1, updated_at = %s, "
            "lease_expires_at = LEAST(%s, %s) "
            "WHERE owner_principal_id = %s AND idempotency_key = %s AND revision = %s "
            "AND lease_token = %s AND lease_expires_at > %s AND state = %s "
            "AND LEAST(%s, %s) > %s RETURNING "
            f"{_COLUMNS}",
            (
                now,
                now + timedelta(seconds=lease_seconds),
                lease_ceiling_at,
                owner_principal_id,
                idempotency_key,
                expected_revision,
                lease_token,
                now,
                ReadInvestigationRunState.RUNNING.value,
                now + timedelta(seconds=lease_seconds),
                lease_ceiling_at,
                now,
            ),
            owner_principal_id,
            idempotency_key,
        )
        return _run(row)

    async def complete(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        result: ReadInvestigationResult,
        usage: ReadInvestigationRunUsage,
        now: datetime,
    ) -> ReadInvestigationRunRecord:
        _aware("complete now", now)
        result_payload = json.dumps(_result_to_dict(result), sort_keys=True, separators=(",", ":"))
        usage_payload = json.dumps(_usage_to_dict(usage), sort_keys=True, separators=(",", ":"))
        request_digest = read_investigation_request_digest(result.request)
        row = await self._leased_update(
            "UPDATE read_investigation_run SET state = %s, revision = revision + 1, "
            "updated_at = %s, terminal_at = %s, lease_owner = NULL, lease_token = NULL, "
            "lease_expires_at = NULL, result = %s::jsonb, usage = %s::jsonb, "
            "failure_reason = NULL WHERE owner_principal_id = %s AND idempotency_key = %s "
            "AND revision = %s AND lease_token = %s AND lease_expires_at > %s "
            "AND state = ANY(%s) AND request_digest = %s RETURNING "
            f"{_COLUMNS}",
            (
                ReadInvestigationRunState.COMPLETED.value,
                now,
                now,
                result_payload,
                usage_payload,
                owner_principal_id,
                idempotency_key,
                expected_revision,
                lease_token,
                now,
                [
                    ReadInvestigationRunState.CLAIMED.value,
                    ReadInvestigationRunState.RUNNING.value,
                ],
                request_digest,
            ),
            owner_principal_id,
            idempotency_key,
        )
        return _run(row)

    async def fail(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        failure_reason: str,
        usage: ReadInvestigationRunUsage,
        now: datetime,
        state: ReadInvestigationRunState = ReadInvestigationRunState.FAILED,
    ) -> ReadInvestigationRunRecord:
        _aware("fail now", now)
        if state not in {ReadInvestigationRunState.FAILED, ReadInvestigationRunState.EXPIRED}:
            raise ValueError("run failure state MUST be failed or expired")
        usage_payload = json.dumps(_usage_to_dict(usage), sort_keys=True, separators=(",", ":"))
        row = await self._leased_update(
            "UPDATE read_investigation_run SET state = %s, revision = revision + 1, "
            "updated_at = %s, terminal_at = %s, lease_owner = NULL, lease_token = NULL, "
            "lease_expires_at = NULL, result = NULL, usage = %s::jsonb, failure_reason = %s "
            "WHERE owner_principal_id = %s AND idempotency_key = %s AND revision = %s "
            "AND lease_token = %s AND lease_expires_at > %s AND state = ANY(%s) RETURNING "
            f"{_COLUMNS}",
            (
                state.value,
                now,
                now,
                usage_payload,
                failure_reason,
                owner_principal_id,
                idempotency_key,
                expected_revision,
                lease_token,
                now,
                [
                    ReadInvestigationRunState.CLAIMED.value,
                    ReadInvestigationRunState.RUNNING.value,
                ],
            ),
            owner_principal_id,
            idempotency_key,
        )
        return _run(row)

    async def reconcile_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[ReadInvestigationRunRecord, ...]:
        _aware("reconcile now", now)
        _limit(limit, 10_000)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH candidate AS ("
                "SELECT owner_principal_id, idempotency_key "
                "FROM read_investigation_run "
                "WHERE state = ANY(%s) AND lease_expires_at <= %s "
                "ORDER BY lease_expires_at, owner_principal_id, idempotency_key "
                "FOR UPDATE SKIP LOCKED LIMIT %s"
                ") UPDATE read_investigation_run AS run SET "
                "state = %s, revision = run.revision + 1, updated_at = %s, terminal_at = %s, "
                "lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, "
                "result = NULL, usage = jsonb_build_object("
                "'tool_calls', 0, 'execution_duration_ms', 0, "
                "'reserved_cost_microusd', COALESCE("
                "(run.request->'budget'->>'max_cost_microusd')::bigint, 0), "
                "'measured_cost_microusd', NULL), failure_reason = %s "
                "FROM candidate WHERE run.owner_principal_id = candidate.owner_principal_id "
                "AND run.idempotency_key = candidate.idempotency_key "
                f"RETURNING {_qualified_columns('run')}",
                (
                    [
                        ReadInvestigationRunState.CLAIMED.value,
                        ReadInvestigationRunState.RUNNING.value,
                    ],
                    now,
                    limit,
                    ReadInvestigationRunState.EXPIRED.value,
                    now,
                    now,
                    "lease_expired",
                ),
            )
            rows = await cursor.fetchall()
        return tuple(_run(row) for row in rows)

    async def purge_retained(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[tuple[str, str], ...]:
        _aware("purge now", now)
        _limit(limit, 10_000)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH candidate AS ("
                "SELECT owner_principal_id, idempotency_key "
                "FROM read_investigation_run "
                "WHERE state = ANY(%s) AND retention_until <= %s "
                "ORDER BY retention_until, owner_principal_id, idempotency_key "
                "FOR UPDATE SKIP LOCKED LIMIT %s"
                "), deleted AS ("
                "DELETE FROM read_investigation_run AS run USING candidate "
                "WHERE run.owner_principal_id = candidate.owner_principal_id "
                "AND run.idempotency_key = candidate.idempotency_key "
                "RETURNING run.owner_principal_id, run.idempotency_key"
                ") SELECT owner_principal_id, idempotency_key FROM deleted",
                (
                    [
                        ReadInvestigationRunState.COMPLETED.value,
                        ReadInvestigationRunState.FAILED.value,
                        ReadInvestigationRunState.EXPIRED.value,
                    ],
                    now,
                    limit,
                ),
            )
            rows = await cursor.fetchall()
        return tuple((str(row["owner_principal_id"]), str(row["idempotency_key"])) for row in rows)

    async def _leased_update(
        self,
        query: str,
        params: tuple[object, ...],
        owner_principal_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(query, params)
            row = await cursor.fetchone()
        if row is not None:
            return row
        if await self._run_exists(
            owner_principal_id=owner_principal_id,
            idempotency_key=idempotency_key,
        ):
            raise ReadInvestigationRunConflictError("read investigation lease or revision conflict")
        raise LookupError("read investigation run was not found")

    async def _run_exists(self, *, owner_principal_id: str, idempotency_key: str) -> bool:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT 1 FROM read_investigation_run "
                "WHERE owner_principal_id = %s AND idempotency_key = %s",
                (owner_principal_id, idempotency_key),
            )
            return await cursor.fetchone() is not None

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


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "PostgresReadInvestigationRunStore",
    "PostgresReadInvestigationRunStoreConfig",
]
