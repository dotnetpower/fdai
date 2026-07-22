"""PostgreSQL run store for read-investigation idempotency and result replay."""

# ruff: noqa: S608 - interpolated SQL identifiers are module constants; values are bound.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.read_investigation.idempotency import (
    MAX_READ_INVESTIGATION_ATTEMPTS,
    ReadInvestigationRunConflictError,
    ReadInvestigationRunLease,
    ReadInvestigationRunMode,
    ReadInvestigationRunRecord,
    ReadInvestigationRunState,
    ReadInvestigationRunUsage,
    read_investigation_request_digest,
)
from fdai.core.read_investigation.models import (
    ReadInvestigationBudget,
    ReadInvestigationOutcome,
    ReadInvestigationRequest,
    ReadInvestigationResult,
)
from fdai.shared.providers.read_investigation import (
    ActorKind,
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadInvestigationIntent,
    ReadToolId,
    ResolvedResource,
    ResourceCandidate,
    ResourceResolution,
    ResourceResolutionStatus,
    ResourceSelector,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt

_COLUMNS: Final[str] = (
    "owner_principal_id, idempotency_key, request_digest, request, mode, state, revision, "
    "attempt_count, "
    "lease_owner, lease_token, lease_expires_at, result, usage, failure_reason, "
    "created_at, updated_at, retention_until, terminal_at"
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


def _run(row: dict[str, Any]) -> ReadInvestigationRunRecord:
    request = _request(_mapping(row["request"]))
    usage_raw = row["usage"]
    result_raw = row["result"]
    lease_owner = row["lease_owner"]
    return ReadInvestigationRunRecord(
        owner_principal_id=str(row["owner_principal_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_digest=str(row["request_digest"]),
        request=request,
        mode=ReadInvestigationRunMode(str(row["mode"])),
        state=ReadInvestigationRunState(str(row["state"])),
        revision=int(row["revision"]),
        attempt_count=int(row["attempt_count"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        retention_until=row["retention_until"],
        terminal_at=row["terminal_at"],
        lease=(
            ReadInvestigationRunLease(
                owner=str(lease_owner),
                token=str(row["lease_token"]),
                expires_at=row["lease_expires_at"],
            )
            if lease_owner is not None
            else None
        ),
        result=_result(_mapping(result_raw), request=request) if result_raw is not None else None,
        usage=_usage(_mapping(usage_raw)) if usage_raw is not None else None,
        failure_reason=str(row["failure_reason"]) if row["failure_reason"] is not None else None,
    )


def _request_to_dict(request: ReadInvestigationRequest) -> dict[str, object]:
    return {
        "requester_ref": request.requester_ref,
        "conversation_ref": request.conversation_ref,
        "correlation_ref": request.correlation_ref,
        "intent": request.intent.value,
        "selector": {
            "name": request.selector.name,
            "scope_ref": request.selector.scope_ref,
            "resource_type": request.selector.resource_type,
            "resource_group": request.selector.resource_group,
        },
        "lookback_seconds": request.lookback_seconds,
        "requested_evidence": [item.value for item in request.requested_evidence],
        "budget": {
            "max_wall_seconds": request.budget.max_wall_seconds,
            "max_cost_microusd": request.budget.max_cost_microusd,
            "max_tool_calls": request.budget.max_tool_calls,
            "max_results": request.budget.max_results,
            "max_output_bytes": request.budget.max_output_bytes,
        },
        "idempotency_key": request.idempotency_key,
        "created_at": request.created_at.isoformat(),
        "explicit_deep": request.explicit_deep,
    }


def _request(raw: dict[str, Any]) -> ReadInvestigationRequest:
    selector = _mapping(raw["selector"])
    budget = _mapping(raw["budget"])
    return ReadInvestigationRequest(
        requester_ref=str(raw["requester_ref"]),
        conversation_ref=str(raw["conversation_ref"]),
        correlation_ref=str(raw["correlation_ref"]),
        intent=ReadInvestigationIntent(str(raw["intent"])),
        selector=ResourceSelector(
            name=str(selector["name"]),
            scope_ref=str(selector["scope_ref"]),
            resource_type=(
                str(selector["resource_type"])
                if selector.get("resource_type") is not None
                else None
            ),
            resource_group=(
                str(selector["resource_group"])
                if selector.get("resource_group") is not None
                else None
            ),
        ),
        lookback_seconds=int(raw["lookback_seconds"]),
        requested_evidence=tuple(
            ReadToolId(str(tool_id)) for tool_id in raw.get("requested_evidence", [])
        ),
        budget=ReadInvestigationBudget(
            max_wall_seconds=int(budget["max_wall_seconds"]),
            max_cost_microusd=int(budget["max_cost_microusd"]),
            max_tool_calls=int(budget["max_tool_calls"]),
            max_results=int(budget["max_results"]),
            max_output_bytes=int(budget["max_output_bytes"]),
        ),
        idempotency_key=str(raw["idempotency_key"]),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        explicit_deep=bool(raw.get("explicit_deep", False)),
    )


def _usage_to_dict(usage: ReadInvestigationRunUsage) -> dict[str, int | None]:
    return {
        "tool_calls": usage.tool_calls,
        "execution_duration_ms": usage.execution_duration_ms,
        "reserved_cost_microusd": usage.reserved_cost_microusd,
        "measured_cost_microusd": usage.measured_cost_microusd,
    }


def _usage(raw: dict[str, Any]) -> ReadInvestigationRunUsage:
    return ReadInvestigationRunUsage(
        tool_calls=int(raw["tool_calls"]),
        execution_duration_ms=int(raw["execution_duration_ms"]),
        reserved_cost_microusd=int(raw.get("reserved_cost_microusd", 0)),
        measured_cost_microusd=(
            int(raw["measured_cost_microusd"])
            if raw.get("measured_cost_microusd") is not None
            else None
        ),
    )


def _result_to_dict(result: ReadInvestigationResult) -> dict[str, object]:
    return {
        "outcome": result.outcome.value,
        "resolution": _resolution_to_dict(result.resolution),
        "evidence": [_evidence_to_dict(item) for item in result.evidence],
        "receipts": [_receipt_to_dict(item) for item in result.receipts],
        "progress_kinds": list(result.progress_kinds),
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
    }


def _result(raw: dict[str, Any], *, request: ReadInvestigationRequest) -> ReadInvestigationResult:
    return ReadInvestigationResult(
        request=request,
        outcome=ReadInvestigationOutcome(str(raw["outcome"])),
        resolution=_resolution(_mapping(raw["resolution"])),
        evidence=tuple(_evidence(_mapping(item)) for item in raw.get("evidence", [])),
        receipts=tuple(_receipt(_mapping(item)) for item in raw.get("receipts", [])),
        progress_kinds=tuple(str(item) for item in raw["progress_kinds"]),
        started_at=datetime.fromisoformat(str(raw["started_at"])),
        finished_at=datetime.fromisoformat(str(raw["finished_at"])),
    )


def _resolution_to_dict(resolution: ResourceResolution) -> dict[str, object]:
    return {
        "status": resolution.status.value,
        "resource": (
            {
                "resource_ref": resolution.resource.resource_ref,
                "scope_ref": resolution.resource.scope_ref,
                "name": resolution.resource.name,
                "resource_type": resolution.resource.resource_type,
                "resource_group": resolution.resource.resource_group,
            }
            if resolution.resource is not None
            else None
        ),
        "candidates": [
            {
                "resource_ref": item.resource_ref,
                "name": item.name,
                "resource_type": item.resource_type,
                "resource_group": item.resource_group,
            }
            for item in resolution.candidates
        ],
        "detail": resolution.detail,
    }


def _resolution(raw: dict[str, Any]) -> ResourceResolution:
    resource_raw = raw.get("resource")
    return ResourceResolution(
        status=ResourceResolutionStatus(str(raw["status"])),
        resource=(
            ResolvedResource(
                resource_ref=str(_mapping(resource_raw)["resource_ref"]),
                scope_ref=str(_mapping(resource_raw)["scope_ref"]),
                name=str(_mapping(resource_raw)["name"]),
                resource_type=str(_mapping(resource_raw)["resource_type"]),
                resource_group=(
                    str(_mapping(resource_raw)["resource_group"])
                    if _mapping(resource_raw).get("resource_group") is not None
                    else None
                ),
            )
            if resource_raw is not None
            else None
        ),
        candidates=tuple(
            ResourceCandidate(
                resource_ref=str(_mapping(item)["resource_ref"]),
                name=str(_mapping(item)["name"]),
                resource_type=str(_mapping(item)["resource_type"]),
                resource_group=(
                    str(_mapping(item)["resource_group"])
                    if _mapping(item).get("resource_group") is not None
                    else None
                ),
            )
            for item in raw.get("candidates", [])
        ),
        detail=str(raw["detail"]) if raw.get("detail") is not None else None,
    )


def _evidence_to_dict(envelope: ReadEvidenceEnvelope) -> dict[str, object]:
    return {
        "status": envelope.status.value,
        "authority": envelope.authority,
        "resource_ref": envelope.resource_ref,
        "observed_at": envelope.observed_at.isoformat(),
        "freshness": envelope.freshness.value,
        "truncated": envelope.truncated,
        "records": [_record_to_dict(item) for item in envelope.records],
        "evidence_refs": list(envelope.evidence_refs),
    }


def _evidence(raw: dict[str, Any]) -> ReadEvidenceEnvelope:
    return ReadEvidenceEnvelope(
        status=EvidenceStatus(str(raw["status"])),
        authority=str(raw["authority"]),
        resource_ref=str(raw["resource_ref"]),
        observed_at=datetime.fromisoformat(str(raw["observed_at"])),
        freshness=EvidenceFreshness(str(raw["freshness"])),
        truncated=bool(raw["truncated"]),
        records=tuple(_record(_mapping(item)) for item in raw.get("records", [])),
        evidence_refs=tuple(str(item) for item in raw.get("evidence_refs", [])),
    )


def _record_to_dict(record: ReadEvidenceRecord) -> dict[str, object]:
    return {
        "occurred_at": record.occurred_at.isoformat(),
        "status": record.status,
        "operation_kind": record.operation_kind,
        "actor_ref": record.actor_ref,
        "actor_kind": record.actor_kind.value if record.actor_kind is not None else None,
        "correlation_ref": record.correlation_ref,
        "state": record.state,
        "health_kind": record.health_kind,
    }


def _record(raw: dict[str, Any]) -> ReadEvidenceRecord:
    actor_kind = raw.get("actor_kind")
    return ReadEvidenceRecord(
        occurred_at=datetime.fromisoformat(str(raw["occurred_at"])),
        status=str(raw["status"]),
        operation_kind=(
            str(raw["operation_kind"]) if raw.get("operation_kind") is not None else None
        ),
        actor_ref=str(raw["actor_ref"]) if raw.get("actor_ref") is not None else None,
        actor_kind=ActorKind(str(actor_kind)) if actor_kind is not None else None,
        correlation_ref=(
            str(raw["correlation_ref"]) if raw.get("correlation_ref") is not None else None
        ),
        state=str(raw["state"]) if raw.get("state") is not None else None,
        health_kind=str(raw["health_kind"]) if raw.get("health_kind") is not None else None,
    )


def _receipt_to_dict(receipt: ToolCallReceipt) -> dict[str, object]:
    return {
        "outcome": receipt.outcome.value,
        "receipt_ref": receipt.receipt_ref,
        "already_existed": receipt.already_existed,
        "rollback_succeeded": receipt.rollback_succeeded,
        "detail": receipt.detail,
        "tool_id": receipt.tool_id,
        "transport": receipt.transport,
        "operation_class": receipt.operation_class,
        "queue_duration_ms": receipt.queue_duration_ms,
        "execution_duration_ms": receipt.execution_duration_ms,
        "cost_microusd": receipt.cost_microusd,
        "result_count": receipt.result_count,
        "truncated": receipt.truncated,
        "cache_status": receipt.cache_status,
        "recorded_at": receipt.recorded_at.isoformat() if receipt.recorded_at is not None else None,
        "trace_ref": receipt.trace_ref,
    }


def _receipt(raw: dict[str, Any]) -> ToolCallReceipt:
    recorded_at = raw.get("recorded_at")
    return ToolCallReceipt(
        outcome=ToolCallOutcome(str(raw["outcome"])),
        receipt_ref=str(raw["receipt_ref"]),
        already_existed=bool(raw.get("already_existed", False)),
        rollback_succeeded=(
            bool(raw["rollback_succeeded"]) if raw.get("rollback_succeeded") is not None else None
        ),
        detail=str(raw["detail"]) if raw.get("detail") is not None else None,
        tool_id=str(raw["tool_id"]) if raw.get("tool_id") is not None else None,
        transport=str(raw["transport"]) if raw.get("transport") is not None else None,
        operation_class=(
            str(raw["operation_class"]) if raw.get("operation_class") is not None else None
        ),
        queue_duration_ms=int(raw.get("queue_duration_ms", 0)),
        execution_duration_ms=int(raw.get("execution_duration_ms", 0)),
        cost_microusd=(int(raw["cost_microusd"]) if raw.get("cost_microusd") is not None else None),
        result_count=int(raw.get("result_count", 0)),
        truncated=bool(raw.get("truncated", False)),
        cache_status=str(raw["cache_status"]) if raw.get("cache_status") is not None else None,
        recorded_at=(datetime.fromisoformat(str(recorded_at)) if recorded_at is not None else None),
        trace_ref=str(raw["trace_ref"]) if raw.get("trace_ref") is not None else None,
    )


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    raise RuntimeError("read investigation JSON column is not an object")


def _qualified_columns(alias: str) -> str:
    return ", ".join(f"{alias}.{column.strip()}" for column in _COLUMNS.split(","))


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
