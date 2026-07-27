"""The declared model ceiling, enforced for every LLM path.

``cost-model.md`` requires the budget to be a ceiling: overflow degrades
to a cheaper path or to a human, never to uncapped inference. These
tests pin the properties that make that claim true rather than merely
asserted - the ledger denies, never refunds, and stays bounded.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fdai.core.metering.budget import (
    MAX_TRACKED_CORRELATIONS,
    BudgetSpend,
    InMemoryBudgetLedger,
    ModelBudget,
    to_microusd,
)


def test_defaults_bound_one_unit_of_work_and_declare_no_fleet_ceiling() -> None:
    """An undeclared total would be a kill switch, not a budget."""
    budget = ModelBudget()

    assert budget.max_calls_per_correlation == 1
    assert budget.max_cost_microusd_per_correlation == 50_000
    assert budget.max_calls_total is None
    assert budget.max_cost_microusd_total is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"max_calls_per_correlation": -1}, "non-negative"),
        ({"max_calls_per_correlation": 4, "max_calls_total": 2}, "fit the total call budget"),
        ({"max_calls_total": MAX_TRACKED_CORRELATIONS + 1}, "tracked correlations"),
        ({"max_cost_microusd_total": -1}, "cost limits MUST be non-negative"),
        (
            {"max_cost_microusd_per_correlation": 10, "max_cost_microusd_total": 5},
            "fit the total cost budget",
        ),
    ),
)
def test_an_incoherent_ceiling_is_rejected(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ModelBudget(**kwargs)


async def test_the_cost_bound_denies_even_while_calls_remain() -> None:
    ledger = InMemoryBudgetLedger(
        ModelBudget(
            max_calls_per_correlation=8,
            max_calls_total=8,
            max_cost_microusd_per_correlation=1_000,
            max_cost_microusd_total=1_000,
        )
    )

    await ledger.charge("c1", calls=1, cost_microusd=1_000)

    assert await ledger.allows("c1") is False
    # A different correlation is denied too: the declared total is spent.
    assert await ledger.allows("c2") is False


async def test_an_undeclared_total_never_becomes_a_silent_kill_switch() -> None:
    """A long-running process MUST NOT stop reasoning because nobody declared."""
    ledger = InMemoryBudgetLedger(ModelBudget())

    for index in range(5_000):
        await ledger.charge(f"event-{index}", calls=1, cost_microusd=1_000)

    assert await ledger.allows("a-brand-new-event") is True
    # The always-on per-correlation bound still holds for a repeat.
    assert await ledger.allows("event-4999") is False


async def test_the_call_bound_denies_when_nothing_is_priced() -> None:
    """A pricing gap MUST NOT become a budget gap."""
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=1, max_calls_total=4))

    await ledger.charge("c1", calls=1, cost_microusd=0)

    assert await ledger.allows("c1") is False
    assert await ledger.allows("c2") is True


async def test_spend_is_never_refunded_by_eviction() -> None:
    ledger = InMemoryBudgetLedger(
        ModelBudget(max_calls_per_correlation=1, max_calls_total=MAX_TRACKED_CORRELATIONS)
    )
    await ledger.charge("victim", calls=1, cost_microusd=0)

    for index in range(MAX_TRACKED_CORRELATIONS - 1):
        await ledger.charge(f"c{index}", calls=1, cost_microusd=0)

    assert await ledger.allows("victim") is False


async def test_a_negative_charge_is_rejected_rather_than_refunding() -> None:
    ledger = InMemoryBudgetLedger()

    with pytest.raises(ValueError, match="non-negative"):
        await ledger.charge("c1", calls=-1, cost_microusd=0)
    with pytest.raises(ValueError, match="non-negative"):
        await ledger.charge("c1", calls=0, cost_microusd=-1)


async def test_spend_reports_what_a_correlation_consumed() -> None:
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=4, max_calls_total=8))

    await ledger.charge("c1", calls=1, cost_microusd=120)
    await ledger.charge("c1", calls=1, cost_microusd=80)

    assert await ledger.spend("c1") == BudgetSpend(calls=2, cost_microusd=200)
    assert await ledger.spend("unseen") == BudgetSpend()


@pytest.mark.parametrize(
    ("cost", "expected"),
    (
        (None, 0),
        (Decimal("0"), 0),
        (Decimal("0.000001"), 1),
        # Rounds up: a fraction that truncated to zero would let an
        # unbounded number of tiny calls through a cost ceiling.
        (Decimal("0.0000001"), 1),
        (Decimal("1.5"), 1_500_000),
    ),
)
def test_pricing_converts_to_conservative_microusd(cost: Decimal | None, expected: int) -> None:
    assert to_microusd(cost) == expected


async def test_the_charging_sink_records_first_then_charges_what_it_recorded() -> None:
    """One charge point: whatever metering records is what the budget spends."""
    from datetime import UTC, datetime

    from fdai.core.metering.budget import BudgetChargingMeteringSink
    from fdai.core.metering.records import InvocationMode, InvocationScope, LlmInvocation
    from fdai.core.metering.sink import InMemoryMeteringSink
    from fdai.core.metering.usage import TokenUsage

    inner = InMemoryMeteringSink()
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=4))
    sink = BudgetChargingMeteringSink(inner, ledger)

    await sink.record(
        LlmInvocation(
            occurred_at=datetime.now(UTC),
            correlation_id="corr-1",
            capability_id="t2.conversation.synthesis",
            model_key="gpt-test",
            tier="T2",
            mode=InvocationMode.SHADOW,
            usage=TokenUsage(1_000, 500),
            usage_scope=InvocationScope.OPERATOR_CHAT,
            cost=Decimal("0.25"),
            currency="USD",
        )
    )

    assert len(await inner.invocations()) == 1
    assert (await ledger.spend("corr-1")).cost_microusd == 250_000


async def test_a_ledger_failure_never_breaks_the_metering_write() -> None:
    """Metering is a side-channel; a budget hiccup MUST NOT lose the record."""
    from datetime import UTC, datetime

    from fdai.core.metering.budget import BudgetChargingMeteringSink
    from fdai.core.metering.records import InvocationMode, InvocationScope, LlmInvocation
    from fdai.core.metering.sink import InMemoryMeteringSink
    from fdai.core.metering.usage import TokenUsage

    class _BrokenLedger:
        async def allows(self, correlation_id: str) -> bool:
            return True

        async def charge(self, correlation_id: str, *, calls: int, cost_microusd: int) -> None:
            raise RuntimeError("ledger backend down")

        async def spend(self, correlation_id: str) -> BudgetSpend:
            return BudgetSpend()

    inner = InMemoryMeteringSink()
    sink = BudgetChargingMeteringSink(inner, _BrokenLedger())

    await sink.record(
        LlmInvocation(
            occurred_at=datetime.now(UTC),
            correlation_id="corr-1",
            capability_id="t2.conversation.synthesis",
            model_key="gpt-test",
            tier="T2",
            mode=InvocationMode.SHADOW,
            usage=TokenUsage(1, 1),
            usage_scope=InvocationScope.OPERATOR_CHAT,
        )
    )

    assert len(await inner.invocations()) == 1


def test_an_empty_in_memory_sink_is_falsy_so_defaults_use_is_none() -> None:
    """Pins the trap that silently discarded an injected sink.

    ``InMemoryMeteringSink`` defines ``__len__``, so an empty one is
    falsy and ``sink or Default()`` throws the caller's sink away. Any
    default fallback for it MUST test ``is None``.
    """
    from fdai.core.metering.sink import InMemoryMeteringSink

    assert bool(InMemoryMeteringSink()) is False
