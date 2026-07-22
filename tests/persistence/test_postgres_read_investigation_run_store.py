from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import psycopg
import pytest

from fdai.core.read_investigation import (
    MAX_READ_INVESTIGATION_ATTEMPTS,
    ReadInvestigationBudget,
    ReadInvestigationOutcome,
    ReadInvestigationRequest,
    ReadInvestigationResult,
    ReadInvestigationRunConflictError,
    ReadInvestigationRunMode,
    ReadInvestigationRunState,
    ReadInvestigationRunUsage,
)
from fdai.delivery.persistence import (
    PostgresReadInvestigationRunStore,
    PostgresReadInvestigationRunStoreConfig,
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
    ResourceResolution,
    ResourceResolutionStatus,
    ResourceSelector,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt

_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 22, 0, 0, 0, tzinfo=UTC)
_OWNER_PREFIX = "test-read-run-"


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    downgrade = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "downgrade", "20260722_0051"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert downgrade.returncode == 0, downgrade.stderr
    upgrade = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert upgrade.returncode == 0, upgrade.stderr


@pytest.fixture
async def database_url() -> str:
    dsn = _dsn()
    _upgrade()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            "DELETE FROM read_investigation_run WHERE owner_principal_id LIKE %s",
            (f"{_OWNER_PREFIX}%",),
        )
    return dsn


def _store(dsn: str) -> PostgresReadInvestigationRunStore:
    return PostgresReadInvestigationRunStore(
        config=PostgresReadInvestigationRunStoreConfig(dsn=dsn),
    )


def _request(
    *,
    owner_ref: str,
    idempotency_key: str,
    lookback_seconds: int = 3_600,
) -> ReadInvestigationRequest:
    return ReadInvestigationRequest(
        requester_ref=owner_ref,
        conversation_ref=f"conversation:{idempotency_key}",
        correlation_ref=f"correlation:{idempotency_key}",
        intent=ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY,
        selector=ResourceSelector(name="vm-01", scope_ref="scope:allowed", resource_group="rg-one"),
        lookback_seconds=lookback_seconds,
        requested_evidence=(ReadToolId.QUERY_RESOURCE_ACTIVITY,),
        budget=ReadInvestigationBudget(),
        idempotency_key=idempotency_key,
        created_at=_NOW,
    )


async def test_postgres_schema_readiness_probe(database_url: str) -> None:
    await _store(database_url).verify_schema()


async def test_postgres_schema_readiness_probe_fails_when_table_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store("postgresql://unused")
    connection = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = connection
    connection.execute.side_effect = [None, psycopg.errors.UndefinedTable("missing ledger")]

    async def connect() -> AsyncMock:
        return context

    monkeypatch.setattr(store, "_connect", connect)

    with pytest.raises(psycopg.errors.UndefinedTable, match="missing ledger"):
        await store.verify_schema()


def _result(
    request: ReadInvestigationRequest,
    *,
    cost_microusd: int | None = 17,
) -> ReadInvestigationResult:
    return ReadInvestigationResult(
        request=request,
        outcome=ReadInvestigationOutcome.MATCHED,
        resolution=ResourceResolution(
            status=ResourceResolutionStatus.MATCHED,
            resource=ResolvedResource(
                resource_ref="resource:one",
                scope_ref="scope:allowed",
                name="vm-01",
                resource_type="compute.vm",
                resource_group="rg-one",
            ),
        ),
        evidence=(
            ReadEvidenceEnvelope(
                status=EvidenceStatus.MATCHED,
                authority="azure.activity_log",
                resource_ref="resource:one",
                observed_at=_NOW,
                freshness=EvidenceFreshness.LIVE,
                truncated=False,
                records=(
                    ReadEvidenceRecord(
                        occurred_at=_NOW,
                        status="succeeded",
                        operation_kind="deallocate",
                        actor_ref="principal:actor",
                        actor_kind=ActorKind.USER,
                        correlation_ref="azure-correlation",
                    ),
                ),
                evidence_refs=("evidence:activity:1",),
            ),
        ),
        receipts=(
            ToolCallReceipt(
                outcome=ToolCallOutcome.SUCCEEDED,
                receipt_ref="receipt:activity:1",
                tool_id="query_resource_activity",
                transport="azure_rest",
                operation_class="activity_log",
                queue_duration_ms=12,
                execution_duration_ms=25,
                result_count=1,
                truncated=False,
                cache_status="live",
                cost_microusd=cost_microusd,
                recorded_at=_NOW,
                trace_ref="trace:one",
            ),
        ),
        progress_kinds=("investigation.completed",),
        started_at=_NOW,
        finished_at=_NOW + timedelta(seconds=1),
    )


