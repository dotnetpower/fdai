from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.delivery.persistence.state_store_hil_registry import (
    StateStoreHilApprovalRegistry,
)
from fdai.delivery.persistence.workflow_approval import (
    StateStoreWorkflowApprovalProvider,
)
from fdai.shared.providers.hil_registry import HilApprovalDecision
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


async def _request(provider: StateStoreWorkflowApprovalProvider, *, at: datetime = _NOW):
    return await provider.ensure_requested(
        process_id="process-1",
        step_id="board_approval",
        correlation_id="correlation-1",
        target_resource_id="resource-1",
        requester_principal="requester-1",
        required_role="approver",
        quorum=2,
        no_self_approval=True,
        timeout_seconds=120,
        requested_at=at,
    )


async def test_workflow_approval_reuses_hil_queue_and_resolves_durable_receipts() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = StateStoreHilApprovalRegistry(store=store)

    initial = await _request(provider)
    pending = await registry.list_pending()
    assert len(pending) == 2
    assert initial.requested_at == _NOW
    assert all(item.action_kind == "workflow.approval" for item in pending)

    for item, approver in zip(pending, ("operator-a", "operator-b"), strict=True):
        receipt = await registry.record_decision(
            idempotency_key=item.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid=approver,
        )
        assert receipt.delivered

    resumed = await _request(provider, at=_NOW + timedelta(seconds=30))
    assert resumed.requested_at == _NOW
    assert {decision.principal for decision in resumed.decisions} == {
        "operator-a",
        "operator-b",
    }
    assert await registry.list_undelivered() == ()


async def test_workflow_approval_timeout_is_persisted_and_closes_pending_slots() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = StateStoreHilApprovalRegistry(store=store)
    snapshot = await _request(provider)

    assert await provider.mark_timed_out(
        process_id=snapshot.process_id,
        step_id=snapshot.step_id,
        expected_revision=snapshot.revision,
        timed_out_at=_NOW + timedelta(seconds=121),
    )

    timed_out = await _request(provider, at=_NOW + timedelta(seconds=130))
    assert timed_out.timed_out
    assert timed_out.revision == 2
    assert await registry.list_pending() == ()
