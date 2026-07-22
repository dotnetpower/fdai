from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.read_investigation import (
    MAX_READ_INVESTIGATION_ATTEMPTS,
    InMemoryReadInvestigationRunStore,
    ReadInvestigationBudget,
    ReadInvestigationOutcome,
    ReadInvestigationRequest,
    ReadInvestigationResult,
    ReadInvestigationRunConflictError,
    ReadInvestigationRunMode,
    ReadInvestigationRunState,
    ReadInvestigationRunUsage,
)
from fdai.shared.providers.read_investigation import (
    ReadInvestigationIntent,
    ResolvedResource,
    ResourceResolution,
    ResourceResolutionStatus,
    ResourceSelector,
)

_NOW = datetime(2026, 7, 22, 0, 0, 0, tzinfo=UTC)


def _request(
    *,
    idempotency_key: str = "request:key",
    conversation_ref: str = "conversation:one",
    correlation_ref: str = "correlation:one",
    lookback_seconds: int = 3_600,
) -> ReadInvestigationRequest:
    return ReadInvestigationRequest(
        requester_ref="principal:requester",
        conversation_ref=conversation_ref,
        correlation_ref=correlation_ref,
        intent=ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY,
        selector=ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
        lookback_seconds=lookback_seconds,
        requested_evidence=(),
        budget=ReadInvestigationBudget(),
        idempotency_key=idempotency_key,
        created_at=_NOW,
    )


def _result(request: ReadInvestigationRequest) -> ReadInvestigationResult:
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
                resource_group="rg-example",
            ),
        ),
        evidence=(),
        receipts=(),
        progress_kinds=("investigation.completed",),
        started_at=_NOW,
        finished_at=_NOW,
    )