@pytest.mark.integration
async def test_postgres_claim_is_concurrent_exactly_once(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}concurrent-{uuid.uuid4().hex}"
    request = _request(owner_ref=owner, idempotency_key=f"request:{uuid.uuid4().hex}")
    first = _store(database_url)
    second = _store(database_url)

    claimed = await asyncio.gather(
        first.claim(
            owner_principal_id=owner,
            request=request,
            mode=ReadInvestigationRunMode.STREAMED,
            lease_owner="coordinator:first",
            lease_token="lease:first",
            now=_NOW,
            lease_seconds=30,
            retention_seconds=300,
        ),
        second.claim(
            owner_principal_id=owner,
            request=request,
            mode=ReadInvestigationRunMode.STREAMED,
            lease_owner="coordinator:second",
            lease_token="lease:second",
            now=_NOW,
            lease_seconds=30,
            retention_seconds=300,
        ),
    )

    assert sum(1 for _record, created in claimed if created) == 1
    assert claimed[0][0] == claimed[1][0]


@pytest.mark.integration
async def test_postgres_schema_exposes_attempt_count_with_bounds(database_url: str) -> None:
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        column_cursor = await connection.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'read_investigation_run' AND column_name = 'attempt_count'"
        )
        column = await column_cursor.fetchone()
        assert column is not None
        assert column[1] == "NO"

        with pytest.raises(psycopg.errors.CheckViolation):
            await connection.execute(
                "INSERT INTO read_investigation_run ("
                "owner_principal_id, idempotency_key, request_digest, request, "
                "mode, state, revision, attempt_count, "
                "lease_owner, lease_token, lease_expires_at, result, usage, failure_reason, "
                "created_at, updated_at, retention_until, terminal_at"
                ") VALUES ("
                "%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, "
                "%s::jsonb, %s::jsonb, %s, %s, %s, %s, %s"
                ")",
                (
                    f"{_OWNER_PREFIX}schema-{uuid.uuid4().hex}",
                    f"request:{uuid.uuid4().hex}",
                    "0" * 64,
                    "{}",
                    "direct",
                    "claimed",
                    1,
                    0,
                    "read-api",
                    "lease:invalid",
                    _NOW + timedelta(seconds=30),
                    None,
                    None,
                    None,
                    _NOW,
                    _NOW,
                    _NOW + timedelta(seconds=300),
                    None,
                ),
            )


@pytest.mark.integration
async def test_postgres_claim_conflicts_on_digest_reuse(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}conflict-{uuid.uuid4().hex}"
    key = f"request:{uuid.uuid4().hex}"
    store = _store(database_url)
    await store.claim(
        owner_principal_id=owner,
        request=_request(owner_ref=owner, idempotency_key=key, lookback_seconds=3_600),
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )

    with pytest.raises(ReadInvestigationRunConflictError, match="reused"):
        await store.claim(
            owner_principal_id=owner,
            request=_request(owner_ref=owner, idempotency_key=key, lookback_seconds=7_200),
            mode=ReadInvestigationRunMode.DIRECT,
            lease_owner="coordinator:two",
            lease_token="lease:two",
            now=_NOW,
            lease_seconds=30,
            retention_seconds=300,
        )


