"""Durable protection reconciliation lifecycle tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai_document_worker_service.adapters.protection import (
    ProtectionReconciliationCandidate,
    ProtectionReconciliationDecision,
)
from fdai_document_worker_service.protection_reconciliation import (
    ClaimedProtectionCandidate,
    ProtectionReconciliationService,
)
from fdai_service_contracts import ProtectionState


class Store:
    def __init__(self, claim: ClaimedProtectionCandidate) -> None:
        self.due = [claim]
        self.cleanup: list[ClaimedProtectionCandidate] = []
        self.invalidated = False
        self.completed = False

    async def claim_due(
        self, *, owner: str, limit: int, lease_seconds: int
    ) -> tuple[ClaimedProtectionCandidate, ...]:
        assert owner == "worker:protection"
        assert limit == 10
        assert lease_seconds == 30
        claimed, self.due = tuple(self.due), []
        return claimed

    async def apply_decisions(
        self,
        claims: object,
        decisions: object,
        *,
        next_check_at: datetime,
    ) -> None:
        assert claims
        decision = tuple(decisions)[0]  # type: ignore[arg-type]
        assert decision.revoked is True
        assert next_check_at > datetime.now(tz=UTC)
        self.invalidated = True
        self.cleanup = [tuple(claims)[0]]  # type: ignore[arg-type]

    async def claim_cleanup(
        self, *, owner: str, limit: int, lease_seconds: int
    ) -> tuple[ClaimedProtectionCandidate, ...]:
        assert self.invalidated is True
        claimed, self.cleanup = tuple(self.cleanup), []
        return claimed

    async def complete_cleanup(self, claim: ClaimedProtectionCandidate) -> None:
        assert self.invalidated is True
        assert claim.candidate.version_id == UUID(int=2)
        self.completed = True


class Provider:
    async def reconcile(self, candidates: object) -> tuple[ProtectionReconciliationDecision, ...]:
        candidate = tuple(candidates)[0]  # type: ignore[arg-type]
        return (
            ProtectionReconciliationDecision(
                document_id=candidate.document_id,
                version_id=candidate.version_id,
                source_sha256=candidate.source_sha256,
                policy_revision=candidate.policy_revision + 1,
                revoked=True,
                state=ProtectionState.RIGHTS_MANAGED_ACCESS_DENIED,
                reason_code="rights_management_revoked",
            ),
        )


class Derivative:
    def __init__(self, store: Store, *, fail: bool = False) -> None:
        self.store = store
        self.fail = fail
        self.deleted: list[tuple[UUID, UUID]] = []

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        assert self.store.invalidated is True
        if self.fail:
            raise RuntimeError("cleanup unavailable")
        self.deleted.append((document_id, version_id))


def _claim() -> ClaimedProtectionCandidate:
    return ClaimedProtectionCandidate(
        candidate=ProtectionReconciliationCandidate(
            document_id=UUID(int=1),
            version_id=UUID(int=2),
            source_sha256="a" * 64,
            provider_ref="provider:document:1",
            policy_revision=7,
        ),
        upload_id=UUID(int=3),
        claim_owner="worker:protection",
        claim_revision=2,
    )


async def test_revocation_invalidates_before_derivative_cleanup() -> None:
    store = Store(_claim())
    index = Derivative(store)
    artifacts = Derivative(store)
    service = ProtectionReconciliationService(
        store=store,
        provider=Provider(),  # type: ignore[arg-type]
        index=index,  # type: ignore[arg-type]
        artifacts=artifacts,  # type: ignore[arg-type]
        owner="worker:protection",
        batch_size=10,
        lease_seconds=30,
        clock=lambda: datetime.now(tz=UTC),
        next_check=lambda now: now + timedelta(minutes=5),
    )

    assert await service.reconcile_once() == 2
    assert store.completed is True
    assert index.deleted == [(UUID(int=1), UUID(int=2))]
    assert artifacts.deleted == [(UUID(int=1), UUID(int=2))]


async def test_cleanup_failure_remains_incomplete_for_restart() -> None:
    store = Store(_claim())
    service = ProtectionReconciliationService(
        store=store,
        provider=Provider(),  # type: ignore[arg-type]
        index=Derivative(store, fail=True),  # type: ignore[arg-type]
        artifacts=Derivative(store),  # type: ignore[arg-type]
        owner="worker:protection",
        batch_size=10,
        lease_seconds=30,
        clock=lambda: datetime.now(tz=UTC),
        next_check=lambda now: now + timedelta(minutes=5),
    )

    with pytest.raises(RuntimeError, match="cleanup unavailable"):
        await service.reconcile_once()
    assert store.invalidated is True
    assert store.completed is False
