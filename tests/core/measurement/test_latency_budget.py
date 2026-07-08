"""Latency budget monitor outcomes."""

from __future__ import annotations

import pytest

from fdai.core.measurement.latency_budget import (
    LatencyBudget,
    LatencyBudgetMonitor,
    LatencyObservation,
    LatencyOutcome,
    Tier,
)


def _monitor() -> LatencyBudgetMonitor:
    return LatencyBudgetMonitor(
        budgets={
            Tier.T0: LatencyBudget(tier=Tier.T0, p95_ceiling_ms=100),
            Tier.T1: LatencyBudget(tier=Tier.T1, p95_ceiling_ms=1000),
            Tier.T2: LatencyBudget(tier=Tier.T2, p95_ceiling_ms=15000),
        }
    )


def test_budget_tier_mismatch_is_hard_error() -> None:
    with pytest.raises(ValueError, match="budgets"):
        LatencyBudgetMonitor(
            budgets={
                Tier.T0: LatencyBudget(tier=Tier.T1, p95_ceiling_ms=100),
            }
        )


def test_non_positive_ceiling_rejected() -> None:
    with pytest.raises(ValueError, match="p95_ceiling_ms"):
        LatencyBudgetMonitor(budgets={Tier.T0: LatencyBudget(tier=Tier.T0, p95_ceiling_ms=0)})


def test_pass_when_p95_within_budget() -> None:
    decision = _monitor().evaluate(LatencyObservation(tier=Tier.T0, p95_ms=50, sample_size=100))
    assert decision.outcome is LatencyOutcome.PASS
    assert decision.reasons == ()


def test_over_budget_flags_the_tier() -> None:
    decision = _monitor().evaluate(LatencyObservation(tier=Tier.T2, p95_ms=20000, sample_size=42))
    assert decision.outcome is LatencyOutcome.OVER_BUDGET
    assert any("p95_ms=20000" in r for r in decision.reasons)
    assert any("ceiling_ms=15000" in r for r in decision.reasons)
    assert any("sample_size=42" in r for r in decision.reasons)


def test_boundary_equal_to_ceiling_is_pass() -> None:
    decision = _monitor().evaluate(LatencyObservation(tier=Tier.T1, p95_ms=1000, sample_size=1))
    assert decision.outcome is LatencyOutcome.PASS


def test_no_budget_configured_treats_as_pass() -> None:
    monitor = LatencyBudgetMonitor(
        budgets={Tier.T0: LatencyBudget(tier=Tier.T0, p95_ceiling_ms=100)}
    )
    decision = monitor.evaluate(LatencyObservation(tier=Tier.T2, p95_ms=1e9, sample_size=1))
    assert decision.outcome is LatencyOutcome.PASS
    assert "no_budget_configured_for_tier" in decision.reasons


def test_insufficient_samples_holds_instead_of_demoting() -> None:
    # A p95 from too few samples is statistical noise - demoting on it
    # would penalize an ActionType on chance. Hold (PASS) until enough.
    monitor = LatencyBudgetMonitor(
        budgets={Tier.T0: LatencyBudget(tier=Tier.T0, p95_ceiling_ms=100)},
        min_sample_size=30,
    )
    decision = monitor.evaluate(LatencyObservation(tier=Tier.T0, p95_ms=9999.0, sample_size=5))
    assert decision.outcome is LatencyOutcome.PASS
    assert any("insufficient_samples" in r for r in decision.reasons)


def test_min_sample_size_validation() -> None:
    with pytest.raises(ValueError, match="min_sample_size"):
        LatencyBudgetMonitor(
            budgets={Tier.T0: LatencyBudget(tier=Tier.T0, p95_ceiling_ms=100)},
            min_sample_size=0,
        )