@pytest.mark.integration
async def test_postgres_claim_isolated_by_owner(database_url: str) -> None:
    key = f"request:{uuid.uuid4().hex}"
    owner_one = f"{_OWNER_PREFIX}owner-a-{uuid.uuid4().hex}"
    owner_two = f"{_OWNER_PREFIX}owner-b-{uuid.uuid4().hex}"
    store = _store(database_url)

    first, first_created = await store.claim(
        owner_principal_id=owner_one,
        request=_request(owner_ref=owner_one, idempotency_key=key),
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    second, second_created = await store.claim(
        owner_principal_id=owner_two,
        request=_request(owner_ref=owner_two, idempotency_key=key),
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:two",
        lease_token="lease:two",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )

    assert first_created is True
    assert second_created is True
    assert first.owner_principal_id != second.owner_principal_id


@pytest.mark.integration
@pytest.mark.parametrize("measured_cost_microusd", [None, 17])
async def test_postgres_completed_result_round_trip(
    database_url: str,
    measured_cost_microusd: int | None,
) -> None:
    owner = f"{_OWNER_PREFIX}roundtrip-{uuid.uuid4().hex}"
    key = f"request:{uuid.uuid4().hex}"
    request = _request(owner_ref=owner, idempotency_key=key)
    store = _store(database_url)

    claimed, _ = await store.claim(
        owner_principal_id=owner,
        request=request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    running = await store.start(
        owner_principal_id=owner,
        idempotency_key=key,
        expected_revision=claimed.revision,
        lease_token="lease:one",
        now=_NOW + timedelta(seconds=1),
    )
    completed = await store.complete(
        owner_principal_id=owner,
        idempotency_key=key,
        expected_revision=running.revision,
        lease_token="lease:one",
        result=_result(request, cost_microusd=measured_cost_microusd),
        usage=ReadInvestigationRunUsage(
            tool_calls=2,
            execution_duration_ms=37,
            reserved_cost_microusd=100_000,
            measured_cost_microusd=measured_cost_microusd,
        ),
        now=_NOW + timedelta(seconds=2),
    )
    replayed, created = await store.claim(
        owner_principal_id=owner,
        request=request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:retry",
        lease_token="lease:retry",
        now=_NOW + timedelta(seconds=3),
        lease_seconds=30,
        retention_seconds=300,
    )

    assert created is False
    assert replayed.state is ReadInvestigationRunState.COMPLETED
    assert replayed.result == completed.result
    assert replayed.result is not None
    assert replayed.result.receipts[0].cost_microusd == measured_cost_microusd
    assert replayed.usage == ReadInvestigationRunUsage(
        tool_calls=2,
        execution_duration_ms=37,
        reserved_cost_microusd=100_000,
        measured_cost_microusd=measured_cost_microusd,
    )
    assert completed.terminal_at == _NOW + timedelta(seconds=2)
    assert replayed.terminal_at == _NOW + timedelta(seconds=2)
    assert replayed.attempt_count == 1


@pytest.mark.integration
async def test_postgres_failed_run_reclaims_with_attempt_increment(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}reclaim-failed-{uuid.uuid4().hex}"
    key = f"request:{uuid.uuid4().hex}"
    request = _request(owner_ref=owner, idempotency_key=key)
    store = _store(database_url)

    claimed, _ = await store.claim(
        owner_principal_id=owner,
        request=request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    failed = await store.fail(
        owner_principal_id=owner,
        idempotency_key=key,
        expected_revision=claimed.revision,
        lease_token="lease:one",
        failure_reason="provider_unavailable",
        usage=ReadInvestigationRunUsage(tool_calls=1, execution_duration_ms=10),
        now=_NOW + timedelta(seconds=1),
    )

    reclaimed = await store.reclaim(
        owner_principal_id=owner,
        idempotency_key=key,
        request_digest=failed.request_digest,
        mode=ReadInvestigationRunMode.DIRECT,
        expected_revision=failed.revision,
        lease_owner="coordinator:retry",
        lease_token="lease:retry",
        now=_NOW + timedelta(seconds=2),
        lease_seconds=30,
        retention_seconds=300,
    )

    assert reclaimed.state is ReadInvestigationRunState.CLAIMED
    assert reclaimed.attempt_count == 2
    assert reclaimed.terminal_at is None
    assert reclaimed.usage is None
    assert reclaimed.failure_reason is None


@pytest.mark.integration
async def test_postgres_expired_run_reclaims(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}reclaim-expired-{uuid.uuid4().hex}"
    key = f"request:{uuid.uuid4().hex}"
    request = _request(owner_ref=owner, idempotency_key=key)
    store = _store(database_url)
    claimed, _ = await store.claim(
        owner_principal_id=owner,
        request=request,
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=1,
        retention_seconds=300,
    )
    expired = await store.reconcile_expired(now=_NOW + timedelta(seconds=1), limit=10)

    reclaimed = await store.reclaim(
        owner_principal_id=owner,
        idempotency_key=key,
        request_digest=claimed.request_digest,
        mode=ReadInvestigationRunMode.STREAMED,
        expected_revision=expired[0].revision,
        lease_owner="coordinator:retry",
        lease_token="lease:retry",
        now=_NOW + timedelta(seconds=2),
        lease_seconds=30,
        retention_seconds=300,
    )

    assert len(expired) == 1
    assert reclaimed.state is ReadInvestigationRunState.CLAIMED
    assert reclaimed.attempt_count == 2


@pytest.mark.integration
async def test_postgres_reclaim_exhausted_returns_conflict(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}reclaim-exhausted-{uuid.uuid4().hex}"
    key = f"request:{uuid.uuid4().hex}"
    request = _request(owner_ref=owner, idempotency_key=key)
    store = _store(database_url)

    current, _ = await store.claim(
        owner_principal_id=owner,
        request=request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    for attempt in range(2, MAX_READ_INVESTIGATION_ATTEMPTS + 1):
        failed = await store.fail(
            owner_principal_id=owner,
            idempotency_key=key,
            expected_revision=current.revision,
            lease_token=current.lease.token if current.lease is not None else "lease:unexpected",
            failure_reason=f"attempt:{attempt}",
            usage=ReadInvestigationRunUsage(tool_calls=attempt, execution_duration_ms=attempt),
            now=_NOW + timedelta(seconds=attempt),
        )
        current = await store.reclaim(
            owner_principal_id=owner,
            idempotency_key=key,
            request_digest=failed.request_digest,
            mode=ReadInvestigationRunMode.DIRECT,
            expected_revision=failed.revision,
            lease_owner="coordinator:retry",
            lease_token=f"lease:retry:{attempt}",
            now=_NOW + timedelta(seconds=attempt, milliseconds=1),
            lease_seconds=30,
            retention_seconds=300,
        )

    exhausted = await store.fail(
        owner_principal_id=owner,
        idempotency_key=key,
        expected_revision=current.revision,
        lease_token=current.lease.token if current.lease is not None else "lease:unexpected",
        failure_reason="terminal:max",
        usage=ReadInvestigationRunUsage(tool_calls=0, execution_duration_ms=0),
        now=_NOW + timedelta(seconds=20),
    )

    with pytest.raises(ReadInvestigationRunConflictError, match="lease or revision"):
        await store.reclaim(
            owner_principal_id=owner,
            idempotency_key=key,
            request_digest=exhausted.request_digest,
            mode=ReadInvestigationRunMode.DIRECT,
            expected_revision=exhausted.revision,
            lease_owner="coordinator:retry",
            lease_token="lease:retry:exhausted",
            now=_NOW + timedelta(seconds=21),
            lease_seconds=30,
            retention_seconds=300,
        )


@pytest.mark.integration
async def test_postgres_reconcile_expired_lease_once(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}expired-{uuid.uuid4().hex}"
    key = f"request:{uuid.uuid4().hex}"
    store = _store(database_url)
    await store.claim(
        owner_principal_id=owner,
        request=_request(owner_ref=owner, idempotency_key=key),
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=1,
        retention_seconds=300,
    )

    first = await store.reconcile_expired(now=_NOW + timedelta(seconds=1), limit=10)
    second = await store.reconcile_expired(now=_NOW + timedelta(seconds=2), limit=10)

    assert len(first) == 1
    assert first[0].state is ReadInvestigationRunState.EXPIRED
    assert first[0].failure_reason == "lease_expired"
    assert first[0].terminal_at == _NOW + timedelta(seconds=1)
    assert second == ()


@pytest.mark.integration
async def test_postgres_renew_running_lease_with_cas(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}renew-{uuid.uuid4().hex}"
    key = f"request:{uuid.uuid4().hex}"
    request = _request(owner_ref=owner, idempotency_key=key)
    store = _store(database_url)

    claimed, _ = await store.claim(
        owner_principal_id=owner,
        request=request,
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=2,
        retention_seconds=300,
    )
    running = await store.start(
        owner_principal_id=owner,
        idempotency_key=key,
        expected_revision=claimed.revision,
        lease_token="lease:one",
        now=_NOW,
    )
    renewed = await store.renew(
        owner_principal_id=owner,
        idempotency_key=key,
        expected_revision=running.revision,
        lease_token="lease:one",
        now=_NOW + timedelta(seconds=1),
        lease_seconds=2,
        lease_ceiling_at=_NOW + timedelta(seconds=2),
    )

    assert renewed.revision == running.revision + 1
    assert renewed.lease is not None
    assert renewed.lease.expires_at == _NOW + timedelta(seconds=2)

    with pytest.raises(ReadInvestigationRunConflictError, match="lease or revision"):
        await store.renew(
            owner_principal_id=owner,
            idempotency_key=key,
            expected_revision=running.revision,
            lease_token="lease:one",
            now=_NOW + timedelta(seconds=1),
            lease_seconds=2,
            lease_ceiling_at=_NOW + timedelta(seconds=3),
        )


@pytest.mark.integration
async def test_postgres_renew_before_running_conflicts(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}renew-claimed-{uuid.uuid4().hex}"
    key = f"request:{uuid.uuid4().hex}"
    store = _store(database_url)
    claimed, _ = await store.claim(
        owner_principal_id=owner,
        request=_request(owner_ref=owner, idempotency_key=key),
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )

    with pytest.raises(ReadInvestigationRunConflictError, match="lease or revision"):
        await store.renew(
            owner_principal_id=owner,
            idempotency_key=key,
            expected_revision=claimed.revision,
            lease_token="lease:one",
            now=_NOW,
            lease_seconds=30,
            lease_ceiling_at=_NOW + timedelta(seconds=120),
        )


@pytest.mark.integration
async def test_postgres_purge_retained_terminal_only(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}purge-{uuid.uuid4().hex}"
    terminal_key = f"request:terminal:{uuid.uuid4().hex}"
    active_key = f"request:active:{uuid.uuid4().hex}"
    store = _store(database_url)

    terminal_claimed, _ = await store.claim(
        owner_principal_id=owner,
        request=_request(owner_ref=owner, idempotency_key=terminal_key),
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=2,
    )
    await store.fail(
        owner_principal_id=owner,
        idempotency_key=terminal_key,
        expected_revision=terminal_claimed.revision,
        lease_token="lease:one",
        failure_reason="provider_unavailable",
        usage=ReadInvestigationRunUsage(tool_calls=1, execution_duration_ms=10),
        now=_NOW + timedelta(seconds=1),
    )
    await store.claim(
        owner_principal_id=owner,
        request=_request(owner_ref=owner, idempotency_key=active_key),
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:two",
        lease_token="lease:two",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=2,
    )

    purged = await store.purge_retained(now=_NOW + timedelta(seconds=3), limit=10)
    active = await store.get(owner_principal_id=owner, idempotency_key=active_key)

    assert purged == ((owner, terminal_key),)
    assert active is not None and active.state is ReadInvestigationRunState.CLAIMED
