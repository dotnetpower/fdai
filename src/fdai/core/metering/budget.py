"""The model budget: one declared ceiling for every LLM path.

``cost-model.md`` requires the model budget to be a ceiling - overflow
degrades to a cheaper path or to HIL, never to uncapped inference. This
module owns that ceiling for the whole control plane so the
conversational port and the event pipeline enforce one concept rather
than each inventing its own.

The budget is denominated in microUSD, the same unit
:class:`~fdai.core.task_worker.models.TaskWorkerBudget` uses, and is
measured against :class:`~fdai.core.metering.pricing.PricingTable`. Call
caps sit alongside the cost caps as the fail-safe: a model with no
configured price yields no cost, so a cost-only ceiling would be no
ceiling at all for exactly the model nobody priced.

:class:`BudgetLedger` is a DI seam like every other durable-state seam.
The upstream :class:`InMemoryBudgetLedger` is process-local, so a restart
resets the ceiling; a deployment that needs the ceiling to survive a
restart binds a durable implementation at the composition root.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol, runtime_checkable

#: Distinct correlations the in-memory ledger tracks. A budget whose call
#: ceiling exceeds this could have a spent correlation evicted, which
#: would refund it, so such a budget is rejected at construction.
MAX_TRACKED_CORRELATIONS: Final[int] = 1_024

_MICROS_PER_UNIT: Final[Decimal] = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class ModelBudget:
    """A pre-declared ceiling on model spend.

    The per-correlation bounds are always on: they stop one unit of work
    from spending without limit, which is the failure a ceiling exists to
    prevent.

    The fleet-wide totals are ``None`` until declared. A total that never
    resets is not a budget on a long-running process, it is a kill
    switch: after N calls every later event would degrade to a human
    forever, and nobody declared that. A deployment that wants a fleet
    ceiling states it in the open at the composition root, against a
    window it also resets.
    """

    max_calls_per_correlation: int = 1
    max_cost_microusd_per_correlation: int = 50_000
    max_calls_total: int | None = None
    max_cost_microusd_total: int | None = None

    def __post_init__(self) -> None:
        if self.max_calls_per_correlation < 0:
            raise ValueError("model budget call limits MUST be non-negative")
        if self.max_cost_microusd_per_correlation < 0:
            raise ValueError("model budget cost limits MUST be non-negative")
        if self.max_calls_total is not None:
            if self.max_calls_total < 0:
                raise ValueError("model budget call limits MUST be non-negative")
            if self.max_calls_per_correlation > self.max_calls_total:
                raise ValueError("per-correlation call budget MUST fit the total call budget")
            if self.max_calls_total > MAX_TRACKED_CORRELATIONS:
                # Beyond the tracked map an eviction could drop a spent
                # correlation and refund it, so a declared total would not
                # hold. Reject it rather than enforce it loosely.
                raise ValueError(
                    f"total call budget MUST NOT exceed {MAX_TRACKED_CORRELATIONS} "
                    "tracked correlations"
                )
        if self.max_cost_microusd_total is not None:
            if self.max_cost_microusd_total < 0:
                raise ValueError("model budget cost limits MUST be non-negative")
            if self.max_cost_microusd_per_correlation > self.max_cost_microusd_total:
                raise ValueError("per-correlation cost budget MUST fit the total cost budget")


@dataclass(frozen=True, slots=True)
class BudgetSpend:
    """What one correlation has consumed against the declared ceiling."""

    calls: int = 0
    cost_microusd: int = 0


@runtime_checkable
class BudgetLedger(Protocol):
    """Account for model spend against a :class:`ModelBudget`.

    Async by contract because a durable implementation is I/O-bound.
    Implementations MUST be deterministic for a given charge sequence, so
    a recorded decision replays to the same allow / deny outcome.
    """

    async def allows(self, correlation_id: str) -> bool:
        """Return whether another call fits every declared bound."""
        ...

    async def charge(self, correlation_id: str, *, calls: int, cost_microusd: int) -> None:
        """Add consumption. MUST NOT refund: both arguments are non-negative."""
        ...

    async def spend(self, correlation_id: str) -> BudgetSpend:
        """Return what ``correlation_id`` has consumed so far."""
        ...


class InMemoryBudgetLedger:
    """Upstream default: process-local, deterministic, bounded accounting.

    Non-durable on purpose, like
    :class:`~fdai.core.metering.sink.InMemoryMeteringSink`: it makes the
    ceiling work out of the box and a restart resets it. The correlation
    map cannot overflow while budget remains, because each charge adds at
    most one key and the total call budget is capped at the map's size.
    """

    __slots__ = ("_budget", "_per_correlation", "_total")

    def __init__(self, budget: ModelBudget | None = None) -> None:
        self._budget = budget or ModelBudget()
        self._per_correlation: dict[str, BudgetSpend] = {}
        self._total = BudgetSpend()

    @property
    def budget(self) -> ModelBudget:
        return self._budget

    async def allows(self, correlation_id: str) -> bool:
        spent = self._per_correlation.get(correlation_id, BudgetSpend())
        budget = self._budget
        if budget.max_calls_total is not None and self._total.calls >= budget.max_calls_total:
            return False
        if (
            budget.max_cost_microusd_total is not None
            and self._total.cost_microusd >= budget.max_cost_microusd_total
        ):
            return False
        return (
            spent.calls < budget.max_calls_per_correlation
            and spent.cost_microusd < budget.max_cost_microusd_per_correlation
        )

    async def charge(self, correlation_id: str, *, calls: int, cost_microusd: int) -> None:
        if calls < 0 or cost_microusd < 0:
            raise ValueError("model budget charges MUST be non-negative")
        self._total = BudgetSpend(
            calls=self._total.calls + calls,
            cost_microusd=self._total.cost_microusd + cost_microusd,
        )
        if (
            correlation_id not in self._per_correlation
            and len(self._per_correlation) >= MAX_TRACKED_CORRELATIONS
        ):
            self._per_correlation.pop(next(iter(self._per_correlation)))
        prior = self._per_correlation.get(correlation_id, BudgetSpend())
        self._per_correlation[correlation_id] = BudgetSpend(
            calls=prior.calls + calls,
            cost_microusd=prior.cost_microusd + cost_microusd,
        )

    async def spend(self, correlation_id: str) -> BudgetSpend:
        return self._per_correlation.get(correlation_id, BudgetSpend())


def to_microusd(cost: Decimal | None) -> int:
    """Convert a priced cost to whole microUSD, rounding up.

    Rounding up keeps the ceiling conservative: a fraction of a microUSD
    that rounded to zero would let an unbounded number of tiny calls
    through a cost budget.
    """
    if cost is None:
        return 0
    micros = cost * _MICROS_PER_UNIT
    whole = int(micros)
    return whole + 1 if micros > whole else whole


__all__ = [
    "MAX_TRACKED_CORRELATIONS",
    "BudgetLedger",
    "BudgetSpend",
    "InMemoryBudgetLedger",
    "ModelBudget",
    "to_microusd",
]
