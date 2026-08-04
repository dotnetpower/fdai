from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.hil_resume.load_control import (
    ApprovalLoadPolicy,
    ApprovalReminderDispatcher,
)
from fdai.delivery.persistence.state_store_hil_registry import (
    StateStoreHilApprovalRegistry,
)
from fdai.delivery.persistence.workflow_approval import (
    StateStoreWorkflowApprovalProvider,
)
from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilDuplicateApproverError,
    HilItemNotFoundError,
)
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _registry(store: InMemoryStateStore) -> StateStoreHilApprovalRegistry:
    return StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)


def _load_policy() -> ApprovalLoadPolicy:
    return ApprovalLoadPolicy.from_mapping(
        {
            "schema_version": "1.0.0",
            "group_window_seconds": 300,
            "max_pending_per_assignee": 3,
            "reminder_offsets_seconds": [60],
            "quiet_hours_utc": {"start": "22:00", "end": "06:00"},
            "urgent_severities": ["critical"],
            "scan_limit": 100,
            "worker_interval_seconds": 30,
        }
    )


async def _request(
    provider: StateStoreWorkflowApprovalProvider,
    *,
    at: datetime = _NOW,
    attempt: int = 1,
):
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
        attempt=attempt,
    )


async def test_workflow_approval_reuses_hil_queue_and_resolves_durable_receipts() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)

    initial = await _request(provider)
    pending = await registry.list_pending()
    assert len(pending) == 2
    assert initial.requested_at == _NOW
    assert all(item.action_kind == "workflow.approval" for item in pending)
    assert all(item.metadata["required_role"] == "approver" for item in pending)

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
    decision_audits = [
        row["entry"]
        for row in store.audit_entries
        if row["entry"].get("action_kind") == "workflow.approval.decided"
    ]
    assert len(decision_audits) == 2
    assert all(row["actor"] == "Var" for row in decision_audits)


async def test_workflow_approval_timeout_is_persisted_and_closes_pending_slots() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
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


async def test_generic_expiry_worker_does_not_close_workflow_approval_slots() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    await _request(provider)
    dispatcher = ApprovalReminderDispatcher(
        state_store=store,
        channel=InMemoryHilChannel(),
        policy=_load_policy(),
        clock=lambda: _NOW + timedelta(seconds=121),
    )

    assert await dispatcher.expire_due() == 0
    parks, _ = await store.read_state_page("hil_park:", limit=10, offset=0)
    assert {park["status"] for park in parks} == {"pending"}


async def test_workflow_timeout_recovers_failed_slot_projection() -> None:
    class SlotProjectionFailingStore(InMemoryStateStore):
        fail_slot_projection = True

        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value: dict[str, object],
            *,
            expected_revision: int,
            audit_entry: dict[str, object],
        ) -> bool:
            if (
                self.fail_slot_projection
                and key.startswith("hil_park:")
                and audit_entry.get("action_kind") == "workflow.approval.slot_timed_out"
            ):
                self.fail_slot_projection = False
                return False
            return await super().compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )

    store = SlotProjectionFailingStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    snapshot = await _request(provider)

    with pytest.raises(RuntimeError, match="left a pending slot"):
        await provider.mark_timed_out(
            process_id=snapshot.process_id,
            step_id=snapshot.step_id,
            expected_revision=snapshot.revision,
            timed_out_at=_NOW + timedelta(seconds=121),
        )

    timed_out = await _request(provider, at=_NOW + timedelta(seconds=130))
    parks, _ = await store.read_state_page("hil_park:", limit=10, offset=0)
    assert timed_out.timed_out
    assert {park["status"] for park in parks} == {"resolved"}
    assert {park["decision"] for park in parks} == {"timeout"}


async def test_workflow_approval_cancellation_closes_slots_and_rejects_late_decisions() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
    snapshot = await _request(provider)
    pending = await registry.list_pending()

    assert await provider.cancel_pending(
        process_id=snapshot.process_id,
        step_id=snapshot.step_id,
        cancelled_at=_NOW + timedelta(seconds=30),
    )

    cancelled = await _request(provider, at=_NOW + timedelta(seconds=40))
    assert cancelled.cancelled
    assert cancelled.revision == 2
    assert await registry.list_pending() == ()
    with pytest.raises(HilItemNotFoundError):
        await registry.record_decision(
            idempotency_key=pending[0].idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid="operator-a",
        )


async def test_workflow_cancellation_recovers_failed_slot_projection() -> None:
    class SlotProjectionFailingStore(InMemoryStateStore):
        fail_slot_projection = True

        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value: dict[str, object],
            *,
            expected_revision: int,
            audit_entry: dict[str, object],
        ) -> bool:
            if (
                self.fail_slot_projection
                and key.startswith("hil_park:")
                and audit_entry.get("action_kind") == "workflow.approval.slot_cancelled"
            ):
                self.fail_slot_projection = False
                return False
            return await super().compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )

    store = SlotProjectionFailingStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    snapshot = await _request(provider)

    with pytest.raises(RuntimeError, match="left a pending slot"):
        await provider.cancel_pending(
            process_id=snapshot.process_id,
            step_id=snapshot.step_id,
            cancelled_at=_NOW + timedelta(seconds=30),
        )

    cancelled = await _request(provider, at=_NOW + timedelta(seconds=40))
    parks, _ = await store.read_state_page("hil_park:", limit=10, offset=0)
    assert cancelled.cancelled
    assert {park["status"] for park in parks} == {"resolved"}
    assert {park["decision"] for park in parks} == {"cancel"}


