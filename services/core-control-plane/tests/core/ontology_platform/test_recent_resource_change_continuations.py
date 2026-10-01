from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.recent_resource_change_continuations import (
    ContinuationBinding,
    ContinuationInvalidError,
    InMemoryRecentResourceChangeContinuationStore,
    RecentResourceChangeContinuationIssuer,
)

NOW = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)
OTHER_DIGEST = "sha256:" + ("b" * 64)


@dataclass(frozen=True, slots=True)
class _Cursor:
    last_effective_at: datetime
    last_subject_ref: str


def _binding() -> ContinuationBinding:
    return ContinuationBinding(
        deployment_scope_digest=DIGEST,
        conversation_id="conversation-a",
        admitted_goal_digest=DIGEST,
        plan_digest=DIGEST,
        manifest_digest=DIGEST,
    )


def _context(principal: str = DIGEST) -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        purposes=("operations-review",),
        principal_scope_digest=principal,
    )


@pytest.mark.asyncio
async def test_continuation_binds_context_and_cursor_without_exposing_rows() -> None:
    store = InMemoryRecentResourceChangeContinuationStore()
    issuer = RecentResourceChangeContinuationIssuer(
        store=store,
        binding=_binding(),
        clock=lambda: NOW,
    )
    continuation_ref = await issuer.issue(
        context=_context(),
        start_at=NOW - timedelta(days=1),
        end_at=NOW,
        known_at=NOW,
        query_version_digest=DIGEST,
        page_size=20,
        cursor=_Cursor(NOW - timedelta(minutes=1), "resource-020"),
        remaining_rows=7,
    )

    request = await issuer.request(
        continuation_ref=continuation_ref,
        context=_context(),
        page_size=5,
        query_version_digest=DIGEST,
    )

    assert request.page_size == 5
    assert request.cursor_subject_ref == "resource-020"
    assert request.continuation.remaining_rows == 7
    assert "resource-020" not in request.continuation.keyset_cursor.cursor_digest
    assert request.continuation.keyset_cursor.last_subject_digest is not None


@pytest.mark.asyncio
async def test_continuation_invalidates_foreign_principal_version_and_expiry() -> None:
    store = InMemoryRecentResourceChangeContinuationStore()
    issuer = RecentResourceChangeContinuationIssuer(
        store=store,
        binding=_binding(),
        clock=lambda: NOW,
    )
    continuation_ref = await issuer.issue(
        context=_context(),
        start_at=NOW - timedelta(days=1),
        end_at=NOW,
        known_at=NOW,
        query_version_digest=DIGEST,
        page_size=20,
        cursor=_Cursor(NOW - timedelta(minutes=1), "resource-020"),
        remaining_rows=7,
    )

    with pytest.raises(ContinuationInvalidError):
        await issuer.request(
            continuation_ref=continuation_ref,
            context=_context(OTHER_DIGEST),
            page_size=20,
            query_version_digest=DIGEST,
        )
    with pytest.raises(ContinuationInvalidError):
        await issuer.request(
            continuation_ref=continuation_ref,
            context=_context(),
            page_size=20,
            query_version_digest=OTHER_DIGEST,
        )

    expired = RecentResourceChangeContinuationIssuer(
        store=store,
        binding=_binding(),
        clock=lambda: NOW + timedelta(minutes=16),
    )
    with pytest.raises(ContinuationInvalidError):
        await expired.request(
            continuation_ref=continuation_ref,
            context=_context(),
            page_size=20,
            query_version_digest=DIGEST,
        )


@pytest.mark.asyncio
async def test_concurrent_requests_can_claim_a_continuation_only_once() -> None:
    store = InMemoryRecentResourceChangeContinuationStore()
    issuer = RecentResourceChangeContinuationIssuer(
        store=store,
        binding=_binding(),
        clock=lambda: NOW,
    )
    continuation_ref = await issuer.issue(
        context=_context(),
        start_at=NOW - timedelta(days=1),
        end_at=NOW,
        known_at=NOW,
        query_version_digest=DIGEST,
        page_size=20,
        cursor=_Cursor(NOW - timedelta(minutes=1), "resource-020"),
        remaining_rows=7,
    )

    results = await asyncio.gather(
        *(
            issuer.request(
                continuation_ref=continuation_ref,
                context=_context(),
                page_size=20,
                query_version_digest=DIGEST,
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, ContinuationInvalidError) for result in results) == 1
    assert sum(not isinstance(result, Exception) for result in results) == 1
