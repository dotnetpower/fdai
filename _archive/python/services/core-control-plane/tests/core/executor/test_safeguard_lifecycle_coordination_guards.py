"""Coordinator-level guards around one shared safeguard dispatch.

These cover the boundaries the per-path adapters cannot reach on their own:
the production composition check, a caller that hands over something other
than a real safeguard receipt, a non-positive attempt, a workflow commitment
that is reused across a restart, a cancellation raised inside the held lock,
and a lock release that cannot be proven after a completed dispatch.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.executor import (
    DirectApiShadowExecutor,
    ResourceLockManager,
)
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureOutcome,
    PostReleaseClosureRecord,
)
from fdai.core.executor.post_release_closure_plan import PostReleaseClosurePlan
from fdai.core.executor.post_release_closure_store import (
    PostReleaseClosureStore,
    PostReleaseClosureStoreReceipt,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_store import SafeguardDispatchTransitionReceipt
from fdai.core.executor.safeguard_evidence_lifecycle import DispatchBoundaryGuard
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinator,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.safeguards import SafeguardReceipt, evaluate_pre_dispatch
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
    TargetDispatchFenceTransitionReceipt,
)
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryAuditIntentStore,
    InMemoryIdempotencyReservationStore,
    InMemoryPostReleaseClosureStore,
    InMemorySafeguardDispatchEvidenceStore,
    InMemoryTargetDispatchFenceStore,
)
from fdai.core.workflow.safeguard_commitment import ProcessRuntimeSafeguardCommitmentStore
from fdai.shared.contracts.models import Action, ExecutionPath, Mode, WorkflowActionRef
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.resource_lock import (
    HeldResourceLock,
    LiveLockOwnershipAssessment,
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
)
from fdai.shared.providers.testing import InMemoryStateStore, RecordingDirectApiExecutor
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore

from tests.core.executor.test_direct_api_executor import _action as _direct_action

_NOW = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40
_PROCESS_ID = "process-guard-1"


class _ProductionEligibleLock(ResourceLockManager):
    """An evidenced lock that claims production eligibility."""

    production_eligible = True


class _UnreleasableLock(ResourceLockManager):
    """Complete the dispatch but never prove the lock was released."""

    @asynccontextmanager
    async def acquire_evidenced(
        self,
        request: ResourceLockAcquisitionRequest,
    ) -> AsyncIterator[HeldResourceLock]:
        async with super().acquire_evidenced(request) as held:
            yield held
        raise RuntimeError("lock release could not be proven")


class _ReleaseCancellingLock(ResourceLockManager):
    """Cancel after the provider ran and the local release receipt exists."""

    @asynccontextmanager
    async def acquire_evidenced(
        self,
        request: ResourceLockAcquisitionRequest,
    ) -> AsyncIterator[HeldResourceLock]:
        async with super().acquire_evidenced(request) as held:
            yield held
        raise asyncio.CancelledError


class _MissingReleaseReceiptHandle:
    """Delegate one held lock while withholding terminal release evidence."""

    def __init__(self, inner: HeldResourceLock) -> None:
        self._inner = inner

    @property
    def acquisition_request(self) -> ResourceLockAcquisitionRequest:
        return self._inner.acquisition_request

    @property
    def acquisition_receipt(self) -> ResourceLockAcquisitionReceipt:
        return self._inner.acquisition_receipt

    def require_active(self) -> None:
        self._inner.require_active()

    @property
    def release_receipt(self) -> None:
        return None

    async def assess_ownership(self) -> LiveLockOwnershipAssessment:
        return await self._inner.assess_ownership()


class _MissingReleaseReceiptLock(ResourceLockManager):
    """Release the lock but violate the terminal receipt contract."""

    @asynccontextmanager
    async def acquire_evidenced(
        self,
        request: ResourceLockAcquisitionRequest,
    ) -> AsyncIterator[HeldResourceLock]:
        async with super().acquire_evidenced(request) as held:
            yield _MissingReleaseReceiptHandle(held)


class _CancellingLock(ResourceLockManager):
    """Cancel the task while the lifecycle still holds the target lock."""

    async def _owns_acquisition(
        self,
        lock_key: str,
        entry: object,
        acquisition_id: str,
    ) -> bool:
        del lock_key, entry, acquisition_id
        raise asyncio.CancelledError


class _PostDispatchUnassessableLock(ResourceLockManager):
    """Lose the ownership readback only after the provider was invoked."""

    def __init__(self) -> None:
        super().__init__(clock=lambda: _NOW, acquisition_id_factory=lambda: "test")
        self.assessment_count = 0

    async def _owns_acquisition(
        self,
        lock_key: str,
        entry: object,
        acquisition_id: str,
    ) -> bool:
        del lock_key, entry, acquisition_id
        self.assessment_count += 1
        if self.assessment_count <= 2:
            return True
        raise RuntimeError("post-dispatch ownership readback failed")


class _PostDispatchCancellingLock(ResourceLockManager):
    """Cancel only the ownership readback after provider invocation."""

    def __init__(self) -> None:
        super().__init__(clock=lambda: _NOW, acquisition_id_factory=lambda: "test")
        self.assessment_count = 0

    async def _owns_acquisition(
        self,
        lock_key: str,
        entry: object,
        acquisition_id: str,
    ) -> bool:
        del lock_key, entry, acquisition_id
        self.assessment_count += 1
        if self.assessment_count <= 2:
            return True
        raise asyncio.CancelledError


class _DelayedReleasePendingFenceStore(InMemoryTargetDispatchFenceStore):
    """Return a later authoritative receipt for the final fence transition."""

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceTransitionReceipt:
        receipt = await super().compare_and_transition(
            prior_record_digest=prior_record_digest,
            expected_revision=expected_revision,
            record=record,
        )
        if record.state is not TargetDispatchFenceState.RELEASE_PENDING:
            return receipt
        return TargetDispatchFenceTransitionReceipt.create(
            prior_record=receipt.prior_record,
            record=receipt.record,
            store_receipt_digest="sha256:" + "9" * 64,
            recorded_at=_NOW.replace(second=_NOW.second + 30),
        )


class _SlowObservationStore(InMemorySafeguardDispatchEvidenceStore):
    """Pause the post-dispatch observation write so caller cancellation can race it."""

    def __init__(self, entered: asyncio.Event) -> None:
        super().__init__()
        self._entered = entered

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: SafeguardDispatchEvidenceRecord,
        **kwargs: object,
    ) -> SafeguardDispatchTransitionReceipt:
        if record.state is SafeguardDispatchEvidenceState.DISPATCH_OBSERVED:
            self._entered.set()
            await asyncio.sleep(0.01)
        return await super().compare_and_transition(
            prior_record_digest=prior_record_digest,
            expected_revision=expected_revision,
            record=record,
            **kwargs,  # type: ignore[arg-type]
        )


class _RecordingDispatchPort:
    """Accept one dispatch and report a committed sink outcome."""

    def __init__(self) -> None:
        self.calls = 0

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
        pre_invoke_guard: DispatchBoundaryGuard,
    ) -> tuple[DispatchTransportState, AuthoritativeSinkState, str | None, str | None]:
        del evidence_record, started_at
        await pre_invoke_guard()
        self.calls += 1
        return (
            DispatchTransportState.ACKNOWLEDGED,
            AuthoritativeSinkState.COMMITTED,
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
        )


class _CancellingDispatchPort(_RecordingDispatchPort):
    """Cancel after the durable dispatch-start checkpoint exists."""

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
        pre_invoke_guard: DispatchBoundaryGuard,
    ) -> tuple[DispatchTransportState, AuthoritativeSinkState, str | None, str | None]:
        del evidence_record, started_at
        await pre_invoke_guard()
        self.calls += 1
        raise asyncio.CancelledError


class _CancellingClosureStore:
    """Cancel closure writes while preserving the wrapped durable read seam."""

    production_eligible = False

    def __init__(
        self,
        inner: PostReleaseClosureStore,
        *,
        complete_on_retry: bool,
        persist_before_cancel: bool = False,
        read_failure: bool = False,
    ) -> None:
        self._inner = inner
        self._complete_on_retry = complete_on_retry
        self._persist_before_cancel = persist_before_cancel
        self._read_failure = read_failure
        self.write_attempts = 0

    async def write(
        self,
        plan: PostReleaseClosurePlan,
    ) -> PostReleaseClosureStoreReceipt:
        self.write_attempts += 1
        if self.write_attempts == 1:
            if self._persist_before_cancel:
                await self._inner.write(plan)
            raise asyncio.CancelledError
        if not self._complete_on_retry:
            raise asyncio.CancelledError
        return await self._inner.write(plan)

    async def read(self, closure_key: str) -> PostReleaseClosureRecord | None:
        if self._read_failure:
            raise RuntimeError("sensitive closure readback detail")
        return await self._inner.read(closure_key)

    async def read_receipt(
        self,
        closure_key: str,
    ) -> PostReleaseClosureStoreReceipt | None:
        if self._read_failure:
            raise RuntimeError("sensitive closure readback detail")
        return await self._inner.read_receipt(closure_key)


class _ErrorThenCancelClosureStore:
    """Fail once, cancel once, then allow exact closure recovery."""

    production_eligible = False

    def __init__(self, inner: PostReleaseClosureStore) -> None:
        self._inner = inner
        self.write_attempts = 0

    async def write(
        self,
        plan: PostReleaseClosurePlan,
    ) -> PostReleaseClosureStoreReceipt:
        self.write_attempts += 1
        if self.write_attempts == 1:
            raise RuntimeError("closure write failed")
        if self.write_attempts == 2:
            raise asyncio.CancelledError
        return await self._inner.write(plan)

    async def read(self, closure_key: str) -> PostReleaseClosureRecord | None:
        return await self._inner.read(closure_key)

    async def read_receipt(
        self,
        closure_key: str,
    ) -> PostReleaseClosureStoreReceipt | None:
        return await self._inner.read_receipt(closure_key)


class _SlowRecoveringClosureStore:
    """Expose both initial and recovery writes to repeated task cancellation."""

    production_eligible = False

    def __init__(
        self,
        inner: PostReleaseClosureStore,
        first_entered: asyncio.Event,
        recovery_entered: asyncio.Event,
    ) -> None:
        self._inner = inner
        self._first_entered = first_entered
        self._recovery_entered = recovery_entered
        self.write_attempts = 0

    async def write(
        self,
        plan: PostReleaseClosurePlan,
    ) -> PostReleaseClosureStoreReceipt:
        self.write_attempts += 1
        entered = self._first_entered if self.write_attempts == 1 else self._recovery_entered
        entered.set()
        await asyncio.sleep(0.01)
        return await self._inner.write(plan)

    async def read(self, closure_key: str) -> PostReleaseClosureRecord | None:
        return await self._inner.read(closure_key)

    async def read_receipt(
        self,
        closure_key: str,
    ) -> PostReleaseClosureStoreReceipt | None:
        return await self._inner.read_receipt(closure_key)


class _UnavailableAuditStore(InMemoryStateStore):
    """Reject quarantine audit persistence after dispatch cancellation."""

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        del entry
        raise RuntimeError("audit persistence unavailable")


def _stores() -> dict[str, object]:
    reservations = InMemoryIdempotencyReservationStore()
    fences = InMemoryTargetDispatchFenceStore()
    return {
        "reservation_store": reservations,
        "audit_intent_store": InMemoryAuditIntentStore(),
        "fence_store": fences,
        "evidence_store": InMemorySafeguardDispatchEvidenceStore(),
        "closure_store": InMemoryPostReleaseClosureStore(
            reservation_store=reservations,
            fence_store=fences,
        ),
    }


def _policy() -> EffectSinkContinuityPolicy:
    return EffectSinkContinuityPolicy.create(
        sink_id="test-dispatch",
        sink_version="1.0.0",
        strategy=OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION,
        cancellation_supported=True,
        durable_unknown_quarantine=True,
        reconciliation_supported=True,
    )


def _config(*, production: bool = False) -> SafeguardLifecycleCoordinatorConfig:
    return SafeguardLifecycleCoordinatorConfig(
        source_revision=_SOURCE_REVISION,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        actor="fdai.core.executor",
        expected_lock_verifier_id="fdai-in-memory-lock-readback",
        expected_lock_verifier_version="1.0.0",
        expected_lock_trust_anchor_id="fdai:local-test-only",
        production=production,
    )


def _coordinator(
    audit: InMemoryStateStore,
    *,
    lock: ResourceLockManager | None = None,
    commitment_store: object | None = None,
    stores: dict[str, object] | None = None,
) -> SafeguardLifecycleCoordinator:
    lifecycle_stores = stores or _stores()
    return SafeguardLifecycleCoordinator(
        resource_lock=lock
        or ResourceLockManager(clock=lambda: _NOW, acquisition_id_factory=lambda: "test"),
        denial_audit_store=audit,
        continuity_policy=_policy(),
        config=_config(),
        commitment_store=commitment_store,  # type: ignore[arg-type]
        clock=lambda: _NOW,
        **lifecycle_stores,  # type: ignore[arg-type]
    )


def _denials(audit: InMemoryStateStore) -> list[str]:
    """Return the reason of every durable safeguard-lifecycle denial."""

    reasons: list[str] = []
    for record in audit.audit_entries:
        entry = record.get("entry", record) if isinstance(record, dict) else dict(record)
        if entry.get("action_kind") == "executor.safeguard_lifecycle.denied":
            reasons.append(str(entry.get("reason")))
    return reasons


def _receipt(action: Action) -> SafeguardReceipt:
    receipt = evaluate_pre_dispatch(
        action,
        execution_path=ExecutionPath.DIRECT_API,
        plan_digest="sha256:" + "3" * 64,
        plan_kind="direct_api_request",
    )
    assert isinstance(receipt, SafeguardReceipt)
    return receipt


async def _commitment_store() -> ProcessRuntimeSafeguardCommitmentStore:
    process_store = InMemoryProcessRuntimeStore()
    await process_store.create(
        snapshot=ProcessSnapshot(
            process_id=_PROCESS_ID,
            workflow_ref="recovery-flow",
            workflow_version="1",
            status=ProcessStatus.RUNNING,
            current_step="restart",
            target_resource_id="resource:example/rg/vm1",
            started_at=_NOW,
            updated_at=_NOW,
            correlation_id="correlation-guard-1",
        ),
        event=ProcessEvent(
            event_id="event-created",
            process_id=_PROCESS_ID,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key=f"{_PROCESS_ID}:created",
            recorded_at=_NOW,
            correlation_id="correlation-guard-1",
        ),
    )
    return ProcessRuntimeSafeguardCommitmentStore(process_store)


def _workflow_action() -> Action:
    return _direct_action().model_copy(
        update={
            "workflow_action": WorkflowActionRef(
                process_id=_PROCESS_ID,
                step_id="restart",
                proposal_ref=f"{_PROCESS_ID}:step:restart:attempt:1",
            )
        }
    )


class TestProductionComposition:
    def test_a_production_coordinator_refuses_non_production_stores(self) -> None:
        with pytest.raises(RuntimeError, match="production safeguard lifecycle stores"):
            SafeguardLifecycleCoordinator(
                resource_lock=_ProductionEligibleLock(clock=lambda: _NOW),
                denial_audit_store=InMemoryStateStore(),
                continuity_policy=_policy(),
                config=_config(production=True),
                clock=lambda: _NOW,
                **_stores(),  # type: ignore[arg-type]
            )

    def test_a_non_production_coordinator_reports_its_composition(self) -> None:
        coordinator = _coordinator(InMemoryStateStore())

        assert coordinator.production_ready is False
        assert coordinator.source_revision == _SOURCE_REVISION


class TestDispatchPreconditions:
    async def test_a_forged_safeguard_receipt_is_denied(self) -> None:
        audit = InMemoryStateStore()
        coordinator = _coordinator(audit)
        port = _RecordingDispatchPort()

        class _Forged(SafeguardReceipt):
            pass

        genuine = _receipt(_direct_action())
        forged = _Forged(**{field: getattr(genuine, field) for field in genuine.__slots__})

        result = await coordinator.dispatch(
            action=_direct_action(),
            safeguard_receipt=forged,
            dispatch_port=port,
            correlation_id="correlation-1",
        )

        assert result.disposition is SafeguardCoordinationDisposition.BLOCKED
        assert result.dispatch_performed is False
        assert result.reason == "safeguard receipt is missing or invalid"
        assert port.calls == 0
        assert _denials(audit) == ["safeguard receipt is missing or invalid"]

    async def test_a_non_positive_attempt_is_denied(self) -> None:
        audit = InMemoryStateStore()
        coordinator = _coordinator(audit)
        port = _RecordingDispatchPort()
        action = _direct_action()

        result = await coordinator.dispatch(
            action=action,
            safeguard_receipt=_receipt(action),
            dispatch_port=port,
            correlation_id="correlation-1",
            attempt=0,
        )

        assert result.disposition is SafeguardCoordinationDisposition.BLOCKED
        assert result.reason == "safeguard lifecycle attempt MUST be positive"
        assert port.calls == 0
        assert _denials(audit) == ["safeguard lifecycle attempt MUST be positive"]


class TestWorkflowCommitmentReuse:
    async def test_a_restart_reuses_the_exact_prior_commitment(self) -> None:
        audit = InMemoryStateStore()
        coordinator = _coordinator(audit, commitment_store=await _commitment_store())
        action = _workflow_action()

        first = await coordinator.prepare_pre_bundle_commitment(
            action=action,
            execution_path=ExecutionPath.DIRECT_API,
            correlation_id="correlation-guard-1",
        )
        reused = await coordinator.prepare_pre_bundle_commitment(
            action=action,
            execution_path=ExecutionPath.DIRECT_API,
            correlation_id="correlation-guard-1",
        )

        assert reused == first
        assert reused.commitment_digest == first.commitment_digest

    async def test_a_reused_commitment_rejects_a_substituted_path(self) -> None:
        audit = InMemoryStateStore()
        coordinator = _coordinator(audit, commitment_store=await _commitment_store())
        action = _workflow_action()
        await coordinator.prepare_pre_bundle_commitment(
            action=action,
            execution_path=ExecutionPath.DIRECT_API,
            correlation_id="correlation-guard-1",
        )

        with pytest.raises(ValueError, match="changed dispatch context"):
            await coordinator.prepare_pre_bundle_commitment(
                action=action,
                execution_path=ExecutionPath.TOOL_CALL,
                correlation_id="correlation-guard-1",
            )


class TestTerminalContinuity:
    async def test_an_unprovable_release_quarantines_a_completed_dispatch(self) -> None:
        audit = InMemoryStateStore()
        lock = _UnreleasableLock(clock=lambda: _NOW, acquisition_id_factory=lambda: "test")
        coordinator = _coordinator(audit, lock=lock)
        port = _RecordingDispatchPort()
        action = _direct_action()

        result = await coordinator.dispatch(
            action=action,
            safeguard_receipt=_receipt(action),
            dispatch_port=port,
            correlation_id="correlation-1",
        )

        # The provider really ran, so the action cannot be reported as a
        # clean success while the lock release is unproven.
        assert port.calls == 1
        assert result.disposition is SafeguardCoordinationDisposition.QUARANTINED
        assert "lock release was not proven" in (result.reason or "")
        assert result.bundle_digest is not None
        assert result.closure_receipt is not None
        assert result.closure_receipt.record.outcome is PostReleaseClosureOutcome.QUARANTINED

    async def test_missing_release_receipt_preserves_dispatched_lifecycle(self) -> None:
        audit = InMemoryStateStore()
        lock = _MissingReleaseReceiptLock(
            clock=lambda: _NOW,
            acquisition_id_factory=lambda: "test",
        )
        coordinator = _coordinator(audit, lock=lock)
        port = _RecordingDispatchPort()
        action = _direct_action()

        result = await coordinator.dispatch(
            action=action,
            safeguard_receipt=_receipt(action),
            dispatch_port=port,
            correlation_id="correlation-1",
        )

        assert port.calls == 1
        assert result.disposition is SafeguardCoordinationDisposition.QUARANTINED
        assert result.dispatch_performed is True
        assert result.bundle_digest is not None
        assert result.lifecycle is not None
        assert result.reason == "post-release safeguard evidence is unavailable"

    async def test_closure_follows_authoritative_release_pending_persistence_time(self) -> None:
        audit = InMemoryStateStore()
        reservations = InMemoryIdempotencyReservationStore()
        fences = _DelayedReleasePendingFenceStore()
        closure = InMemoryPostReleaseClosureStore(
            reservation_store=reservations,
            fence_store=fences,
        )
        stores: dict[str, object] = {
            "reservation_store": reservations,
            "audit_intent_store": InMemoryAuditIntentStore(),
            "fence_store": fences,
            "evidence_store": InMemorySafeguardDispatchEvidenceStore(),
            "closure_store": closure,
        }
        coordinator = _coordinator(audit, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()

        result = await coordinator.dispatch(
            action=action,
            safeguard_receipt=_receipt(action),
            dispatch_port=port,
            correlation_id="correlation-1",
        )

        assert result.disposition is SafeguardCoordinationDisposition.COMPLETED
        assert result.closure_receipt is not None
        assert result.closure_receipt.record.closed_at == _NOW.replace(second=_NOW.second + 30)

    async def test_a_post_dispatch_failure_is_quarantined(self) -> None:
        audit = InMemoryStateStore()
        lock = _PostDispatchUnassessableLock()
        coordinator = _coordinator(audit, lock=lock)
        port = _RecordingDispatchPort()
        action = _direct_action().model_copy(update={"mode": Mode.ENFORCE})

        result = await coordinator.dispatch(
            action=action,
            safeguard_receipt=_receipt(action),
            dispatch_port=port,
            correlation_id="correlation-1",
        )

        assert port.calls == 1
        assert result.disposition is SafeguardCoordinationDisposition.QUARANTINED
        assert result.dispatch_performed is True
        assert result.bundle_digest is not None
        assert result.reason == "pre-release ownership assessment failed"
        assert "ownership readback failed" not in (result.reason or "")
        quarantine = next(
            row["entry"]
            for row in audit.audit_entries
            if row["entry"].get("action_kind") == "executor.safeguard_lifecycle.quarantined"
        )
        assert quarantine["dispatch_performed"] is True
        assert quarantine["safeguard_bundle_digest"] == result.bundle_digest
        assert quarantine["mode"] == "enforce"

    async def test_post_dispatch_ownership_cancellation_closes_then_propagates(self) -> None:
        audit = InMemoryStateStore()
        stores = _stores()
        closure = stores["closure_store"]
        assert isinstance(closure, InMemoryPostReleaseClosureStore)
        lock = _PostDispatchCancellingLock()
        coordinator = _coordinator(audit, lock=lock, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1
        assert len(closure.audit_entries) == 1
        assert closure.audit_entries[0]["outcome"] == "quarantined"

    async def test_cancellation_during_observation_write_closes_then_propagates(self) -> None:
        audit = InMemoryStateStore()
        stores = _stores()
        closure = stores["closure_store"]
        assert isinstance(closure, InMemoryPostReleaseClosureStore)
        entered = asyncio.Event()
        stores["evidence_store"] = _SlowObservationStore(entered)
        coordinator = _coordinator(audit, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()
        task = asyncio.create_task(
            coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )
        )

        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert port.calls == 1
        assert len(closure.audit_entries) == 1
        assert closure.audit_entries[0]["outcome"] == "quarantined"

    async def test_release_cancellation_closes_then_propagates(self) -> None:
        audit = InMemoryStateStore()
        stores = _stores()
        closure = stores["closure_store"]
        assert isinstance(closure, InMemoryPostReleaseClosureStore)
        lock = _ReleaseCancellingLock(
            clock=lambda: _NOW,
            acquisition_id_factory=lambda: "test",
        )
        coordinator = _coordinator(audit, lock=lock, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1
        assert len(closure.audit_entries) == 1
        assert closure.audit_entries[0]["outcome"] == "quarantined"

    async def test_a_cancellation_inside_the_lock_propagates(self) -> None:
        audit = InMemoryStateStore()
        lock = _CancellingLock(clock=lambda: _NOW, acquisition_id_factory=lambda: "test")
        coordinator = _coordinator(audit, lock=lock)
        adapter = RecordingDirectApiExecutor()
        executor = DirectApiShadowExecutor(
            executor=adapter,
            audit_store=audit,
            resource_lock=lock,
            safeguard_coordinator=coordinator,
        )

        with pytest.raises(asyncio.CancelledError):
            await executor.execute(action=_direct_action())

        assert adapter.records == ()

    async def test_a_post_dispatch_cancellation_is_quarantined_then_propagated(self) -> None:
        audit = InMemoryStateStore()
        coordinator = _coordinator(audit)
        port = _CancellingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1
        quarantine = next(
            row["entry"]
            for row in audit.audit_entries
            if row["entry"].get("action_kind") == "executor.safeguard_lifecycle.quarantined"
        )
        assert quarantine["dispatch_performed"] is True
        assert quarantine["safeguard_bundle_digest"] is not None

    async def test_closure_cancellation_retries_exact_plan_then_propagates(self) -> None:
        audit = InMemoryStateStore()
        stores = _stores()
        inner = stores["closure_store"]
        assert isinstance(inner, PostReleaseClosureStore)
        closure = _CancellingClosureStore(inner, complete_on_retry=True)
        stores["closure_store"] = closure
        coordinator = _coordinator(audit, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1
        assert closure.write_attempts == 2
        assert not any(
            row["entry"].get("action_kind") == "executor.safeguard_lifecycle.quarantined"
            for row in audit.audit_entries
        )

    async def test_closure_cancellation_accepts_exact_committed_readback(self) -> None:
        audit = InMemoryStateStore()
        stores = _stores()
        inner = stores["closure_store"]
        assert isinstance(inner, PostReleaseClosureStore)
        closure = _CancellingClosureStore(
            inner,
            complete_on_retry=False,
            persist_before_cancel=True,
        )
        stores["closure_store"] = closure
        coordinator = _coordinator(audit, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1
        assert closure.write_attempts == 1
        assert not any(
            row["entry"].get("action_kind") == "executor.safeguard_lifecycle.quarantined"
            for row in audit.audit_entries
        )

    async def test_closure_cancellation_records_quarantine_when_retry_cannot_finish(self) -> None:
        audit = InMemoryStateStore()
        stores = _stores()
        inner = stores["closure_store"]
        assert isinstance(inner, PostReleaseClosureStore)
        closure = _CancellingClosureStore(inner, complete_on_retry=False)
        stores["closure_store"] = closure
        coordinator = _coordinator(audit, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1
        assert closure.write_attempts == 2
        quarantine = next(
            row["entry"]
            for row in audit.audit_entries
            if row["entry"].get("action_kind") == "executor.safeguard_lifecycle.quarantined"
        )
        assert quarantine["mode"] == "shadow"

    async def test_closure_readback_failure_is_sanitized_and_quarantined(self) -> None:
        audit = InMemoryStateStore()
        stores = _stores()
        inner = stores["closure_store"]
        assert isinstance(inner, PostReleaseClosureStore)
        closure = _CancellingClosureStore(
            inner,
            complete_on_retry=False,
            read_failure=True,
        )
        stores["closure_store"] = closure
        coordinator = _coordinator(audit, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1
        assert closure.write_attempts == 1
        quarantine = next(
            row["entry"]
            for row in audit.audit_entries
            if row["entry"].get("action_kind") == "executor.safeguard_lifecycle.quarantined"
        )
        assert quarantine["reason"].endswith("RuntimeError")
        assert "sensitive closure readback detail" not in quarantine["reason"]

    async def test_quarantine_audit_failure_does_not_replace_cancellation(self) -> None:
        audit = _UnavailableAuditStore()
        coordinator = _coordinator(audit)
        port = _CancellingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1

    async def test_closure_audit_failure_does_not_replace_cancellation(self) -> None:
        audit = _UnavailableAuditStore()
        stores = _stores()
        inner = stores["closure_store"]
        assert isinstance(inner, PostReleaseClosureStore)
        closure = _CancellingClosureStore(inner, complete_on_retry=False)
        stores["closure_store"] = closure
        coordinator = _coordinator(audit, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1
        assert closure.write_attempts == 2

    async def test_cancellation_during_failed_closure_retry_still_closes(self) -> None:
        audit = InMemoryStateStore()
        stores = _stores()
        inner = stores["closure_store"]
        assert isinstance(inner, InMemoryPostReleaseClosureStore)
        closure = _ErrorThenCancelClosureStore(inner)
        stores["closure_store"] = closure
        coordinator = _coordinator(audit, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()

        with pytest.raises(asyncio.CancelledError):
            await coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )

        assert port.calls == 1
        assert closure.write_attempts == 3
        assert len(inner.audit_entries) == 1

    async def test_repeated_cancellation_cannot_abort_closure_recovery(self) -> None:
        audit = InMemoryStateStore()
        stores = _stores()
        inner = stores["closure_store"]
        assert isinstance(inner, InMemoryPostReleaseClosureStore)
        first_entered = asyncio.Event()
        recovery_entered = asyncio.Event()
        closure = _SlowRecoveringClosureStore(
            inner,
            first_entered,
            recovery_entered,
        )
        stores["closure_store"] = closure
        coordinator = _coordinator(audit, stores=stores)
        port = _RecordingDispatchPort()
        action = _direct_action()
        task = asyncio.create_task(
            coordinator.dispatch(
                action=action,
                safeguard_receipt=_receipt(action),
                dispatch_port=port,
                correlation_id="correlation-1",
            )
        )

        await first_entered.wait()
        task.cancel()
        await recovery_entered.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert port.calls == 1
        assert closure.write_attempts == 2
        assert len(inner.audit_entries) == 1
