"""Explicit in-memory providers for safeguard lifecycle tests and shadow runs."""

from __future__ import annotations

import asyncio

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.audit_intent import (
    AuditIntentAppendDecision,
    AuditIntentAppendReceipt,
    AuditIntentAppendResult,
    PreEffectAuditIntent,
)
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationRecord,
    IdempotencyReservationReserveResult,
    IdempotencyReservationTransitionReceipt,
    ReservationMatch,
    ReservationState,
    classify_reservation,
)
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureRecord,
    audit_closure_mapping,
    closure_outbox_mapping,
)
from fdai.core.executor.post_release_closure_plan import PostReleaseClosurePlan
from fdai.core.executor.post_release_closure_store import (
    PostReleaseClosureStoreReceipt,
    PostReleaseClosureWriteDecision,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchPersistenceDecision,
    SafeguardDispatchPersistenceResult,
    SafeguardDispatchTransitionReceipt,
    classify_safeguard_dispatch_evidence,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceTransitionReceipt,
)
from fdai.core.executor.target_dispatch_fence_store import (
    TargetDispatchFenceAcquireDecision,
    TargetDispatchFenceAcquireResult,
    classify_target_fence,
)
from fdai.shared.providers.resource_lock import LiveLockOwnershipAssessment


def _digest(domain: str, value: str) -> str:
    return content_digest({"domain": domain, "value": value})


class InMemoryIdempotencyReservationStore:
    """Process-local reservation provider that is never production eligible."""

    production_eligible = False

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyReservationRecord] = {}
        self._lock = asyncio.Lock()

    def seed(self, record: IdempotencyReservationRecord) -> None:
        """Install one validated record before a focused lifecycle test."""

        self._records[record.identity.idempotency_key] = record

    async def reserve(
        self,
        record: IdempotencyReservationRecord,
    ) -> IdempotencyReservationReserveResult:
        if record.state is not ReservationState.RESERVED or record.revision != 1:
            raise ValueError("in-memory reservation requires revision-one reserved state")
        async with self._lock:
            existing = self._records.get(record.identity.idempotency_key)
            if existing is not None:
                return IdempotencyReservationReserveResult(
                    candidate_identity=record.identity,
                    match=classify_reservation(existing, record.identity),
                    observed_record=existing,
                    transition_receipt=None,
                )
            self._records[record.identity.idempotency_key] = record
            receipt = IdempotencyReservationTransitionReceipt.create(
                prior_record=None,
                record=record,
                expected_prior_revision=0,
                store_receipt_digest=_digest("memory-reservation", record.record_digest),
                recorded_at=record.state_changed_at,
            )
            return IdempotencyReservationReserveResult(
                candidate_identity=record.identity,
                match=ReservationMatch.ACQUIRED,
                observed_record=record,
                transition_receipt=receipt,
            )

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_prior_revision: int,
        record: IdempotencyReservationRecord,
    ) -> IdempotencyReservationTransitionReceipt:
        async with self._lock:
            key = record.identity.idempotency_key
            prior = self._records.get(key)
            if (
                prior is None
                or prior.record_digest != prior_record_digest
                or prior.revision != expected_prior_revision
            ):
                raise RuntimeError("in-memory reservation predecessor changed")
            self._records[key] = record
            return IdempotencyReservationTransitionReceipt.create(
                prior_record=prior,
                record=record,
                expected_prior_revision=expected_prior_revision,
                store_receipt_digest=_digest("memory-reservation-cas", record.record_digest),
                recorded_at=record.state_changed_at,
            )

    async def read(self, idempotency_key: str) -> IdempotencyReservationRecord | None:
        return self._records.get(idempotency_key)


