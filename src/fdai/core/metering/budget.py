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

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol, runtime_checkable

from fdai.core.metering.records import LlmInvocation
from fdai.core.metering.sink import MeteringSink

_LOG = logging.getLogger(__name__)

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
    max_cost_microusd_per_correlation: int | None = 50_000
    max_calls_total: int | None = None
    max_cost_microusd_total: int | None = None

    def __post_init__(self) -> None:
        if self.max_calls_per_correlation < 0:
            raise ValueError("model budget call limits MUST be non-negative")
        if (
            self.max_cost_microusd_per_correlation is not None
            and self.max_cost_microusd_per_correlation < 0
        ):
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
            if (
                self.max_cost_microusd_per_correlation is not None
                and self.max_cost_microusd_per_correlation > self.max_cost_microusd_total
            ):
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

    async def reserve(self, correlation_id: str, *, calls: int, cost_microusd: int) -> bool:
        """Atomically take the allowance if it fits, else return ``False``.

        This is the gate. Checking with :meth:`allows` and then charging
        is a check-then-act race: two turns that read the same remaining
        allowance both proceed, and a declared ceiling of one call admits
        as many callers as happen to overlap. A durable implementation
        MUST make this a single operation (one conditional ``UPDATE``),
        never a read followed by a write.
        """
        ...

    async def allows(self, correlation_id: str) -> bool:
        """Return whether another call would fit. Advisory only.

        Safe for display - the ``escalation_available`` fact a turn
        states - but MUST NOT be used to admit a call. Use
        :meth:`reserve` for that.
        """
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
    ceiling work out of the box and a restart resets it.

    The correlation map is bounded, so it evicts. A declared *total*
    survives eviction because totals are counted separately and never
    evicted, which is why a total call budget above the map size is
    rejected at construction. A *per-correlation* limb does not: a
    correlation evicted behind ``MAX_TRACKED_CORRELATIONS`` others comes
    back with a fresh allowance. That is the intended reading of a
    per-unit-of-work ceiling, and it matters here because cost-only
    charges from the metering write add keys without consuming call
    budget, so keys can grow faster than calls.
    """

    __slots__ = ("_budget", "_per_correlation", "_total")

    def __init__(self, budget: ModelBudget | None = None) -> None:
        self._budget = budget or ModelBudget()
        self._per_correlation: dict[str, BudgetSpend] = {}
        self._total = BudgetSpend()

    @property
    def budget(self) -> ModelBudget:
        return self._budget

    async def reserve(self, correlation_id: str, *, calls: int, cost_microusd: int) -> bool:
        """Check and take in one step, with no ``await`` in between.

        Atomic by construction on an event loop: nothing can run between
        the test and the mutation, so two overlapping turns cannot both
        be admitted by the same remaining allowance.
        """
        if calls < 0 or cost_microusd < 0:
            raise ValueError("model budget charges MUST be non-negative")
        if not self._fits(correlation_id):
            return False
        self._apply(correlation_id, calls=calls, cost_microusd=cost_microusd)
        return True

    async def allows(self, correlation_id: str) -> bool:
        return self._fits(correlation_id)

    def _fits(self, correlation_id: str) -> bool:
        spent = self._per_correlation.get(correlation_id, BudgetSpend())
        budget = self._budget
        if budget.max_calls_total is not None and self._total.calls >= budget.max_calls_total:
            return False
        if (
            budget.max_cost_microusd_total is not None
            and self._total.cost_microusd >= budget.max_cost_microusd_total
        ):
            return False
        if spent.calls >= budget.max_calls_per_correlation:
            return False
        # ``None`` means the deployment did not declare a per-correlation
        # money limb. A caller that cannot observe cost (the pipeline
        # tier meters through its provider, not through this ledger)
        # would otherwise carry a ceiling that can never fire.
        return (
            budget.max_cost_microusd_per_correlation is None
            or spent.cost_microusd < budget.max_cost_microusd_per_correlation
        )

    async def charge(self, correlation_id: str, *, calls: int, cost_microusd: int) -> None:
        if calls < 0 or cost_microusd < 0:
            raise ValueError("model budget charges MUST be non-negative")
        self._apply(correlation_id, calls=calls, cost_microusd=cost_microusd)

    def _apply(self, correlation_id: str, *, calls: int, cost_microusd: int) -> None:
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


class BudgetChargingMeteringSink:
    """Charge the budget with what metering actually recorded.

    Spend is known in one place already: an adapter emits an
    :class:`~fdai.core.metering.records.LlmInvocation` after every call,
    with the measured usage and the computed cost. Wrapping the sink
    makes that the single charge point, so every path that meters is
    also bounded - the cross-check, the proposer, the critic, the judge,
    the narrator - without each one being taught to account for itself.

    Cost is charged after the call because that is when it is known. The
    call caps are what stop a call *before* it happens; a ceiling can
    therefore be overshot by at most the one call that crossed it, which
    is why the per-unit call cap exists alongside the cost cap.

    Charging never breaks the caller: the wrapped sink is written first
    and a ledger failure is logged, not raised, exactly like the
    emitter's own best-effort contract.
    """

    __slots__ = ("_inner", "_ledger")

    def __init__(self, inner: MeteringSink, ledger: BudgetLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    async def record(self, invocation: LlmInvocation) -> None:
        # ``finally``: the money left the account whether or not the
        # record could be persisted. A ceiling that only counts the calls
        # it managed to write down is not a ceiling, so a failing sink
        # must not also refund the budget. The write's own failure is
        # left to propagate; the caller decides how loud it is.
        try:
            await self._inner.record(invocation)
        finally:
            await self._charge(invocation)

    async def _charge(self, invocation: LlmInvocation) -> None:
        try:
            await self._ledger.charge(
                invocation.correlation_id,
                calls=0,
                cost_microusd=to_microusd(invocation.cost),
            )
        except Exception:
            _LOG.warning(
                "budget_charge_failed",
                extra={"correlation_id": invocation.correlation_id},
                exc_info=True,
            )


__all__ = [
    "MAX_TRACKED_CORRELATIONS",
    "BudgetChargingMeteringSink",
    "BudgetLedger",
    "BudgetSpend",
    "InMemoryBudgetLedger",
    "ModelBudget",
    "to_microusd",
]
