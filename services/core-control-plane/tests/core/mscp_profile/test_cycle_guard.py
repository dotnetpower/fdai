"""Tests for MSCP-derived cycle budgets and oscillation detection."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from fdai.core.mscp_profile import (
    CycleBudget,
    CycleGuardReason,
    CycleGuardStatus,
    CycleUsage,
    OscillationPolicy,
    evaluate_cycle_guard,
)

_BUDGET = CycleBudget(
    max_cycles=5,
    max_elapsed_seconds=60.0,
    max_cost_units=10.0,
    max_rollbacks=2,
)
_OSCILLATION = OscillationPolicy(window_size=5, max_sign_changes=3)


def test_cycle_within_all_bounds_continues() -> None:
    result = evaluate_cycle_guard(
        budget=_BUDGET,
        usage=CycleUsage(1, 5.0, 1.0, 0, (0.1, 0.2)),
        oscillation=_OSCILLATION,
    )
    assert result.status is CycleGuardStatus.CONTINUE
    assert result.reasons == (CycleGuardReason.WITHIN_BOUNDS,)


def test_cycle_reports_every_exhausted_budget() -> None:
    result = evaluate_cycle_guard(
        budget=_BUDGET,
        usage=CycleUsage(5, 60.0, 10.0, 3),
        oscillation=_OSCILLATION,
    )
    assert result.status is CycleGuardStatus.HOLD
    assert set(result.reasons) == {
        CycleGuardReason.MAX_CYCLES_REACHED,
        CycleGuardReason.MAX_ELAPSED_REACHED,
        CycleGuardReason.MAX_COST_REACHED,
        CycleGuardReason.MAX_ROLLBACKS_EXCEEDED,
    }


def test_zero_rollback_budget_allows_work_until_a_rollback_occurs() -> None:
    budget = CycleBudget(5, 60.0, 10.0, 0)
    before = evaluate_cycle_guard(
        budget=budget,
        usage=CycleUsage(1, 1.0, 1.0, 0),
        oscillation=_OSCILLATION,
    )
    after = evaluate_cycle_guard(
        budget=budget,
        usage=CycleUsage(1, 1.0, 1.0, 1),
        oscillation=_OSCILLATION,
    )
    assert before.status is CycleGuardStatus.CONTINUE
    assert after.reasons == (CycleGuardReason.MAX_ROLLBACKS_EXCEEDED,)


def test_cycle_detects_recent_oscillation_and_ignores_zeroes() -> None:
    result = evaluate_cycle_guard(
        budget=_BUDGET,
        usage=CycleUsage(1, 5.0, 1.0, 0, (10.0, 1.0, 0.0, -1.0, 1.0, -1.0)),
        oscillation=_OSCILLATION,
    )
    assert result.status is CycleGuardStatus.HOLD
    assert result.reasons == (CycleGuardReason.OSCILLATION_DETECTED,)


def test_budget_type_is_frozen() -> None:
    value = CycleBudget(1, 1.0, 1.0, 0)
    with pytest.raises(FrozenInstanceError):
        value.max_cycles = 2  # type: ignore[misc]


def test_cycle_contracts_reject_invalid_limits_and_usage() -> None:
    with pytest.raises(ValueError, match="max_cycles"):
        CycleBudget(0, 1.0, 1.0, 0)
    with pytest.raises(ValueError, match="window_size"):
        OscillationPolicy(1, 1)
    with pytest.raises(ValueError, match="finite"):
        CycleUsage(0, 0.0, float("inf"), 0)