class InMemoryAuditIntentStore:
    """Process-local exact append/readback provider for test composition."""

    production_eligible = False

    def __init__(self) -> None:
        self._intents: dict[str, PreEffectAuditIntent] = {}
        self._receipts: dict[str, AuditIntentAppendReceipt] = {}
        self._lock = asyncio.Lock()

    async def append_and_readback(
        self,
        intent: PreEffectAuditIntent,
    ) -> AuditIntentAppendResult:
        key = intent.reservation_receipt.record.identity.identity_digest
        async with self._lock:
            existing = self._intents.get(key)
            if existing is not None and existing != intent:
                return AuditIntentAppendResult(
                    candidate_intent_digest=intent.intent_digest,
                    decision=AuditIntentAppendDecision.CONFLICT,
                    observed_intent_digest=existing.intent_digest,
                    receipt=None,
                )
            if existing is not None:
                receipt = self._receipts[key]
                return AuditIntentAppendResult(
                    candidate_intent_digest=intent.intent_digest,
                    decision=AuditIntentAppendDecision.DUPLICATE_SAME,
                    observed_intent_digest=intent.intent_digest,
                    receipt=receipt,
                )
            receipt = AuditIntentAppendReceipt.create(
                intent=intent,
                persisted_intent_digest=intent.intent_digest,
                store_receipt_digest=_digest("memory-audit-intent", intent.intent_digest),
                persisted_at=intent.created_at,
                read_back_at=intent.created_at,
            )
            self._intents[key] = intent
            self._receipts[key] = receipt
            return AuditIntentAppendResult(
                candidate_intent_digest=intent.intent_digest,
                decision=AuditIntentAppendDecision.APPENDED,
                observed_intent_digest=intent.intent_digest,
                receipt=receipt,
            )


class InMemoryTargetDispatchFenceStore:
    """Process-local exact-generation target fence provider."""

    production_eligible = False

    def __init__(self) -> None:
        self._records: dict[str, TargetDispatchFenceRecord] = {}
        self._lock = asyncio.Lock()

    async def acquire_generation(
        self,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceAcquireResult:
        async with self._lock:
            key = record.identity.target_digest
            existing = self._records.get(key)
            if existing is not None:
                return TargetDispatchFenceAcquireResult(
                    candidate_identity=record.identity,
                    decision=classify_target_fence(existing, record.identity),
                    observed_record=existing,
                    transition_receipt=None,
                )
            self._records[key] = record
            receipt = TargetDispatchFenceTransitionReceipt.create(
                prior_record=None,
                record=record,
                store_receipt_digest=_digest("memory-target-fence", record.record_digest),
                recorded_at=record.state_changed_at,
            )
            return TargetDispatchFenceAcquireResult(
                candidate_identity=record.identity,
                decision=TargetDispatchFenceAcquireDecision.ACQUIRED,
                observed_record=record,
                transition_receipt=receipt,
            )

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceTransitionReceipt:
        async with self._lock:
            key = record.identity.target_digest
            prior = self._records.get(key)
            if (
                prior is None
                or prior.record_digest != prior_record_digest
                or prior.revision != expected_revision
            ):
                raise RuntimeError("in-memory target fence predecessor changed")
            self._records[key] = record
            return TargetDispatchFenceTransitionReceipt.create(
                prior_record=prior,
                record=record,
                store_receipt_digest=_digest("memory-target-fence-cas", record.record_digest),
                recorded_at=record.state_changed_at,
            )

    async def read(self, target_digest: str) -> TargetDispatchFenceRecord | None:
        return self._records.get(target_digest)


class InMemorySafeguardDispatchEvidenceStore:
    """Process-local exact-bundle and dispatch checkpoint provider."""

    production_eligible = False

    def __init__(self) -> None:
        self._records: dict[tuple[str, int], SafeguardDispatchEvidenceRecord] = {}
        self._lock = asyncio.Lock()

    async def persist_bundle(
        self,
        record: SafeguardDispatchEvidenceRecord,
    ) -> SafeguardDispatchPersistenceResult:
        if record.state is not SafeguardDispatchEvidenceState.BUNDLE_PERSISTED:
            raise ValueError("in-memory evidence store requires bundle-persisted state")
        async with self._lock:
            key = (record.identity.target_digest, record.identity.target_fence_generation)
            existing = self._records.get(key)
            if existing is not None:
                return SafeguardDispatchPersistenceResult(
                    candidate_identity=record.identity,
                    decision=classify_safeguard_dispatch_evidence(existing, record.identity),
                    observed_record=existing,
                    transition_receipt=None,
                )
            self._records[key] = record
            receipt = SafeguardDispatchTransitionReceipt.create(
                prior_record=None,
                record=record,
                store_receipt_digest=_digest("memory-safeguard", record.record_digest),
                recorded_at=record.state_changed_at,
            )
            return SafeguardDispatchPersistenceResult(
                candidate_identity=record.identity,
                decision=SafeguardDispatchPersistenceDecision.PERSISTED,
                observed_record=record,
                transition_receipt=receipt,
            )

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: SafeguardDispatchEvidenceRecord,
        bundle_persistence_receipt: SafeguardDispatchTransitionReceipt | None = None,
        current_lock_assessment: LiveLockOwnershipAssessment | None = None,
    ) -> SafeguardDispatchTransitionReceipt:
        async with self._lock:
            key = (record.identity.target_digest, record.identity.target_fence_generation)
            prior = self._records.get(key)
            if (
                prior is None
                or prior.record_digest != prior_record_digest
                or prior.revision != expected_revision
            ):
                raise RuntimeError("in-memory safeguard predecessor changed")
            self._records[key] = record
            return SafeguardDispatchTransitionReceipt.create(
                prior_record=prior,
                record=record,
                bundle_persistence_receipt=bundle_persistence_receipt,
                current_lock_assessment=current_lock_assessment,
                store_receipt_digest=_digest("memory-safeguard-cas", record.record_digest),
                recorded_at=record.state_changed_at,
            )

    async def read(
        self,
        target_digest: str,
        generation: int,
    ) -> SafeguardDispatchEvidenceRecord | None:
        return self._records.get((target_digest, generation))


