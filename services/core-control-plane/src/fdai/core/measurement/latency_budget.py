"""Per-tier latency budget monitor.

Phase 4 § Scalability and Performance. The system holds tier latency
budgets (T0 ms-s, T1 ~s, T2 s-tens-of-seconds) across scale; this
module compares observed p95 latency to a stated budget and emits a
demote-vs-hold decision the caller wires into the promotion registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Tier(StrEnum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"


class LatencyOutcome(StrEnum):
    PASS = "pass"  # noqa: S105 - enum value, not a secret
    """Observed p95 is within budget."""

    OVER_BUDGET = "over_budget"
    """Observed p95 exceeds budget - caller demotes / alerts."""


@dataclass(frozen=True, slots=True)
class LatencyObservation:
    tier: Tier
    p95_ms: float
    sample_size: int


@dataclass(frozen=True, slots=True)
class LatencyBudget:
    tier: Tier
    p95_ceiling_ms: float


@dataclass(frozen=True, slots=True)
class LatencyDecision:
    tier: Tier
    outcome: LatencyOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)


class LatencyBudgetMonitor:
    """Compare :class:`LatencyObservation` against :class:`LatencyBudget`."""

    def __init__(self, *, budgets: dict[Tier, LatencyBudget], min_sample_size: int = 1) -> None:
        for tier, budget in budgets.items():
            if budget.tier is not tier:
                raise ValueError(f"budgets[{tier}].tier is {budget.tier}, expected {tier}")
            if budget.p95_ceiling_ms <= 0:
                raise ValueError(f"budgets[{tier}].p95_ceiling_ms MUST be > 0")
        if min_sample_size < 1:
            raise ValueError("min_sample_size MUST be >= 1")
        self._budgets = dict(budgets)
        self._min_sample_size = min_sample_size

    def evaluate(self, observation: LatencyObservation) -> LatencyDecision:
        budget = self._budgets.get(observation.tier)
        if budget is None:
            return LatencyDecision(
                tier=observation.tier,
                outcome=LatencyOutcome.PASS,
                reasons=("no_budget_configured_for_tier",),
            )
        if observation.sample_size < self._min_sample_size:
            # A p95 computed from too few samples is statistical noise;
            # acting on it would demote an ActionType on chance. Hold
            # (PASS) until enough samples accumulate.
            return LatencyDecision(
                tier=observation.tier,
                outcome=LatencyOutcome.PASS,
                reasons=(
                    f"insufficient_samples:{observation.sample_size}<min={self._min_sample_size}",
                ),
            )
        if observation.p95_ms > budget.p95_ceiling_ms:
            return LatencyDecision(
                tier=observation.tier,
                outcome=LatencyOutcome.OVER_BUDGET,
                reasons=(
                    f"p95_ms={observation.p95_ms}>"
                    f"ceiling_ms={budget.p95_ceiling_ms}"
                    f":sample_size={observation.sample_size}",
                ),
            )
        return LatencyDecision(
            tier=observation.tier,
            outcome=LatencyOutcome.PASS,
        )


__all__ = [
    "LatencyBudget",
    "LatencyBudgetMonitor",
    "LatencyDecision",
    "LatencyObservation",
    "LatencyOutcome",
    "Tier",
]