async def test_same_owner_and_same_digest_dedupes() -> None:
    store = InMemoryReadInvestigationRunStore()
    first_request = _request()
    second_request = _request(
        conversation_ref="conversation:retry",
        correlation_ref="correlation:retry",
    )

    first, first_created = await store.claim(
        owner_principal_id="principal:one",
        request=first_request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    second, second_created = await store.claim(
        owner_principal_id="principal:one",
        request=second_request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:two",
        lease_token="lease:two",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )

    assert first_created is True
    assert second_created is False
    assert second == first
    assert second.attempt_count == 1


async def test_same_owner_and_key_with_different_digest_conflicts() -> None:
    store = InMemoryReadInvestigationRunStore()
    await store.claim(
        owner_principal_id="principal:one",
        request=_request(lookback_seconds=3_600),
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )

    with pytest.raises(ReadInvestigationRunConflictError, match="reused"):
        await store.claim(
            owner_principal_id="principal:one",
            request=_request(lookback_seconds=7_200),
            mode=ReadInvestigationRunMode.DIRECT,
            lease_owner="coordinator:two",
            lease_token="lease:two",
            now=_NOW,
            lease_seconds=30,
            retention_seconds=300,
        )


async def test_different_owner_is_independent_for_same_idempotency_key() -> None:
    store = InMemoryReadInvestigationRunStore()
    first, first_created = await store.claim(
        owner_principal_id="principal:one",
        request=_request(),
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    second, second_created = await store.claim(
        owner_principal_id="principal:two",
        request=_request(),
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


async def test_concurrent_claim_allows_exactly_one_creator() -> None:
    store = InMemoryReadInvestigationRunStore()
    request = _request()

    claims = await asyncio.gather(
        store.claim(
            owner_principal_id="principal:one",
            request=request,
            mode=ReadInvestigationRunMode.STREAMED,
            lease_owner="coordinator:one",
            lease_token="lease:one",
            now=_NOW,
            lease_seconds=30,
            retention_seconds=300,
        ),
        store.claim(
            owner_principal_id="principal:one",
            request=request,
            mode=ReadInvestigationRunMode.STREAMED,
            lease_owner="coordinator:two",
            lease_token="lease:two",
            now=_NOW,
            lease_seconds=30,
            retention_seconds=300,
        ),
    )

    assert sum(1 for _, created in claims if created) == 1
    assert claims[0][0] == claims[1][0]


async def test_completed_result_replays_for_same_owner_and_key() -> None:
    store = InMemoryReadInvestigationRunStore()
    request = _request()
    claimed, _created = await store.claim(
        owner_principal_id="principal:one",
        request=request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    running = await store.start(
        owner_principal_id="principal:one",
        idempotency_key=request.idempotency_key,
        expected_revision=claimed.revision,
        lease_token="lease:one",
        now=_NOW,
    )
    completed = await store.complete(
        owner_principal_id="principal:one",
        idempotency_key=request.idempotency_key,
        expected_revision=running.revision,
        lease_token="lease:one",
        result=_result(request),
        usage=ReadInvestigationRunUsage(tool_calls=2, execution_duration_ms=200),
        now=_NOW,
    )
    replayed, created = await store.claim(
        owner_principal_id="principal:one",
        request=request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:retry",
        lease_token="lease:retry",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )

    assert created is False
    assert replayed.state is ReadInvestigationRunState.COMPLETED
    assert replayed.result == completed.result
    assert completed.terminal_at == _NOW
    assert replayed.terminal_at == _NOW
    assert replayed.attempt_count == 1


async def test_failed_run_can_be_reclaimed_until_retry_budget() -> None:
    store = InMemoryReadInvestigationRunStore()
    request = _request(idempotency_key="request:reclaim")
    claimed, _ = await store.claim(
        owner_principal_id="principal:one",
        request=request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    failed = await store.fail(
        owner_principal_id="principal:one",
        idempotency_key=request.idempotency_key,
        expected_revision=claimed.revision,
        lease_token="lease:one",
        failure_reason="provider_unavailable",
        usage=ReadInvestigationRunUsage(tool_calls=1, execution_duration_ms=5),
        now=_NOW,
    )

    reclaimed = await store.reclaim(
        owner_principal_id="principal:one",
        idempotency_key=request.idempotency_key,
        request_digest=failed.request_digest,
        mode=ReadInvestigationRunMode.DIRECT,
        expected_revision=failed.revision,
        lease_owner="coordinator:retry",
        lease_token="lease:retry",
        now=_NOW + timedelta(seconds=1),
        lease_seconds=30,
        retention_seconds=300,
    )

    assert reclaimed.state is ReadInvestigationRunState.CLAIMED
    assert reclaimed.attempt_count == 2
    assert reclaimed.terminal_at is None
    assert reclaimed.usage is None
    assert reclaimed.failure_reason is None


async def test_expired_run_can_be_reclaimed() -> None:
    store = InMemoryReadInvestigationRunStore()
    request = _request(idempotency_key="request:reclaim-expired")
    claimed, _ = await store.claim(
        owner_principal_id="principal:one",
        request=request,
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=1,
        retention_seconds=300,
    )
    expired = await store.reconcile_expired(now=_NOW + timedelta(seconds=1))
    assert len(expired) == 1

    reclaimed = await store.reclaim(
        owner_principal_id="principal:one",
        idempotency_key=request.idempotency_key,
        request_digest=claimed.request_digest,
        mode=ReadInvestigationRunMode.STREAMED,
        expected_revision=expired[0].revision,
        lease_owner="coordinator:retry",
        lease_token="lease:retry",
        now=_NOW + timedelta(seconds=2),
        lease_seconds=30,
        retention_seconds=300,
    )

    assert reclaimed.state is ReadInvestigationRunState.CLAIMED
    assert reclaimed.attempt_count == 2


async def test_reclaim_exhaustion_is_non_retryable() -> None:
    store = InMemoryReadInvestigationRunStore()
    request = _request(idempotency_key="request:reclaim-exhausted")
    claimed, _ = await store.claim(
        owner_principal_id="principal:one",
        request=request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )

    current = claimed
    for attempt in range(2, MAX_READ_INVESTIGATION_ATTEMPTS + 1):
        failed = await store.fail(
            owner_principal_id="principal:one",
            idempotency_key=request.idempotency_key,
            expected_revision=current.revision,
            lease_token=current.lease.token if current.lease is not None else "lease:unexpected",
            failure_reason=f"attempt:{attempt}",
            usage=ReadInvestigationRunUsage(tool_calls=attempt, execution_duration_ms=attempt),
            now=_NOW + timedelta(seconds=attempt),
        )
        current = await store.reclaim(
            owner_principal_id="principal:one",
            idempotency_key=request.idempotency_key,
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
        owner_principal_id="principal:one",
        idempotency_key=request.idempotency_key,
        expected_revision=current.revision,
        lease_token=current.lease.token if current.lease is not None else "lease:unexpected",
        failure_reason="terminal:max",
        usage=ReadInvestigationRunUsage(tool_calls=0, execution_duration_ms=0),
        now=_NOW + timedelta(seconds=20),
    )

    with pytest.raises(ReadInvestigationRunConflictError, match="exhausted"):
        await store.reclaim(
            owner_principal_id="principal:one",
            idempotency_key=request.idempotency_key,
            request_digest=exhausted.request_digest,
            mode=ReadInvestigationRunMode.DIRECT,
            expected_revision=exhausted.revision,
            lease_owner="coordinator:retry",
            lease_token="lease:retry:exhausted",
            now=_NOW + timedelta(seconds=21),
            lease_seconds=30,
            retention_seconds=300,
        )


async def test_reconcile_expired_is_deterministic() -> None:
    store = InMemoryReadInvestigationRunStore()
    request = _request()
    await store.claim(
        owner_principal_id="principal:one",
        request=request,
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=1,
        retention_seconds=300,
    )

    first = await store.reconcile_expired(now=_NOW + timedelta(seconds=1))
    second = await store.reconcile_expired(now=_NOW + timedelta(seconds=2))

    assert len(first) == 1
    assert first[0].state is ReadInvestigationRunState.EXPIRED
    assert first[0].failure_reason == "lease_expired"
    assert first[0].terminal_at == _NOW + timedelta(seconds=1)
    assert second == ()


async def test_renew_running_extends_lease_with_cas_and_ceiling() -> None:
    store = InMemoryReadInvestigationRunStore()
    request = _request(idempotency_key="request:renew")
    claimed, _ = await store.claim(
        owner_principal_id="principal:one",
        request=request,
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=2,
        retention_seconds=300,
    )
    running = await store.start(
        owner_principal_id="principal:one",
        idempotency_key=request.idempotency_key,
        expected_revision=claimed.revision,
        lease_token="lease:one",
        now=_NOW,
    )
    renewed = await store.renew(
        owner_principal_id="principal:one",
        idempotency_key=request.idempotency_key,
        expected_revision=running.revision,
        lease_token="lease:one",
        now=_NOW + timedelta(seconds=1),
        lease_seconds=2,
        lease_ceiling_at=_NOW + timedelta(seconds=2),
    )

    assert renewed.revision == running.revision + 1
    assert renewed.lease is not None
    assert renewed.lease.expires_at == _NOW + timedelta(seconds=2)

    with pytest.raises(ReadInvestigationRunConflictError, match="revision"):
        await store.renew(
            owner_principal_id="principal:one",
            idempotency_key=request.idempotency_key,
            expected_revision=running.revision,
            lease_token="lease:one",
            now=_NOW + timedelta(seconds=1),
            lease_seconds=2,
            lease_ceiling_at=_NOW + timedelta(seconds=3),
        )


async def test_renew_before_running_conflicts() -> None:
    store = InMemoryReadInvestigationRunStore()
    request = _request(idempotency_key="request:renew-claimed")
    claimed, _ = await store.claim(
        owner_principal_id="principal:one",
        request=request,
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=300,
    )

    with pytest.raises(ReadInvestigationRunConflictError, match="state transition"):
        await store.renew(
            owner_principal_id="principal:one",
            idempotency_key=request.idempotency_key,
            expected_revision=claimed.revision,
            lease_token="lease:one",
            now=_NOW,
            lease_seconds=30,
            lease_ceiling_at=_NOW + timedelta(seconds=120),
        )


async def test_retention_purge_removes_terminal_runs_only() -> None:
    store = InMemoryReadInvestigationRunStore()
    terminal_request = _request(idempotency_key="request:terminal")
    active_request = _request(idempotency_key="request:active")

    claimed_terminal, _ = await store.claim(
        owner_principal_id="principal:one",
        request=terminal_request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="coordinator:one",
        lease_token="lease:one",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=2,
    )
    await store.fail(
        owner_principal_id="principal:one",
        idempotency_key=terminal_request.idempotency_key,
        expected_revision=claimed_terminal.revision,
        lease_token="lease:one",
        failure_reason="provider_unavailable",
        usage=ReadInvestigationRunUsage(tool_calls=1, execution_duration_ms=10),
        now=_NOW,
    )
    await store.claim(
        owner_principal_id="principal:one",
        request=active_request,
        mode=ReadInvestigationRunMode.STREAMED,
        lease_owner="coordinator:two",
        lease_token="lease:two",
        now=_NOW,
        lease_seconds=30,
        retention_seconds=2,
    )

    purged = await store.purge_retained(now=_NOW + timedelta(seconds=3))
    active = await store.get(
        owner_principal_id="principal:one",
        idempotency_key=active_request.idempotency_key,
    )

    assert purged == (("principal:one", terminal_request.idempotency_key),)
    assert active is not None and active.state is ReadInvestigationRunState.CLAIMED