class InMemoryPostReleaseClosureStore:
    """Process-local closure transaction provider for explicit tests."""

    production_eligible = False

    def __init__(
        self,
        *,
        reservation_store: InMemoryIdempotencyReservationStore,
        fence_store: InMemoryTargetDispatchFenceStore,
    ) -> None:
        self._reservation_store = reservation_store
        self._fence_store = fence_store
        self._records: dict[str, PostReleaseClosureRecord] = {}
        self.audit_entries: list[dict[str, object]] = []
        self.outbox_events: list[dict[str, object]] = []
        self._lock = asyncio.Lock()

    async def write(
        self,
        plan: PostReleaseClosurePlan,
    ) -> PostReleaseClosureStoreReceipt:
        async with self._lock:
            key = plan.record.identity.closure_key
            existing = self._records.get(key)
            if existing is not None:
                if existing != plan.record:
                    raise RuntimeError("in-memory post-release closure conflicts")
                return PostReleaseClosureStoreReceipt.create(
                    decision=PostReleaseClosureWriteDecision.DUPLICATE_SAME,
                    record=existing,
                    persisted_at=existing.closed_at,
                    read_back_at=existing.closed_at,
                    store_receipt_digest=_digest(
                        "memory-post-release-duplicate",
                        existing.record_digest,
                    ),
                )
            reservation_key = plan.prior_reservation_record.identity.idempotency_key
            current_reservation = await self._reservation_store.read(reservation_key)
            current_fence = await self._fence_store.read(
                plan.prior_fence_record.identity.target_digest
            )
            if (
                current_reservation != plan.prior_reservation_record
                or current_fence != plan.prior_fence_record
            ):
                raise RuntimeError("in-memory post-release predecessor changed")
            self._reservation_store._records[reservation_key] = plan.reservation_record
            self._fence_store._records[plan.fence_record.identity.target_digest] = plan.fence_record
            self._records[key] = plan.record
            self.audit_entries.append(audit_closure_mapping(plan.record))
            self.outbox_events.append(closure_outbox_mapping(plan.record))
            return PostReleaseClosureStoreReceipt.create(
                decision=PostReleaseClosureWriteDecision.APPLIED,
                record=plan.record,
                persisted_at=plan.record.closed_at,
                read_back_at=plan.record.closed_at,
                store_receipt_digest=_digest(
                    "memory-post-release",
                    plan.record.record_digest,
                ),
            )

    async def read(self, closure_key: str) -> PostReleaseClosureRecord | None:
        return self._records.get(closure_key)


__all__ = [
    "InMemoryAuditIntentStore",
    "InMemoryIdempotencyReservationStore",
    "InMemoryPostReleaseClosureStore",
    "InMemorySafeguardDispatchEvidenceStore",
    "InMemoryTargetDispatchFenceStore",
]
