"""Durable-store failure behavior for the safeguard lifecycle preparation phase.

Preparation is the phase that has to fail closed: it reserves idempotency,
appends the pre-effect audit intent, and acquires the target fence, all inside
the held logical-target lock. Every store answer below - a conflict, a
re-delivered reservation, an unresolved prior generation, a lost acquisition
race, or an ownership probe that cannot be evaluated - MUST stop the dispatch
before the provider is ever called.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

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
    IdempotencyReservationTransitionReceipt,
    ReservationEvidenceKind,
    ReservationMatch,
    ReservationState,
)
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.core.executor.post_release_closure_plan import PostReleaseClosurePlan
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStoreReceipt
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchEvidenceReadback,
    SafeguardDispatchTransitionReceipt,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardLifecycleCoordinator,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.target_dispatch_fence import TargetDispatchFenceRecord
from fdai.core.executor.target_dispatch_fence_store import TargetDispatchFenceReadback
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryAuditIntentStore,
    InMemoryIdempotencyReservationStore,
    InMemoryPostReleaseClosureStore,
    InMemorySafeguardDispatchEvidenceStore,
    InMemoryTargetDispatchFenceStore,
)
from fdai.shared.providers.resource_lock import (
    HeldResourceLock,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseState,
)
from fdai.shared.providers.testing import InMemoryStateStore, RecordingDirectApiExecutor

from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.executor.test_safeguard_lifecycle_coordination_guards import (
    _MissingReleaseReceiptLock,
)

_NOW = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40
_OTHER_TARGET = "resource:example/rg/vm2"
_FOREIGN_INTENT_DIGEST = "sha256:" + "e" * 64


class _AdvancingClock:
    def __init__(self) -> None:
        self.current = _NOW

    def __call__(self) -> datetime:
        observed = self.current
        self.current += timedelta(milliseconds=1)
        return observed


class _RecordingAcquisitionLock(ResourceLockManager):
    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        super().__init__(clock=clock)
        self.handles: list[HeldResourceLock] = []

    @asynccontextmanager
    async def acquire_evidenced(
        self, request: ResourceLockAcquisitionRequest
    ) -> AsyncIterator[HeldResourceLock]:
        for prior in self.handles:
            assert prior.release_receipt is not None
            assert prior.release_receipt.state is ResourceLockReleaseState.RELEASED
        async with super().acquire_evidenced(request) as held:
            self.handles.append(held)
            yield held


class _RecoveryReleaseFailureLock(_RecordingAcquisitionLock):
    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        super().__init__(clock=clock)
        self.release_error: BaseException | None = None

    @asynccontextmanager
    async def acquire_evidenced(
        self, request: ResourceLockAcquisitionRequest
    ) -> AsyncIterator[HeldResourceLock]:
        try:
            async with super().acquire_evidenced(request) as held:
                yield held
        finally:
            if self.release_error is not None:
                raise self.release_error


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


class _FailFirstAuditIntentStore(InMemoryAuditIntentStore):
    """Leave one pre-dispatch reservation behind, then admit its recovery."""

    def __init__(self) -> None:
        super().__init__()
        self._failed = False

    async def append_and_readback(self, intent: PreEffectAuditIntent) -> AuditIntentAppendResult:
        result = await super().append_and_readback(intent)
        if self._failed:
            return result
        self._failed = True
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


class _PersistThenRaiseClosureStore(InMemoryPostReleaseClosureStore):
    """Commit the closure but lose the first write response."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.write_attempts = 0

    async def write(self, plan: PostReleaseClosurePlan) -> PostReleaseClosureStoreReceipt:
        self.write_attempts += 1
        receipt = await super().write(plan)
        if self.write_attempts == 1:
            raise RuntimeError("closure response was lost")
        return receipt


class _FailTwiceClosureStore(InMemoryPostReleaseClosureStore):
    """Fail initial closure and its retry, then permit restart recovery."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.write_attempts = 0

    async def write(self, plan: PostReleaseClosurePlan) -> PostReleaseClosureStoreReceipt:
        self.write_attempts += 1
        if self.write_attempts <= 2:
            raise RuntimeError("closure transaction was interrupted")
        return await super().write(plan)


class _BlockingFirstClosureStore(InMemoryPostReleaseClosureStore):
    """Hold the first post-release transaction open for race regression tests."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.started = asyncio.Event()
        self.allow_write = asyncio.Event()
        self._blocked = False

    async def write(self, plan: PostReleaseClosurePlan) -> PostReleaseClosureStoreReceipt:
        if not self._blocked:
            self._blocked = True
            self.started.set()
            await self.allow_write.wait()
        return await super().write(plan)


