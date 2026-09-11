"""Actual executor call-site coverage for the shared safeguard lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
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
from fdai.shared.contracts.models import ExecutionPath, WorkflowActionRef
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingDirectApiExecutor,
    RecordingRemediationPrPublisher,
    RecordingToolExecutor,
)

from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.executor.test_executor import _action as _pr_action
from tests.core.executor.test_executor import _rule
from tests.core.executor.test_tool_call_executor import _action as _tool_action

_NOW = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40
_ROOT = Path(__file__).resolve().parents[5]


def _coordinator(
    audit: InMemoryStateStore,
    *,
    hold_state_reader: object | None = None,
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
        hold_state_reader=hold_state_reader,  # type: ignore[arg-type]
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
    audit = InMemoryStateStore()
    reader = _StaticHoldReader(
        {
            "state": "released",
            "revision": 9,
            "fencing_generation": 2,
            "release_receipt": {
                "receipt_digest": "sha256:" + "b" * 64,
                "released_hold_revision": 1,
            },
        }
    )
    coordinator, lock = _coordinator(audit, hold_state_reader=reader)
    adapter = RecordingToolExecutor()
    executor = ToolCallShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=_tool_action())

    assert len(adapter.records) == 0
    assert result.outcome is not ToolCallExecutionOutcome.DISPATCHED
    denial = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
    )
    assert "hold_reissued_after_release" in denial["rejection_reasons"]


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
    audit = InMemoryStateStore()
    reader = _StaticHoldReader(
        {
            "state": "released",
            "revision": 2,
            "fencing_generation": 2,
            "release_receipt": {
                "receipt_digest": "sha256:" + "b" * 64,
                "released_hold_revision": 1,
            },
        }
    )
    coordinator, lock = _coordinator(audit, hold_state_reader=reader)
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    result = await executor.execute(action=_direct_action())

    assert result.outcome is DirectApiExecutionOutcome.DISPATCHED
    assert len(adapter.records) == 1
    assert not any(
        row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
        for row in audit.audit_entries
    )
