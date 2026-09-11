"""Coordinator-level guards around one shared safeguard dispatch.

These cover the boundaries the per-path adapters cannot reach on their own:
the production composition check, a caller that hands over something other
than a real safeguard receipt, a non-positive attempt, a workflow commitment
that is reused across a restart, a cancellation raised inside the held lock,
and a lock release that cannot be proven after a completed dispatch.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fdai.core.executor import (
    DirectApiExecutionOutcome,
    DirectApiShadowExecutor,
    ResourceLockManager,
)
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinator,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.safeguards import SafeguardReceipt, evaluate_pre_dispatch
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryAuditIntentStore,
    InMemoryIdempotencyReservationStore,
    InMemoryPostReleaseClosureStore,
    InMemorySafeguardDispatchEvidenceStore,
    InMemoryTargetDispatchFenceStore,
)
from fdai.core.workflow.safeguard_commitment import ProcessRuntimeSafeguardCommitmentStore
from fdai.shared.contracts.models import Action, ExecutionPath, WorkflowActionRef
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.resource_lock import (
    HeldResourceLock,
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


class _RecordingDispatchPort:
    """Accept one dispatch and report a committed sink outcome."""

    def __init__(self) -> None:
        self.calls = 0

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
    ) -> tuple[DispatchTransportState, AuthoritativeSinkState, str | None, str | None]:
        del evidence_record, started_at
        self.calls += 1
        return (
            DispatchTransportState.ACKNOWLEDGED,
            AuthoritativeSinkState.COMMITTED,
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
        )


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
) -> SafeguardLifecycleCoordinator:
    return SafeguardLifecycleCoordinator(
        resource_lock=lock
        or ResourceLockManager(clock=lambda: _NOW, acquisition_id_factory=lambda: "test"),
        denial_audit_store=audit,
        continuity_policy=_policy(),
        config=_config(),
        commitment_store=commitment_store,  # type: ignore[arg-type]
        clock=lambda: _NOW,
        **_stores(),  # type: ignore[arg-type]
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
        adapter = RecordingDirectApiExecutor()
        executor = DirectApiShadowExecutor(
            executor=adapter,
            audit_store=audit,
            resource_lock=lock,
            safeguard_coordinator=coordinator,
        )

        result = await executor.execute(action=_direct_action())

        # The provider really ran, so the action cannot be reported as a
        # clean success while the lock release is unproven.
        assert len(adapter.records) == 1
        assert result.outcome is DirectApiExecutionOutcome.FAILED
        assert "lock release was not proven" in (result.reason or "")
        assert result.safeguard_bundle_digest is not None

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
