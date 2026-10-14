"""Persistent model-budget contracts over the existing StateStore seam."""

from __future__ import annotations

import asyncio
import hashlib

import pytest
from fdai.core.metering.budget import BudgetSpend, ModelBudget
from fdai.delivery.persistence.state_store_model_budget import StateStoreBudgetLedger
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_restart_keeps_the_original_call_reservation() -> None:
    store = InMemoryStateStore()
    assert await StateStoreBudgetLedger(store).reserve(
        "correlation-example", calls=1, cost_microusd=0
    )
    restarted = StateStoreBudgetLedger(store)
    assert await restarted.spend("correlation-example") == BudgetSpend(calls=1)
    assert not await restarted.reserve("correlation-example", calls=1, cost_microusd=0)
    assert await restarted.reserve("different-correlation", calls=1, cost_microusd=0)


async def test_two_replicas_admit_only_one_call() -> None:
    store = InMemoryStateStore()
    results = await asyncio.gather(
        *(
            StateStoreBudgetLedger(store).reserve("shared-correlation", calls=1, cost_microusd=0)
            for _replica in range(8)
        )
    )
    assert sum(results) == 1


async def test_measured_cost_and_no_refund_survive_restart() -> None:
    store = InMemoryStateStore()
    budget = ModelBudget(max_calls_per_correlation=4, max_cost_microusd_per_correlation=50)
    ledger = StateStoreBudgetLedger(store, budget)
    assert await ledger.reserve("correlation-example", calls=1, cost_microusd=0)
    await ledger.charge("correlation-example", calls=0, cost_microusd=60)
    restarted = StateStoreBudgetLedger(store, budget)
    assert await restarted.spend("correlation-example") == BudgetSpend(1, 60)
    assert not await restarted.allows("correlation-example")
    with pytest.raises(ValueError, match="non-negative integers"):
        await restarted.charge("correlation-example", calls=0, cost_microusd=-1)


async def test_policy_substitution_cannot_reset_consumption() -> None:
    store = InMemoryStateStore()
    assert await StateStoreBudgetLedger(store).reserve(
        "correlation-example", calls=1, cost_microusd=0
    )
    replaced = StateStoreBudgetLedger(store, ModelBudget(max_calls_per_correlation=2))
    with pytest.raises(ValueError, match="pinned policy"):
        await replaced.reserve("correlation-example", calls=1, cost_microusd=0)


@pytest.mark.parametrize("counter", [True, -1, "1"])
async def test_corrupt_spend_never_receives_fresh_allowance(counter: object) -> None:
    store = InMemoryStateStore()
    ledger = StateStoreBudgetLedger(store)
    key = f"model_budget:conversation:{hashlib.sha256(b'correlation-example').hexdigest()}"
    await store.write_state(
        key,
        {
            "schema_version": "1.0.0",
            "policy_digest": ledger.policy_digest,
            "revision": 1,
            "calls": counter,
            "cost_microusd": 0,
        },
    )
    with pytest.raises(ValueError, match="invalid"):
        await ledger.reserve("correlation-example", calls=1, cost_microusd=0)


def test_declared_fleet_limit_is_not_silently_ignored() -> None:
    with pytest.raises(ValueError, match="fleet-budget binding"):
        StateStoreBudgetLedger(InMemoryStateStore(), ModelBudget(max_calls_total=2))


async def test_store_failure_does_not_fall_back_to_process_local_allowance() -> None:
    class UnavailableStore(InMemoryStateStore):
        async def read_state(self, key: str):
            raise RuntimeError("state store unavailable")

    ledger = StateStoreBudgetLedger(UnavailableStore())
    with pytest.raises(RuntimeError, match="state store unavailable"):
        await ledger.reserve("correlation-example", calls=1, cost_microusd=0)


async def test_persistent_insert_contention_is_bounded() -> None:
    class ContendedStore(InMemoryStateStore):
        attempts = 0

        async def write_state_if_absent(self, key: str, value):
            self.attempts += 1
            return False

    store = ContendedStore()
    with pytest.raises(RuntimeError, match="changed concurrently"):
        await StateStoreBudgetLedger(store).reserve("correlation-example", calls=1, cost_microusd=0)
    assert store.attempts == 4
