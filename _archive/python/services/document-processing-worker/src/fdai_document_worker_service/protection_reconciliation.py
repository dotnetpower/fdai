"""Durable rights-revocation reconciliation and derivative invalidation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from fdai_service_contracts import DocumentArtifactStore, DocumentIndex

from fdai_document_worker_service.adapters.protection import (
    ProtectionReconciliationCandidate,
    ProtectionReconciliationDecision,
    PurviewRmsRevocationReconciler,
)


@dataclass(frozen=True, slots=True)
class ClaimedProtectionCandidate:
    candidate: ProtectionReconciliationCandidate
    upload_id: UUID
    claim_owner: str
    claim_revision: int


class ProtectionReconciliationStore(Protocol):
    async def claim_due(
        self, *, owner: str, limit: int, lease_seconds: int
    ) -> tuple[ClaimedProtectionCandidate, ...]: ...

    async def apply_decisions(
        self,
        claims: Sequence[ClaimedProtectionCandidate],
        decisions: Sequence[ProtectionReconciliationDecision],
        *,
        next_check_at: datetime,
    ) -> None: ...

    async def claim_cleanup(
        self, *, owner: str, limit: int, lease_seconds: int
    ) -> tuple[ClaimedProtectionCandidate, ...]: ...

    async def complete_cleanup(self, claim: ClaimedProtectionCandidate) -> None: ...


class ProtectionReconciliationService:
    """Make revoked versions unavailable before retryable derivative cleanup."""

    def __init__(
        self,
        *,
        store: ProtectionReconciliationStore,
        provider: PurviewRmsRevocationReconciler,
        index: DocumentIndex,
        artifacts: DocumentArtifactStore,
        owner: str,
        batch_size: int = 100,
        lease_seconds: int = 120,
        clock: Callable[[], datetime],
        next_check: Callable[[datetime], datetime],
    ) -> None:
        if not owner or len(owner) > 256:
            raise ValueError("protection reconciliation owner MUST be bounded")
        if not 1 <= batch_size <= 1000:
            raise ValueError("protection reconciliation batch MUST be in [1, 1000]")
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("protection reconciliation lease MUST be in [3, 3600]")
        self._store = store
        self._provider = provider
        self._index = index
        self._artifacts = artifacts
        self._owner = owner
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._clock = clock
        self._next_check = next_check

    async def reconcile_once(self) -> int:
        claims = await self._store.claim_due(
            owner=self._owner,
            limit=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        if claims:
            decisions = await self._provider.reconcile(tuple(claim.candidate for claim in claims))
            now = self._clock()
            await self._store.apply_decisions(
                claims,
                decisions,
                next_check_at=self._next_check(now),
            )
        cleanup = await self._store.claim_cleanup(
            owner=self._owner,
            limit=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        for claim in cleanup:
            candidate = claim.candidate
            await self._index.delete(candidate.document_id, candidate.version_id)
            await self._artifacts.delete(candidate.document_id, candidate.version_id)
            await self._store.complete_cleanup(claim)
        return len(claims) + len(cleanup)