class _CrashDuringPreDispatchRecoveryStore(InMemoryIdempotencyReservationStore):
    """Persist two recovery checkpoints while losing each write response."""

    def __init__(self) -> None:
        super().__init__()
        self._lost_in_flight = False
        self._lost_terminal = False

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_prior_revision: int,
        record: IdempotencyReservationRecord,
    ) -> IdempotencyReservationTransitionReceipt:
        receipt = await super().compare_and_transition(
            prior_record_digest=prior_record_digest,
            expected_prior_revision=expected_prior_revision,
            record=record,
        )
        if record.state is ReservationState.IN_FLIGHT and not self._lost_in_flight:
            self._lost_in_flight = True
            raise RuntimeError("simulated loss after in-flight reservation")
        if (
            record.state is ReservationState.TERMINAL
            and record.evidence_kind is ReservationEvidenceKind.IRREVOCABLE_NON_ACCEPTANCE
            and not self._lost_terminal
        ):
            self._lost_terminal = True
            raise RuntimeError("simulated loss after no-dispatch terminal reservation")
        return receipt


class _CrashAfterEvidenceStore(InMemorySafeguardDispatchEvidenceStore):
    """Persist one checkpoint, then simulate process loss before returning."""

    def __init__(self, state: SafeguardDispatchEvidenceState) -> None:
        super().__init__()
        self._state = state
        self._failed = False

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: SafeguardDispatchEvidenceRecord,
        **kwargs: object,
    ) -> SafeguardDispatchTransitionReceipt:
        receipt = await super().compare_and_transition(
            prior_record_digest=prior_record_digest,
            expected_revision=expected_revision,
            record=record,
            **kwargs,  # type: ignore[arg-type]
        )
        if record.state is self._state and not self._failed:
            self._failed = True
            raise RuntimeError("simulated process loss after evidence persistence")
        return receipt


class _DelayedRecoveryEvidenceStore(InMemorySafeguardDispatchEvidenceStore):
    """Expose a later authoritative persistence time during restart recovery."""

    async def read_with_timestamp(
        self,
        target_digest: str,
        generation: int,
    ) -> SafeguardDispatchEvidenceReadback | None:
        readback = await super().read_with_timestamp(target_digest, generation)
        if readback is None:
            return None
        return SafeguardDispatchEvidenceReadback(
            record=readback.record,
            recorded_at=_NOW + timedelta(seconds=20),
        )


