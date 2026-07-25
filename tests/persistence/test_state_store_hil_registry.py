"""StateStore-backed HIL registry projection and decision tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.delivery.persistence.state_store_hil_registry import (
    StateStoreHilApprovalRegistry,
    add_pending_approval,
)
from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilItemAlreadyResolvedError,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def _seed(store: InMemoryStateStore) -> None:
    await store.write_state(
        "hil_park:approval-1",
        {
            "status": "pending",
            "approval_id": "approval-1",
            "idempotency_key": "event-1::rule-1::resource-1",
            "action_type": "remediate.tag-add",
            "submitter_oid": "submitter-1",
            "correlation_id": "corr-1",
            "parked_at": "2026-07-15T00:00:00+00:00",
            "execution_path": "pr_native",
            "action": {
                "event_id": "00000000-0000-0000-0000-000000000001",
                "action_id": "00000000-0000-0000-0000-000000000002",
                "action_type": "remediate.tag-add",
                "target_resource_ref": "resource:example/one",
                "citing_rules": ["rule-1"],
            },
        },
    )
    await add_pending_approval(store, "approval-1")
    await add_pending_approval(store, "approval-1")


@pytest.mark.asyncio
async def test_registry_satisfies_protocol_and_projects_park() -> None:
    store = InMemoryStateStore()
    await _seed(store)
    registry = StateStoreHilApprovalRegistry(store=store)

    assert isinstance(registry, HilApprovalRegistry)
    pending = await registry.list_pending()
    assert len(pending) == 1
    assert pending[0].approval_id == "approval-1"
    assert pending[0].submitter_oid == "submitter-1"
    assert pending[0].citing_rule_ids == ("rule-1",)
    assert pending[0].requested_at == datetime(2026, 7, 15, tzinfo=UTC)


@pytest.mark.asyncio
async def test_registry_records_idempotent_decision_and_rejects_conflict() -> None:
    store = InMemoryStateStore()
    await _seed(store)
    registry = StateStoreHilApprovalRegistry(store=store)
    key = "event-1::rule-1::resource-1"

    first = await registry.record_decision(
        idempotency_key=key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid="approver-1",
        justification="Reviewed by the on-call approver.",
    )
    replay = await registry.record_decision(
        idempotency_key=key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid="approver-1",
        justification="Reviewed by the on-call approver.",
    )

    assert first.already_recorded is False
    assert first.delivered is False
    assert replay.already_recorded is True
    assert replay.receipt_ref == first.receipt_ref
    recovered = await registry.get_decision_by_approval_id("approval-1")
    assert recovered is not None
    assert recovered.idempotency_key == key
    assert recovered.delivered is False

    undelivered = await registry.list_undelivered()
    assert tuple(item.idempotency_key for item in undelivered) == (key,)
    delivered = await registry.record_delivery_attempt(
        idempotency_key=key,
        delivered=True,
        max_attempts=8,
    )
    assert delivered.delivered is True
    assert delivered.delivery_attempts == 1
    assert await registry.list_undelivered() == ()
    recovered_after_delivery = await registry.get_decision_by_approval_id("approval-1")
    assert recovered_after_delivery is not None
    assert recovered_after_delivery.delivered is True
    stale_failure = await registry.record_delivery_attempt(
        idempotency_key=key,
        delivered=False,
        error_code="publish:TimeoutError",
        max_attempts=8,
    )
    assert stale_failure.delivered is True
    assert stale_failure.delivery_attempts == 1
    assert await registry.list_pending() == ()
    with pytest.raises(HilItemAlreadyResolvedError):
        await registry.record_decision(
            idempotency_key=key,
            decision=HilApprovalDecision.REJECT,
            approver_oid="approver-2",
        )
