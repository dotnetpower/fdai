"""Actual executor call-site coverage for the shared safeguard lifecycle."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.executor import (
    DirectApiExecutionOutcome,
    DirectApiShadowExecutor,
    ExecutorOutcome,
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
    ToolCallExecutionOutcome,
    ToolCallShadowExecutor,
)
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardLifecycleCoordinator,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryAuditIntentStore,
    InMemoryIdempotencyReservationStore,
    InMemoryPostReleaseClosureStore,
    InMemorySafeguardDispatchEvidenceStore,
    InMemoryTargetDispatchFenceStore,
)
from fdai.core.workflow.automation_hold import (
    AutomationHoldReleaseReceipt,
    StateStoreAutomationHoldLedger,
)
from fdai.core.workflow.recovery_admission import assess_workflow_recovery_admission
from fdai.core.workflow.safeguard_commitment import ProcessRuntimeSafeguardCommitmentStore
from fdai.core.workflow.workflow_runtime import (
    WorkflowApprovalDecision,
    WorkflowApprovalSnapshot,
    workflow_approval_state_key,
)
from fdai.shared.contracts.models import ExecutionPath, WorkflowActionRef
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingDirectApiExecutor,
    RecordingRemediationPrPublisher,
    RecordingToolExecutor,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore

from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.executor.test_executor import _action as _pr_action
from tests.core.executor.test_executor import _rule
from tests.core.executor.test_tool_call_executor import _action as _tool_action

_NOW = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40
_ROOT = Path(__file__).resolve().parents[5]
_HOLD_PROCESS_ID = "process-hold-1"
_HOLD_RECEIPTS = ("sha256:" + "b" * 64, "sha256:" + "c" * 64)


def _coordinator(
    audit: InMemoryStateStore,
    *,
    hold_state_reader: object | None = None,
    hold_release_authorizations: object | None = None,
    commitment_store: object | None = None,
) -> tuple[SafeguardLifecycleCoordinator, ResourceLockManager]:
    lock = ResourceLockManager(clock=lambda: _NOW, acquisition_id_factory=lambda: "test")
    reservations = InMemoryIdempotencyReservationStore()
    fences = InMemoryTargetDispatchFenceStore()
    coordinator = SafeguardLifecycleCoordinator(
        resource_lock=lock,
        reservation_store=reservations,
        audit_intent_store=InMemoryAuditIntentStore(),
        fence_store=fences,
        evidence_store=InMemorySafeguardDispatchEvidenceStore(),
        closure_store=InMemoryPostReleaseClosureStore(
            reservation_store=reservations,
            fence_store=fences,
        ),
        denial_audit_store=audit,
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
        commitment_store=commitment_store,  # type: ignore[arg-type]
        hold_state_reader=hold_state_reader,  # type: ignore[arg-type]
        hold_release_authorizations=hold_release_authorizations,  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )
    return coordinator, lock


@pytest.mark.parametrize("path", [ExecutionPath.PR_NATIVE, ExecutionPath.PR_MANUAL])
async def test_pr_paths_dispatch_through_shared_lifecycle(path: ExecutionPath) -> None:
    audit = InMemoryStateStore()
    coordinator, lock = _coordinator(audit)
    publisher = RecordingRemediationPrPublisher()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=_ROOT / "rule-catalog" / "remediation"),
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=_pr_action(), rule=_rule(), execution_path=path)

    assert result.outcome is ExecutorOutcome.PUBLISHED
    assert result.safeguard_bundle_digest is not None
    assert len(publisher.records) == 1
    assert (
        publisher.records[0].metadata["safeguard_bundle_digest"] == result.safeguard_bundle_digest
    )


async def test_direct_api_dispatches_through_shared_lifecycle() -> None:
    audit = InMemoryStateStore()
    coordinator, lock = _coordinator(audit)
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=_direct_action())

    assert result.outcome is DirectApiExecutionOutcome.DISPATCHED
    assert result.safeguard_bundle_digest is not None
    assert len(adapter.records) == 1
    assert adapter.records[0].metadata["safeguard_bundle_digest"] == result.safeguard_bundle_digest


async def test_direct_api_restart_reuses_retained_bundle_without_dispatch() -> None:
    audit = InMemoryStateStore()
    coordinator, lock = _coordinator(audit)
    adapter = RecordingDirectApiExecutor()
    first_executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )
    first = await first_executor.execute(action=_direct_action())
    restarted_executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    replay = await restarted_executor.execute(action=_direct_action())

    assert replay.outcome is DirectApiExecutionOutcome.ALREADY_APPLIED
    assert replay.safeguard_bundle_digest == first.safeguard_bundle_digest
    assert len(adapter.records) == 1


async def test_tool_call_dispatches_through_shared_lifecycle() -> None:
    audit = InMemoryStateStore()
    coordinator, lock = _coordinator(audit)
    adapter = RecordingToolExecutor()
    executor = ToolCallShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=_tool_action())

    assert result.outcome is ToolCallExecutionOutcome.DISPATCHED
    assert result.safeguard_bundle_digest is not None
    assert len(adapter.records) == 1
    assert adapter.records[0].metadata["safeguard_bundle_digest"] == result.safeguard_bundle_digest


async def test_workflow_dispatch_rejects_missing_commitment_store() -> None:
    audit = InMemoryStateStore()
    coordinator, lock = _coordinator(audit)
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )
    action = _direct_action().model_copy(
        update={
            "workflow_action": WorkflowActionRef(
                process_id="process-1",
                step_id="restart",
                proposal_ref="proposal-1",
                attempt=2,
            )
        }
    )

    result = await executor.execute(action=action)

    assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
    assert result.safeguard_bundle_digest is None
    assert adapter.records == ()
    assert "commitment store is unavailable" in (result.reason or "")


def test_production_coordinator_rejects_test_stores() -> None:
    audit = InMemoryStateStore()
    lock = ResourceLockManager(clock=lambda: _NOW)
    reservations = InMemoryIdempotencyReservationStore()
    fences = InMemoryTargetDispatchFenceStore()

    with pytest.raises(RuntimeError, match="not production eligible|stores are unavailable"):
        SafeguardLifecycleCoordinator(
            resource_lock=lock,
            reservation_store=reservations,
            audit_intent_store=InMemoryAuditIntentStore(),
            fence_store=fences,
            evidence_store=InMemorySafeguardDispatchEvidenceStore(),
            closure_store=InMemoryPostReleaseClosureStore(
                reservation_store=reservations,
                fence_store=fences,
            ),
            denial_audit_store=audit,
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
                production=True,
            ),
            clock=lambda: _NOW,
        )


class _StaticHoldReader:
    """Return one fixed durable automation-hold record for fencing."""

    def __init__(self, record: dict[str, object] | None) -> None:
        self.record = record
        self.reads = 0

    async def read_hold_record(self, *, target_ref: str) -> dict[str, object] | None:
        del target_ref
        self.reads += 1
        return self.record


class _UnreadableHoldReader:
    """Fail every hold read so dispatch fences closed."""

    async def read_hold_record(self, *, target_ref: str) -> dict[str, object] | None:
        del target_ref
        raise RuntimeError("automation hold state is unreadable")


class _HoldAdmissions:
    """Issue one distinct decision-evidence admission per recovery release."""

    def __init__(self, receipt_digest: str) -> None:
        self._receipt_digest = receipt_digest

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        return DecisionEvidenceAdmission(
            receipt_digest=self._receipt_digest,
            verification_bundle_digest="sha256:" + "f" * 64,
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
            verified_at=_NOW - timedelta(minutes=1),
            valid_until=_NOW + timedelta(minutes=5),
        )


async def _workflow_commitment_store() -> ProcessRuntimeSafeguardCommitmentStore:
    """Bind commitments against one real held Process runtime journal."""

    process_store = InMemoryProcessRuntimeStore()
    await process_store.create(
        snapshot=ProcessSnapshot(
            process_id=_HOLD_PROCESS_ID,
            workflow_ref="recovery-flow",
            workflow_version="1",
            status=ProcessStatus.COMPENSATING,
            current_step="compensate_apply_first",
            target_resource_id="resource:example/rg/vm1",
            started_at=_NOW,
            updated_at=_NOW,
            correlation_id="correlation-hold-1",
        ),
        event=ProcessEvent(
            event_id="event-created",
            process_id=_HOLD_PROCESS_ID,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key=f"{_HOLD_PROCESS_ID}:created",
            recorded_at=_NOW,
            correlation_id="correlation-hold-1",
        ),
    )
    return ProcessRuntimeSafeguardCommitmentStore(process_store)


def _workflow_action(action, step_id: str):
    """Return the same action carrying one exact workflow step lineage."""

    return action.model_copy(
        update={
            "workflow_action": WorkflowActionRef(
                process_id=_HOLD_PROCESS_ID,
                step_id=step_id,
                proposal_ref=f"{_HOLD_PROCESS_ID}:step:{step_id}:attempt:1",
            )
        }
    )


async def _release_hold(
    store: InMemoryStateStore,
    *,
    target_ref: str,
    action_id: str,
    hold_revision: int,
    admission_receipt_digest: str,
    step_id: str,
) -> AutomationHoldReleaseReceipt | None:
    """Release one real hold revision through the production ledger."""

    ledger = StateStoreAutomationHoldLedger(store, clock=lambda: _NOW)
    snapshot = WorkflowApprovalSnapshot(
        process_id=_HOLD_PROCESS_ID,
        step_id=step_id,
        requester_principal="requester@example.com",
        revision=3,
        requested_at=_NOW - timedelta(minutes=2),
        expires_at=_NOW + timedelta(minutes=10),
        attempt=1,
        decisions=(
            WorkflowApprovalDecision(
                principal="approver@example.com",
                decision="approved",
                receipt_ref=f"approval:{step_id}",
            ),
        ),
    )
    await store.write_state(
        workflow_approval_state_key(snapshot.process_id, snapshot.step_id, snapshot.attempt),
        {
            "process_id": snapshot.process_id,
            "step_id": snapshot.step_id,
            "attempt": snapshot.attempt,
            "requester_principal": snapshot.requester_principal,
            "quorum": 1,
            "no_self_approval": True,
            "requested_at": snapshot.requested_at.isoformat(),
            "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
            "decision_claims": {
                "slot-1": {
                    "principal": snapshot.decisions[0].principal,
                    "decision": snapshot.decisions[0].decision,
                    "receipt_ref": snapshot.decisions[0].receipt_ref,
                }
            },
            "state": "pending",
            "revision": snapshot.revision,
        },
    )
    assessment = await assess_workflow_recovery_admission(
        _HoldAdmissions(admission_receipt_digest),
        snapshot=snapshot,
        quorum=1,
        no_self_approval=True,
        hold_revision=hold_revision,
        target_digest="sha256:" + hashlib.sha256(target_ref.encode()).hexdigest(),
        compensation_receipt_digests=_HOLD_RECEIPTS,
        executor_identity="executor@example.com",
        source_revision=_SOURCE_REVISION,
        evaluated_at=_NOW,
    )
    return await ledger.release_admitted(
        target_ref=target_ref,
        process_id=_HOLD_PROCESS_ID,
        action_id=action_id,
        hold_revision=hold_revision,
        approval_snapshot=snapshot,
        quorum=1,
        no_self_approval=True,
        compensation_receipt_digests=_HOLD_RECEIPTS,
        executor_identity="executor@example.com",
        source_revision=_SOURCE_REVISION,
        assessment=assessment,
        workflow_lineage=(_HOLD_PROCESS_ID, step_id),
    )


async def test_active_hold_fences_direct_api_dispatch_inside_the_lock() -> None:
    audit = InMemoryStateStore()
    reader = _StaticHoldReader({"state": "active", "revision": 3})
    coordinator, lock = _coordinator(audit, hold_state_reader=reader)
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=_direct_action())

    assert reader.reads == 1
    assert len(adapter.records) == 0
    assert result.outcome is not DirectApiExecutionOutcome.DISPATCHED
    denial = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
    )
    assert denial["rejection_reasons"] == ["active_hold"]
    assert denial["outcome"] == "not_invoked"
    assert denial["execution_authority"] is False


async def test_hold_reissued_after_release_fences_tool_dispatch() -> None:
    audit = InMemoryStateStore(linearization_clock=lambda: _NOW)
    action = _workflow_action(_tool_action(), "recover_first")
    target = action.target_resource_ref
    ledger = StateStoreAutomationHoldLedger(audit, clock=lambda: _NOW)
    await ledger.issue(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        reason="compensation_failed",
    )
    authorized = await _release_hold(
        audit,
        target_ref=target,
        action_id=str(action.action_id),
        hold_revision=1,
        admission_receipt_digest="sha256:" + "e" * 64,
        step_id="recover_first",
    )
    assert authorized is not None
    await ledger.issue(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        reason="compensation_failed_again",
    )
    reissued = await ledger.read_hold_record(target_ref=target)
    assert reissued is not None
    second = await _release_hold(
        audit,
        target_ref=target,
        action_id="recovery-action-2",
        hold_revision=int(str(reissued["revision"])),
        admission_receipt_digest="sha256:" + "a" * 64,
        step_id="recover_second",
    )
    assert second is not None and second.receipt_digest != authorized.receipt_digest

    coordinator, lock = _coordinator(
        audit,
        hold_state_reader=ledger,
        hold_release_authorizations=ledger,
        commitment_store=await _workflow_commitment_store(),
    )
    adapter = RecordingToolExecutor()
    executor = ToolCallShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=action)

    assert len(adapter.records) == 0
    assert result.outcome is not ToolCallExecutionOutcome.DISPATCHED
    denial = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
    )
    assert "hold_reissued_after_release" in denial["rejection_reasons"]
    assert "release_receipt_mismatch" in denial["rejection_reasons"]
    assert "fencing_generation_mismatch" in denial["rejection_reasons"]


async def test_unreadable_hold_state_fences_dispatch_closed() -> None:
    audit = InMemoryStateStore()
    coordinator, lock = _coordinator(audit, hold_state_reader=_UnreadableHoldReader())
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=_direct_action())

    assert len(adapter.records) == 0
    assert result.outcome is not DirectApiExecutionOutcome.DISPATCHED
    denial = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
    )
    assert denial["rejection_reasons"] == ["unreadable_state"]


async def test_released_hold_with_matching_lineage_permits_dispatch() -> None:
    audit = InMemoryStateStore(linearization_clock=lambda: _NOW)
    action = _workflow_action(_direct_action(), "recover_first")
    target = action.target_resource_ref
    ledger = StateStoreAutomationHoldLedger(audit, clock=lambda: _NOW)
    await ledger.issue(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        reason="compensation_failed",
    )
    receipt = await _release_hold(
        audit,
        target_ref=target,
        action_id=str(action.action_id),
        hold_revision=1,
        admission_receipt_digest="sha256:" + "e" * 64,
        step_id="recover_first",
    )
    assert receipt is not None

    coordinator, lock = _coordinator(
        audit,
        hold_state_reader=ledger,
        hold_release_authorizations=ledger,
        commitment_store=await _workflow_commitment_store(),
    )
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=action)

    assert result.outcome is DirectApiExecutionOutcome.DISPATCHED
    assert len(adapter.records) == 1
    assert not any(
        row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
        for row in audit.audit_entries
    )


async def test_released_hold_without_authorization_for_this_action_is_denied() -> None:
    audit = InMemoryStateStore(linearization_clock=lambda: _NOW)
    action = _workflow_action(_direct_action(), "recover_other")
    target = action.target_resource_ref
    ledger = StateStoreAutomationHoldLedger(audit, clock=lambda: _NOW)
    await ledger.issue(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        reason="compensation_failed",
    )
    await ledger.issue(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        reason="still_failing",
    )

    coordinator, lock = _coordinator(
        audit,
        hold_state_reader=ledger,
        hold_release_authorizations=ledger,
        commitment_store=await _workflow_commitment_store(),
    )
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=action)

    assert len(adapter.records) == 0
    assert result.outcome is not DirectApiExecutionOutcome.DISPATCHED
    denial = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
    )
    assert denial["rejection_reasons"] == ["active_hold"]


async def test_hold_scoped_authorization_permits_the_approved_recovery_step() -> None:
    audit = InMemoryStateStore(linearization_clock=lambda: _NOW)
    action = _workflow_action(_direct_action(), "recover_first")
    target = action.target_resource_ref
    ledger = StateStoreAutomationHoldLedger(audit, clock=lambda: _NOW)
    await ledger.issue(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        reason="compensation_failed",
    )
    assert await ledger.authorize_hold_scoped_dispatch(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        step_id="recover_first",
        hold_revision=1,
    )

    coordinator, lock = _coordinator(
        audit,
        hold_state_reader=ledger,
        hold_release_authorizations=ledger,
        commitment_store=await _workflow_commitment_store(),
    )
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=action)

    assert result.outcome is DirectApiExecutionOutcome.DISPATCHED
    assert len(adapter.records) == 1
    assert not any(
        row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
        for row in audit.audit_entries
    )


async def test_hold_scoped_authorization_is_denied_after_the_hold_moves() -> None:
    audit = InMemoryStateStore(linearization_clock=lambda: _NOW)
    action = _workflow_action(_direct_action(), "recover_first")
    target = action.target_resource_ref
    ledger = StateStoreAutomationHoldLedger(audit, clock=lambda: _NOW)
    await ledger.issue(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        reason="compensation_failed",
    )
    assert await ledger.authorize_hold_scoped_dispatch(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        step_id="recover_first",
        hold_revision=1,
    )
    released = await _release_hold(
        audit,
        target_ref=target,
        action_id="recovery-action-other",
        hold_revision=1,
        admission_receipt_digest="sha256:" + "e" * 64,
        step_id="recover_other",
    )
    assert released is not None

    coordinator, lock = _coordinator(
        audit,
        hold_state_reader=ledger,
        hold_release_authorizations=ledger,
        commitment_store=await _workflow_commitment_store(),
    )
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=action)

    assert len(adapter.records) == 0
    assert result.outcome is not DirectApiExecutionOutcome.DISPATCHED
    denial = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
    )
    assert denial["rejection_reasons"] == ["hold_authorization_mismatch"]


async def test_a_hold_reissued_under_a_scoped_authorization_is_denied() -> None:
    audit = InMemoryStateStore(linearization_clock=lambda: _NOW)
    action = _workflow_action(_direct_action(), "recover_first")
    target = action.target_resource_ref
    ledger = StateStoreAutomationHoldLedger(audit, clock=lambda: _NOW)
    await ledger.issue(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        reason="compensation_failed",
    )
    assert await ledger.authorize_hold_scoped_dispatch(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        step_id="recover_first",
        hold_revision=1,
    )
    released = await _release_hold(
        audit,
        target_ref=target,
        action_id="recovery-action-other",
        hold_revision=1,
        admission_receipt_digest="sha256:" + "e" * 64,
        step_id="recover_other",
    )
    assert released is not None
    await ledger.issue(
        target_ref=target,
        process_id=_HOLD_PROCESS_ID,
        reason="compensation_failed_again",
    )

    coordinator, lock = _coordinator(
        audit,
        hold_state_reader=ledger,
        hold_release_authorizations=ledger,
        commitment_store=await _workflow_commitment_store(),
    )
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=action)

    assert len(adapter.records) == 0
    assert result.outcome is not DirectApiExecutionOutcome.DISPATCHED
    denial = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
    )
    assert sorted(denial["rejection_reasons"]) == [
        "active_hold",
        "hold_authorization_mismatch",
    ]


async def test_an_unreadable_dispatch_authorization_fences_dispatch_closed() -> None:
    audit = InMemoryStateStore(linearization_clock=lambda: _NOW)
    action = _workflow_action(_direct_action(), "recover_first")
    ledger = StateStoreAutomationHoldLedger(audit, clock=lambda: _NOW)
    await ledger.issue(
        target_ref=action.target_resource_ref,
        process_id=_HOLD_PROCESS_ID,
        reason="compensation_failed",
    )
    await ledger.authorize_hold_scoped_dispatch(
        target_ref=action.target_resource_ref,
        process_id=_HOLD_PROCESS_ID,
        step_id="recover_first",
        hold_revision=1,
    )
    key = next(
        stored
        for stored in audit._state
        if stored.startswith("workflow:automation-hold-dispatch-authorization:")
    )
    record = await audit.read_state(key)
    assert record is not None
    await audit.write_state(key, {**dict(record), "authorization_kind": "forged"})

    coordinator, lock = _coordinator(
        audit,
        hold_state_reader=ledger,
        hold_release_authorizations=ledger,
        commitment_store=await _workflow_commitment_store(),
    )
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=action)

    assert len(adapter.records) == 0
    assert result.outcome is not DirectApiExecutionOutcome.DISPATCHED
    denial = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
    )
    assert denial["rejection_reasons"] == ["unreadable_state"]