class _DelayedRecoveryFenceStore(InMemoryTargetDispatchFenceStore):
    """Expose the authoritative fence persistence time during recovery."""

    async def read_with_timestamp(
        self,
        target_digest: str,
    ) -> TargetDispatchFenceReadback | None:
        readback = await super().read_with_timestamp(target_digest)
        if readback is None:
            return None
        return TargetDispatchFenceReadback(
            record=readback.record,
            recorded_at=_NOW + timedelta(seconds=30),
        )


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
        evidence_store: InMemorySafeguardDispatchEvidenceStore | None = None,
        closure_store_factory: Callable[..., InMemoryPostReleaseClosureStore] | None = None,
        lock: ResourceLockManager | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        lifecycle_clock = clock or (lambda: _NOW)
        self.audit = InMemoryStateStore()
        self.lock = lock or ResourceLockManager(
            clock=lifecycle_clock,
            acquisition_id_factory=lambda: "test",
        )
        self.reservations = reservation_store or InMemoryIdempotencyReservationStore()
        self.fences = fence_store or InMemoryTargetDispatchFenceStore()
        factory = closure_store_factory or InMemoryPostReleaseClosureStore
        self.closure = factory(
            reservation_store=self.reservations,
            fence_store=self.fences,
        )
        self.adapter = RecordingDirectApiExecutor()
        self.coordinator = SafeguardLifecycleCoordinator(
            resource_lock=self.lock,
            reservation_store=self.reservations,
            audit_intent_store=audit_intent_store or InMemoryAuditIntentStore(),
            fence_store=self.fences,
            evidence_store=evidence_store or InMemorySafeguardDispatchEvidenceStore(),
            closure_store=self.closure,
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
            clock=lifecycle_clock,
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

    @pytest.mark.parametrize("advancing_clock", [False, True])
    async def test_same_operation_recovers_pre_dispatch_reservation_under_new_lock(
        self, advancing_clock: bool
    ) -> None:
        harness = _Harness(
            audit_intent_store=_FailFirstAuditIntentStore(),
            clock=_AdvancingClock() if advancing_clock else None,
        )
        action = _direct_action()

        first = await harness.executor().execute(action=action)
        replay = await harness.executor().execute(action=action)

        assert first.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert replay.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert len(harness.adapter.records) == 1

    async def test_recovery_releases_before_one_fresh_acquisition(self) -> None:
        clock = _AdvancingClock()
        lock = _RecordingAcquisitionLock(clock=clock)
        harness = _Harness(audit_intent_store=_FailFirstAuditIntentStore(), clock=clock, lock=lock)
        action = _direct_action()

        await harness.executor().execute(action=action)
        replay = await harness.executor().execute(action=action)

        assert replay.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert len(lock.handles) == 3
        recovered_lock, dispatch_lock = lock.handles[1:]
        release = recovered_lock.release_receipt
        assert release is not None
        assert dispatch_lock.acquisition_receipt.acquired_at > release.recorded_at
        assert dispatch_lock.acquisition_receipt.attempt == 2
        reservation = await harness.reservations.read(action.idempotency_key)
        assert reservation is not None
        assert reservation.identity.acquisition_receipt == dispatch_lock.acquisition_receipt
        assert len(harness.adapter.records) == 1

    async def test_recovery_reacquisition_is_bounded_when_lock_clock_lags(self) -> None:
        clock = _AdvancingClock()
        lock = _RecordingAcquisitionLock(clock=lambda: _NOW)
        harness = _Harness(audit_intent_store=_FailFirstAuditIntentStore(), clock=clock, lock=lock)
        action = _direct_action()

        await harness.executor().execute(action=action)
        replay = await harness.executor().execute(action=action)

        assert replay.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "requires a later evidenced acquisition" in (replay.reason or "")
        assert len(lock.handles) == 3
        assert harness.adapter.records == ()
        reservation = await harness.reservations.read(action.idempotency_key)
        assert reservation is not None
        assert reservation.state is ReservationState.ABANDONED

    async def test_recovery_refuses_reacquisition_without_exact_release_evidence(self) -> None:
        clock = _AdvancingClock()
        harness = _Harness(
            audit_intent_store=_FailFirstAuditIntentStore(),
            clock=clock,
            lock=_MissingReleaseReceiptLock(clock=clock),
        )
        action = _direct_action()

        await harness.executor().execute(action=action)
        replay = await harness.executor().execute(action=action)

        assert replay.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "recovery lock release is unproven" in (replay.reason or "")
        assert harness.adapter.records == ()

    @pytest.mark.parametrize("cancel_release", [False, True])
    async def test_recovery_does_not_reacquire_after_release_failure(
        self, cancel_release: bool
    ) -> None:
        clock = _AdvancingClock()
        lock = _RecoveryReleaseFailureLock(clock=clock)
        harness = _Harness(audit_intent_store=_FailFirstAuditIntentStore(), clock=clock, lock=lock)
        action = _direct_action()
        await harness.executor().execute(action=action)
        lock.release_error = (
            asyncio.CancelledError() if cancel_release else RuntimeError("release failed")
        )

        if cancel_release:
            with pytest.raises(asyncio.CancelledError):
                await harness.executor().execute(action=action)
        else:
            replay = await harness.executor().execute(action=action)
            assert replay.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT

        assert len(lock.handles) == 2
        assert harness.adapter.records == ()

    async def test_terminal_no_dispatch_checkpoint_reopens_after_response_loss(self) -> None:
        current_time = [_NOW]
        harness = _Harness(
            reservation_store=_CrashDuringPreDispatchRecoveryStore(),
            clock=lambda: current_time[0],
        )
        action = _direct_action()

        first = await harness.executor().execute(action=action)
        second = await harness.executor().execute(action=action)
        current_time[0] += timedelta(seconds=1)
        third = await harness.executor().execute(action=action)

        assert first.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert second.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert third.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert len(harness.adapter.records) == 1


class TestAuditIntentPhase:
    async def test_a_foreign_pre_effect_intent_denies_dispatch(self) -> None:
        harness = _Harness(audit_intent_store=_ForeignAuditIntentStore())

        result = await harness.executor().execute(action=_direct_action())

        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "audit intent conflicts with durable state" in (result.reason or "")
        assert harness.adapter.records == ()


class TestTargetFencePhase:
    @pytest.mark.parametrize(
        ("crash_state", "provider_calls"),
        (
            (SafeguardDispatchEvidenceState.DISPATCH_STARTED, 0),
            (SafeguardDispatchEvidenceState.DISPATCH_OBSERVED, 1),
        ),
    )
    async def test_in_flight_restart_recovers_to_quarantine_without_redispatch(
        self,
        crash_state: SafeguardDispatchEvidenceState,
        provider_calls: int,
    ) -> None:
        current_time = [_NOW]
        harness = _Harness(
            evidence_store=_CrashAfterEvidenceStore(crash_state),
            clock=lambda: current_time[0],
        )
        action = _direct_action()

        first = await harness.executor().execute(action=action)
        current_time[0] += timedelta(minutes=6)
        replay = await harness.executor().execute(action=action)

        assert first.outcome is not DirectApiExecutionOutcome.DISPATCHED
        assert replay.outcome is DirectApiExecutionOutcome.FAILED
        assert replay.reason == "prior release-pending lifecycle recovered into quarantine"
        assert len(harness.adapter.records) == provider_calls
        assert harness.closure.audit_entries[0]["outcome"] == "quarantined"

    async def test_release_pending_restart_recovers_to_quarantine_without_redispatch(
        self,
    ) -> None:
        current_time = [_NOW]
        harness = _Harness(
            closure_store_factory=_FailTwiceClosureStore,
            clock=lambda: current_time[0],
        )
        action = _direct_action()

        first = await harness.executor().execute(action=action)
        current_time[0] += timedelta(minutes=6)
        replay = await harness.executor().execute(action=action)

        assert first.outcome is DirectApiExecutionOutcome.FAILED
        assert replay.outcome is DirectApiExecutionOutcome.FAILED
        assert replay.reason == "prior release-pending lifecycle recovered into quarantine"
        assert len(harness.adapter.records) == 1
        assert harness.closure.audit_entries[0]["outcome"] == "quarantined"

    async def test_restart_recovery_uses_authoritative_readback_times(self) -> None:
        current_time = [_NOW]
        harness = _Harness(
            fence_store=_DelayedRecoveryFenceStore(),
            evidence_store=_DelayedRecoveryEvidenceStore(),
            closure_store_factory=_FailTwiceClosureStore,
            clock=lambda: current_time[0],
        )
        action = _direct_action()

        await harness.executor().execute(action=action)
        current_time[0] += timedelta(minutes=6)
        replay = await harness.executor().execute(action=action)

        assert replay.outcome is DirectApiExecutionOutcome.FAILED
        closure_record = next(iter(harness.closure._records.values()))
        assert closure_record.closed_at == current_time[0]

    async def test_fresh_release_pending_replay_cannot_preempt_normal_closure(self) -> None:
        harness = _Harness(closure_store_factory=_BlockingFirstClosureStore)
        assert isinstance(harness.closure, _BlockingFirstClosureStore)
        action = _direct_action()
        first_task = asyncio.create_task(harness.executor().execute(action=action))
        await harness.closure.started.wait()

        try:
            replay = await harness.executor().execute(action=action)

            assert replay.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
            assert "reservation already exists" in (replay.reason or "")
            assert harness.closure.audit_entries == []
        finally:
            harness.closure.allow_write.set()
        first = await first_task
        assert first.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert harness.closure.audit_entries[0]["outcome"] == "resolved"

    @pytest.mark.parametrize("advancing_clock", [False, True])
    async def test_reserved_attempt_recovers_after_foreign_fence_resolves(
        self, advancing_clock: bool
    ) -> None:
        current_time = [_NOW]
        harness = _Harness(
            closure_store_factory=_BlockingFirstClosureStore,
            clock=_AdvancingClock() if advancing_clock else lambda: current_time[0],
        )
        assert isinstance(harness.closure, _BlockingFirstClosureStore)
        first_action = _direct_action()
        waiting_action = _direct_action(
            action_id="00000000-0000-0000-0000-000000000099",
            idempotency_key="waiting-operation",
        )
        first_task = asyncio.create_task(harness.executor().execute(action=first_action))
        await harness.closure.started.wait()

        try:
            blocked = await harness.executor().execute(action=waiting_action)
        finally:
            harness.closure.allow_write.set()
        first = await first_task
        current_time[0] += timedelta(seconds=1)
        replay = await harness.executor().execute(action=waiting_action)

        assert blocked.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert first.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert replay.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert len(harness.adapter.records) == 2

    async def test_committed_closure_is_recovered_after_response_loss(self) -> None:
        harness = _Harness(closure_store_factory=_PersistThenRaiseClosureStore)

        result = await harness.executor().execute(action=_direct_action())

        assert result.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert result.safeguard_bundle_digest is not None
        assert len(harness.adapter.records) == 1

    async def test_an_unresolved_prior_generation_blocks_the_next_dispatch(self) -> None:
        harness = _Harness(closure_store_factory=_BrokenClosureStore)
        first = await harness.executor().execute(action=_direct_action())

        assert first.outcome is DirectApiExecutionOutcome.FAILED
        assert first.safeguard_bundle_digest is not None
        assert first.reason == "post-release safeguard closure failed: RuntimeError"

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
        first = await harness.executor().execute(action=_direct_action())

        assert first.outcome is DirectApiExecutionOutcome.FAILED
        assert first.safeguard_bundle_digest is not None
        assert first.reason == "post-release safeguard closure failed: RuntimeError"

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
        first = await harness.executor().execute(action=_direct_action())

        assert first.outcome is DirectApiExecutionOutcome.FAILED
        assert first.safeguard_bundle_digest is not None
        assert first.reason == "post-release safeguard closure failed: RuntimeError"

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
