from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.chaos.run_state import ChaosRunSnapshot, ChaosRunState
from fdai.core.chaos.run_store import ChaosRunConflictError, ChaosRunStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


async def test_create_is_idempotent_and_transition_is_durable() -> None:
    state = InMemoryStateStore()
    store = ChaosRunStore(state_store=state)
    created = await store.create(run_id="run-1", at=_NOW)
    duplicate = await store.create(run_id="run-1", at=_NOW + timedelta(seconds=1))
    assert duplicate == created

    updated = await store.transition(
        created,
        target=ChaosRunState.IMPACT_CHECKED,
        idempotency_key="run-1:impact",
        at=_NOW + timedelta(seconds=1),
    )
    assert await store.get("run-1") == updated
    assert await state.verify_chain()


async def test_transition_rejects_stale_snapshot_revision() -> None:
    state = InMemoryStateStore()
    store = ChaosRunStore(state_store=state)
    created = await store.create(run_id="run-1", at=_NOW)
    await store.transition(
        created,
        target=ChaosRunState.IMPACT_CHECKED,
        idempotency_key="run-1:impact",
        at=_NOW + timedelta(seconds=1),
    )
    stale = ChaosRunSnapshot(
        run_id="run-1",
        state=ChaosRunState.PLANNED,
        revision=0,
        updated_at=_NOW,
        last_idempotency_key="different",
    )
    with pytest.raises(ChaosRunConflictError, match="concurrently"):
        await store.transition(
            stale,
            target=ChaosRunState.IMPACT_CHECKED,
            idempotency_key="run-1:stale",
            at=_NOW + timedelta(seconds=2),
        )


async def test_transition_reconciles_duplicate_retry() -> None:
    store = ChaosRunStore(state_store=InMemoryStateStore())
    planned = await store.create(run_id="run-1", at=_NOW)
    first = await store.transition(
        planned,
        target=ChaosRunState.IMPACT_CHECKED,
        idempotency_key="run-1:impact_checked",
        at=_NOW,
    )
    retried = await store.transition(
        planned,
        target=ChaosRunState.IMPACT_CHECKED,
        idempotency_key="run-1:impact_checked",
        at=_NOW,
    )
    assert retried == first
