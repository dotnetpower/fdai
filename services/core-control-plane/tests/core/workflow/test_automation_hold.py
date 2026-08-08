from __future__ import annotations

from fdai.core.workflow import StateStoreAutomationHoldLedger
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_issued_hold_is_target_scoped_and_audited() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAutomationHoldLedger(store)

    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    assert await ledger.is_held(target_ref="resource-1")
    assert not await ledger.is_held(target_ref="resource-2")
    assert store.audit_entries[0]["entry"]["action_kind"] == ("workflow.automation_hold.issued")
    assert "resource-1" not in str(store.audit_entries[0])


async def test_malformed_hold_state_fails_closed() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAutomationHoldLedger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    key = next(iter(store._state))
    await store.write_state(key, {"state": "unknown"})

    assert await ledger.is_held(target_ref="resource-1")


async def test_only_matching_compensation_can_release_verified_hold() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAutomationHoldLedger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    assert not await ledger.recovery_eligible(
        target_ref="resource-1",
        process_id="process-other",
        step_id="compensate_start",
    )
    assert not await ledger.recovery_eligible(
        target_ref="resource-1",
        process_id="process-1",
        step_id="ordinary_step",
    )
    assert await ledger.recovery_eligible(
        target_ref="resource-1",
        process_id="process-1",
        step_id="compensate_start",
    )

    assert await ledger.release_verified(
        target_ref="resource-1",
        process_id="process-1",
        recovery_receipt_ref="workflow-outcome:verified",
    )
    assert not await ledger.is_held(target_ref="resource-1")
    assert not await ledger.release_verified(
        target_ref="resource-1",
        process_id="process-1",
        recovery_receipt_ref="workflow-outcome:second",
    )


async def test_reissued_hold_rejects_stale_process_release() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAutomationHoldLedger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="first_failure",
    )
    assert await ledger.release_verified(
        target_ref="resource-1",
        process_id="process-1",
        recovery_receipt_ref="workflow-outcome:first",
    )

    await ledger.issue(
        target_ref="resource-1",
        process_id="process-2",
        reason="second_failure",
    )

    assert await ledger.is_held(target_ref="resource-1")
    assert not await ledger.release_verified(
        target_ref="resource-1",
        process_id="process-1",
        recovery_receipt_ref="workflow-outcome:stale",
    )
