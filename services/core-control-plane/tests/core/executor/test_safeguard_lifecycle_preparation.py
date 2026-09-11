"""Durable-store failure behavior for the safeguard lifecycle preparation phase.

Preparation is the phase that has to fail closed: it reserves idempotency,
appends the pre-effect audit intent, and acquires the target fence, all inside
the held logical-target lock. Every store answer below - a conflict, a
re-delivered reservation, an unresolved prior generation, a lost acquisition
race, or an ownership probe that cannot be evaluated - MUST stop the dispatch
before the provider is ever called.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.executor import (
    DirectApiExecutionOutcome,
    DirectApiShadowExecutor,
    ResourceLockManager,
)
from fdai.core.executor.audit_intent import (
    AuditIntentAppendDecision,
    AuditIntentAppendResult,
    PreEffectAuditIntent,
)
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationRecord,
    IdempotencyReservationReserveResult,
    ReservationMatch,
)
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.core.executor.post_release_closure_plan import PostReleaseClosurePlan
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStoreReceipt
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardLifecycleCoordinator,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.target_dispatch_fence import TargetDispatchFenceRecord
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryAuditIntentStore,
    InMemoryIdempotencyReservationStore,
    InMemoryPostReleaseClosureStore,
    InMemorySafeguardDispatchEvidenceStore,
    InMemoryTargetDispatchFenceStore,
)
from fdai.shared.providers.testing import InMemoryStateStore, RecordingDirectApiExecutor

from tests.core.executor.test_direct_api_executor import _action as _direct_action

_NOW = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40
_OTHER_TARGET = "resource:example/rg/vm2"
_FOREIGN_INTENT_DIGEST = "sha256:" + "e" * 64


class _RedeliveredReservationStore(InMemoryIdempotencyReservationStore):
    """Report the identical attempt as an already-landed durable insert."""

    async def reserve(
        self,
        record: IdempotencyReservationRecord,
    ) -> IdempotencyReservationReserveResult:
        result = await super().reserve(record)
        if result.match is not ReservationMatch.ACQUIRED:
            return result
        return replace(
            result,
            match=ReservationMatch.DUPLICATE_SAME,
            transition_receipt=None,
        )


class _ForeignAuditIntentStore(InMemoryAuditIntentStore):
    """Report that durable audit state already holds a different intent."""

    async def append_and_readback(self, intent: PreEffectAuditIntent) -> AuditIntentAppendResult:
        result = await super().append_and_readback(intent)
        return replace(
            result,
            decision=AuditIntentAppendDecision.CONFLICT,
            observed_intent_digest=_FOREIGN_INTENT_DIGEST,
            receipt=None,
        )


class _RacingFenceStore(InMemoryTargetDispatchFenceStore):
    """Hide the current generation from the pre-read but not from the insert."""

    def __init__(self) -> None:
        super().__init__()
        self.hide_reads = False

    async def read(self, target_digest: str) -> TargetDispatchFenceRecord | None:
        if self.hide_reads:
            return None
        return await super().read(target_digest)


class _UnresolvableFenceStore(InMemoryTargetDispatchFenceStore):
    """Refuse the fence transition so no-dispatch cancellation cannot close."""

    async def compare_and_transition(self, **kwargs: object) -> object:
        raise RuntimeError("target fence transition is unavailable")


class _BrokenClosureStore(InMemoryPostReleaseClosureStore):
    """Fail the atomic closure so the target fence stays release-pending."""

    async def write(self, plan: PostReleaseClosurePlan) -> PostReleaseClosureStoreReceipt:
        raise RuntimeError("closure transaction is unavailable")


class _UnassessableLock(ResourceLockManager):
    """Hold the lock but refuse to prove live ownership."""

    async def _owns_acquisition(
        self,
        lock_key: str,
        entry: object,
        acquisition_id: str,
    ) -> bool:
        del lock_key, entry, acquisition_id
        raise RuntimeError("lock ownership is unprovable")


class _Harness:
    """One coordinator plus the stores it was explicitly composed from."""

    def __init__(
        self,
        *,
        reservation_store: InMemoryIdempotencyReservationStore | None = None,
        audit_intent_store: InMemoryAuditIntentStore | None = None,
        fence_store: InMemoryTargetDispatchFenceStore | None = None,
        closure_store_factory: Callable[..., InMemoryPostReleaseClosureStore] | None = None,
        lock: ResourceLockManager | None = None,
    ) -> None:
        self.audit = InMemoryStateStore()
        self.lock = lock or ResourceLockManager(
            clock=lambda: _NOW,
            acquisition_id_factory=lambda: "test",
        )
        self.reservations = reservation_store or InMemoryIdempotencyReservationStore()
        self.fences = fence_store or InMemoryTargetDispatchFenceStore()
        factory = closure_store_factory or InMemoryPostReleaseClosureStore
        self.adapter = RecordingDirectApiExecutor()
        self.coordinator = SafeguardLifecycleCoordinator(
            resource_lock=self.lock,
            reservation_store=self.reservations,
            audit_intent_store=audit_intent_store or InMemoryAuditIntentStore(),
            fence_store=self.fences,
            evidence_store=InMemorySafeguardDispatchEvidenceStore(),
            closure_store=factory(
                reservation_store=self.reservations,
                fence_store=self.fences,
            ),
            denial_audit_store=self.audit,
            continuity_policy=EffectSinkContinuityPolicy.create(
                sink_id="test-dispatch",
                sink_version="1.0.0",
                strategy=OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION,
                cancellation_supported=True,
                durable_unknown_quarantine=True,
                reconciliation_supported=True,
            ),
            config=SafeguardLifecycleCoordinatorConfig(
                source_revision=_SOURCE_REVISION,
                producer_id="fdai.core.executor",
                producer_version="1.0.0",
                actor="fdai.core.executor",
                expected_lock_verifier_id="fdai-in-memory-lock-readback",
                expected_lock_verifier_version="1.0.0",
                expected_lock_trust_anchor_id="fdai:local-test-only",
            ),
            clock=lambda: _NOW,
        )

    def executor(self) -> DirectApiShadowExecutor:
        """Return a fresh executor, modelling one process instance."""

        return DirectApiShadowExecutor(
            executor=self.adapter,
            audit_store=self.audit,
            resource_lock=self.lock,
            safeguard_coordinator=self.coordinator,
        )


class TestReservationPhase:
    async def test_a_conflicting_reservation_for_another_action_denies_dispatch(self) -> None:
        harness = _Harness()
        await harness.executor().execute(action=_direct_action())

        # A restarted process re-uses the stable idempotency key for a
        # different operation. The durable reservation cannot cover both,
        # so nothing may be dispatched.
        result = await harness.executor().execute(
            action=_direct_action(
                action_id="00000000-0000-0000-0000-0000000000ff",
                target=_OTHER_TARGET,
            )
        )

        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "conflicts with a different action" in (result.reason or "")
        assert len(harness.adapter.records) == 1

    async def test_a_redelivered_reservation_never_dispatches_twice(self) -> None:
        harness = _Harness(reservation_store=_RedeliveredReservationStore())

        result = await harness.executor().execute(action=_direct_action())

        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "reservation already exists" in (result.reason or "")
        assert harness.adapter.records == ()

    async def test_a_redelivered_reservation_without_a_fence_claims_no_bundle(self) -> None:
        harness = _Harness(reservation_store=_RedeliveredReservationStore())

        result = await harness.executor().execute(action=_direct_action())

        # No prior generation exists for the target, so the duplicate has no
        # retained safeguard bundle it may claim as its own evidence.
        assert result.safeguard_bundle_digest is None


class TestAuditIntentPhase:
    async def test_a_foreign_pre_effect_intent_denies_dispatch(self) -> None:
        harness = _Harness(audit_intent_store=_ForeignAuditIntentStore())

        result = await harness.executor().execute(action=_direct_action())

        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "audit intent conflicts with durable state" in (result.reason or "")
        assert harness.adapter.records == ()


class TestTargetFencePhase:
    async def test_an_unresolved_prior_generation_blocks_the_next_dispatch(self) -> None:
        harness = _Harness(closure_store_factory=_BrokenClosureStore)
        with pytest.raises(RuntimeError, match="closure transaction is unavailable"):
            await harness.executor().execute(action=_direct_action())

        # The first dispatch reached the provider but never closed, so the
        # target generation is still open and a second action on the same
        # target MUST NOT be dispatched.
        result = await harness.executor().execute(
            action=_direct_action(
                action_id="00000000-0000-0000-0000-0000000000fe",
                idempotency_key="second-idem",
            )
        )

        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "target dispatch fence is unresolved" in (result.reason or "")
        assert len(harness.adapter.records) == 1

    async def test_a_blocked_generation_never_inherits_another_actions_bundle(self) -> None:
        harness = _Harness(closure_store_factory=_BrokenClosureStore)
        with pytest.raises(RuntimeError, match="closure transaction is unavailable"):
            await harness.executor().execute(action=_direct_action())

        blocked = await harness.executor().execute(
            action=_direct_action(
                action_id="00000000-0000-0000-0000-0000000000fd",
                idempotency_key="third-idem",
            )
        )

        # The retained bundle belongs to the first action, so the blocked
        # second action MUST NOT inherit it as its own safeguard evidence.
        assert blocked.safeguard_bundle_digest is None
        assert len(harness.adapter.records) == 1

    async def test_a_lost_generation_race_blocks_the_dispatch(self) -> None:
        fences = _RacingFenceStore()
        harness = _Harness(fence_store=fences, closure_store_factory=_BrokenClosureStore)
        with pytest.raises(RuntimeError, match="closure transaction is unavailable"):
            await harness.executor().execute(action=_direct_action())

        # The pre-read sees a free target, but a concurrent generation is
        # already durable, so the atomic insert has to lose the race.
        fences.hide_reads = True
        result = await harness.executor().execute(
            action=_direct_action(
                action_id="00000000-0000-0000-0000-0000000000fc",
                idempotency_key="fourth-idem",
            )
        )

        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "target dispatch fence blocked" in (result.reason or "")
        assert len(harness.adapter.records) == 1


class TestOwnershipProofPhase:
    async def test_an_unprovable_lock_cancels_before_dispatch(self) -> None:
        harness = _Harness(
            lock=_UnassessableLock(clock=lambda: _NOW, acquisition_id_factory=lambda: "test"),
        )

        result = await harness.executor().execute(action=_direct_action())

        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "failed before terminal evidence" in (result.reason or "")
        assert harness.adapter.records == ()

    async def test_an_unresolvable_fence_still_fails_closed(self) -> None:
        harness = _Harness(
            fence_store=_UnresolvableFenceStore(),
            lock=_UnassessableLock(clock=lambda: _NOW, acquisition_id_factory=lambda: "test"),
        )

        result = await harness.executor().execute(action=_direct_action())

        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "failed before terminal evidence" in (result.reason or "")
        assert harness.adapter.records == ()