async def test_cancellation_reconciliation_heals_timed_out_slots() -> None:
    class SlotProjectionFailingStore(InMemoryStateStore):
        fail_slot_projection = True

        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value: dict[str, object],
            *,
            expected_revision: int,
            audit_entry: dict[str, object],
        ) -> bool:
            if self.fail_slot_projection and key.startswith("hil_park:"):
                self.fail_slot_projection = False
                return False
            return await super().compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )

    store = SlotProjectionFailingStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    snapshot = await _request(provider)
    timed_out_at = _NOW + timedelta(seconds=121)
    with pytest.raises(RuntimeError, match="left a pending slot"):
        await provider.mark_timed_out(
            process_id=snapshot.process_id,
            step_id=snapshot.step_id,
            expected_revision=snapshot.revision,
            timed_out_at=timed_out_at,
        )

    assert await provider.cancel_pending(
        process_id=snapshot.process_id,
        step_id=snapshot.step_id,
        cancelled_at=_NOW + timedelta(seconds=130),
    )
    parks, _ = await store.read_state_page("hil_park:", limit=10, offset=0)
    assert {park["status"] for park in parks} == {"resolved"}
    assert {park["decision"] for park in parks} == {"timeout"}


async def test_workflow_approval_cancellation_fails_when_authoritative_state_is_missing() -> None:
    provider = StateStoreWorkflowApprovalProvider(InMemoryStateStore())

    assert not await provider.cancel_pending(
        process_id="missing-process",
        step_id="missing-approval",
        cancelled_at=_NOW,
    )


async def test_workflow_approval_rejects_duplicate_principal_across_slots() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
    await _request(provider)
    first, second = await registry.list_pending()

    await registry.record_decision(
        idempotency_key=first.idempotency_key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid="operator-a",
    )
    with pytest.raises(HilDuplicateApproverError):
        await registry.record_decision(
            idempotency_key=second.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid="OPERATOR-A",
        )

    still_pending = await registry.get_pending(second.idempotency_key)
    assert still_pending is not None
    await registry.record_decision(
        idempotency_key=second.idempotency_key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid="operator-b",
    )
    resumed = await _request(provider, at=_NOW + timedelta(seconds=30))
    assert {decision.principal for decision in resumed.decisions} == {
        "operator-a",
        "operator-b",
    }


async def test_workflow_approval_claim_retry_scales_with_quorum() -> None:
    class ContendedWorkflowStore(InMemoryStateStore):
        conflicts_remaining = 8

        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value: dict[str, object],
            *,
            expected_revision: int,
            audit_entry: dict[str, object],
        ) -> bool:
            if (
                self.conflicts_remaining > 0
                and key.startswith("workflow:approval:")
                and audit_entry.get("action_kind") == "workflow.approval.decided"
            ):
                self.conflicts_remaining -= 1
                current = await self.read_state(key)
                assert current is not None
                await self.write_state(
                    key,
                    {**dict(current), "revision": int(current["revision"]) + 1},
                )
                return False
            return await super().compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )

    store = ContendedWorkflowStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
    await provider.ensure_requested(
        process_id="process-high-quorum",
        step_id="board_approval",
        correlation_id="correlation-high-quorum",
        target_resource_id="resource-high-quorum",
        requester_principal="requester-1",
        required_role="approver",
        quorum=10,
        no_self_approval=True,
        timeout_seconds=120,
        requested_at=_NOW,
    )
    item = (await registry.list_pending())[0]

    receipt = await registry.record_decision(
        idempotency_key=item.idempotency_key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid="operator-a",
    )

    assert receipt.approver_oid == "operator-a"
    assert store.conflicts_remaining == 0


async def test_workflow_approval_refuses_decision_after_expiry() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
    await _request(provider)
    item = (await registry.list_pending())[0]

    with pytest.raises(HilItemNotFoundError):
        await registry.record_decision(
            idempotency_key=item.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid="operator-a",
            decided_at=_NOW + timedelta(seconds=121),
        )

    snapshot = await _request(provider, at=_NOW + timedelta(seconds=121))
    assert snapshot.decisions == ()


async def test_workflow_approval_queue_hides_expired_slots() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    current = _NOW
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: current)
    await _request(provider)
    assert len(await registry.list_pending()) == 2

    current = _NOW + timedelta(seconds=121)
    assert await registry.list_pending() == ()


