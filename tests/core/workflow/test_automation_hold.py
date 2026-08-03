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