async def test_workflow_approval_rejection_closes_every_quorum_slot() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
    await _request(provider)
    first, second = await registry.list_pending()

    await registry.record_decision(
        idempotency_key=first.idempotency_key,
        decision=HilApprovalDecision.REJECT,
        approver_oid="operator-a",
    )

    assert await registry.list_pending() == ()
    snapshot = await _request(provider, at=_NOW + timedelta(seconds=30))
    assert snapshot.decisions[0].decision == "rejected"
    with pytest.raises(HilItemNotFoundError):
        await registry.record_decision(
            idempotency_key=second.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid="operator-b",
        )

    second_attempt = await _request(
        provider,
        at=_NOW + timedelta(seconds=40),
        attempt=2,
    )
    assert second_attempt.attempt == 2
    assert second_attempt.decisions == ()
    assert len(await registry.list_pending()) == 2


async def test_timeout_cannot_overwrite_rejected_approval() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
    await _request(provider)
    first = (await registry.list_pending())[0]
    await registry.record_decision(
        idempotency_key=first.idempotency_key,
        decision=HilApprovalDecision.REJECT,
        approver_oid="operator-a",
    )
    rejected = await _request(provider, at=_NOW + timedelta(seconds=30))

    assert not await provider.mark_timed_out(
        process_id=rejected.process_id,
        step_id=rejected.step_id,
        expected_revision=rejected.revision,
        timed_out_at=_NOW + timedelta(seconds=121),
    )
    preserved = await _request(provider, at=_NOW + timedelta(seconds=130))
    assert not preserved.timed_out
    assert preserved.decisions[0].decision == "rejected"


async def test_timeout_cannot_overwrite_cancelled_approval() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    snapshot = await _request(provider)
    assert await provider.cancel_pending(
        process_id=snapshot.process_id,
        step_id=snapshot.step_id,
        cancelled_at=_NOW + timedelta(seconds=30),
    )
    cancelled = await _request(provider, at=_NOW + timedelta(seconds=40))

    assert not await provider.mark_timed_out(
        process_id=cancelled.process_id,
        step_id=cancelled.step_id,
        expected_revision=cancelled.revision,
        timed_out_at=_NOW + timedelta(seconds=121),
    )
    preserved = await _request(provider, at=_NOW + timedelta(seconds=130))
    assert preserved.cancelled
    assert not preserved.timed_out


async def test_workflow_approval_malformed_expiry_fails_closed() -> None:
    store = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
    await _request(provider)
    item = (await registry.list_pending())[0]
    state_key = item.metadata["workflow_state_key"]
    record = await store.read_state(state_key)
    assert record is not None
    await store.write_state(state_key, {**dict(record), "expires_at": "not-a-timestamp"})

    with pytest.raises(RuntimeError, match="expiry is malformed"):
        await registry.record_decision(
            idempotency_key=item.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid="operator-a",
        )


async def test_workflow_rejection_survives_sibling_slot_projection_failure() -> None:
    class SlotProjectionFailingStore(InMemoryStateStore):
        fail_slot_projection = True

        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value: dict[str, object],
            *,
            expected_revision: int,
            audit_entry: dict[str, object],
        ) -> bool:
            if (
                self.fail_slot_projection
                and key.startswith("hil_park:")
                and audit_entry.get("action_kind") == "workflow.approval.slot_rejected"
            ):
                self.fail_slot_projection = False
                return False
            return await super().compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )

    store = SlotProjectionFailingStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
    await _request(provider)
    first = (await registry.list_pending())[0]

    with pytest.raises(RuntimeError, match="left a pending slot"):
        await registry.record_decision(
            idempotency_key=first.idempotency_key,
            decision=HilApprovalDecision.REJECT,
            approver_oid="operator-a",
        )

    assert await registry.list_pending() == ()
    await _request(provider, at=_NOW + timedelta(seconds=30))
    parks, _ = await store.read_state_page("hil_park:", limit=10, offset=0)
    assert {park["status"] for park in parks} == {"resolved"}
    assert {park["decision"] for park in parks} == {"reject"}


async def test_workflow_decision_survives_receipt_projection_failure() -> None:
    class ProjectionFailingStore(InMemoryStateStore):
        fail_projection = True

        async def write_state_with_audit_if_absent(
            self,
            key: str,
            value: dict[str, object],
            audit_entry: dict[str, object],
        ) -> bool:
            if self.fail_projection and key.startswith("hil_decision:"):
                self.fail_projection = False
                raise RuntimeError("synthetic receipt projection failure")
            return await super().write_state_with_audit_if_absent(key, value, audit_entry)

    store = ProjectionFailingStore()
    provider = StateStoreWorkflowApprovalProvider(store)
    registry = _registry(store)
    await _request(provider)
    item = (await registry.list_pending())[0]

    with pytest.raises(RuntimeError, match="receipt projection failure"):
        await registry.record_decision(
            idempotency_key=item.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid="operator-a",
        )

    recovered = await registry.get_decision_by_approval_id(item.approval_id)
    assert recovered is not None
    assert recovered.approver_oid == "operator-a"
    snapshot = await _request(provider, at=_NOW + timedelta(seconds=10))
    assert snapshot.decisions[0].principal == "operator-a"

    replay = await registry.record_decision(
        idempotency_key=item.idempotency_key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid="OPERATOR-A",
    )
    assert replay.already_recorded
    assert replay.receipt_ref == recovered.receipt_ref
