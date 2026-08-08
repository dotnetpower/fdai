"""Bound recursive work for the MSCP operational profile.

MSCP provenance: Level 3 meta-escalation, oscillation detection, and
cognitive budgeting. FDAI keeps every threshold caller-owned and uses the
result only to continue or hold work for review.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class CycleGuardStatus(StrEnum):
    CONTINUE = "continue"
    HOLD = "hold"


class CycleGuardReason(StrEnum):
    WITHIN_BOUNDS = "within_bounds"
    MAX_CYCLES_REACHED = "max_cycles_reached"
    MAX_ELAPSED_REACHED = "max_elapsed_reached"
    MAX_COST_REACHED = "max_cost_reached"
    MAX_ROLLBACKS_EXCEEDED = "max_rollbacks_exceeded"
    OSCILLATION_DETECTED = "oscillation_detected"


@dataclass(frozen=True, slots=True)
class CycleBudget:
    max_cycles: int
    max_elapsed_seconds: float
    max_cost_units: float
    max_rollbacks: int

    def __post_init__(self) -> None:
        if self.max_cycles < 1:
            raise ValueError("max_cycles MUST be >= 1")
        if not math.isfinite(self.max_elapsed_seconds) or self.max_elapsed_seconds <= 0:
            raise ValueError("max_elapsed_seconds MUST be finite and > 0")
        if not math.isfinite(self.max_cost_units) or self.max_cost_units <= 0:
            raise ValueError("max_cost_units MUST be finite and > 0")
        if self.max_rollbacks < 0:
            raise ValueError("max_rollbacks MUST be >= 0")


@dataclass(frozen=True, slots=True)
class OscillationPolicy:
    window_size: int
    max_sign_changes: int

    def __post_init__(self) -> None:
        if self.window_size < 2:
            raise ValueError("window_size MUST be >= 2")
        if not 1 <= self.max_sign_changes < self.window_size:
            raise ValueError("max_sign_changes MUST be in [1, window_size)")


@dataclass(frozen=True, slots=True)
class CycleUsage:
    cycles: int
    elapsed_seconds: float
    cost_units: float
    rollbacks: int
    correction_history: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.cycles < 0:
            raise ValueError("cycles MUST be >= 0")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds MUST be finite and >= 0")
        if not math.isfinite(self.cost_units) or self.cost_units < 0:
            raise ValueError("cost_units MUST be finite and >= 0")
        if self.rollbacks < 0:
            raise ValueError("rollbacks MUST be >= 0")
        if any(not math.isfinite(value) for value in self.correction_history):
            raise ValueError("correction_history values MUST be finite")


@dataclass(frozen=True, slots=True)
class CycleGuardDecision:
    status: CycleGuardStatus
    reasons: tuple[CycleGuardReason, ...]


def _sign_changes(values: tuple[float, ...]) -> int:
    non_zero = tuple(value for value in values if value != 0.0)
    return sum(
        1
        for previous, current in zip(non_zero, non_zero[1:], strict=False)
        if previous * current < 0
    )


def evaluate_cycle_guard(
    *,
    budget: CycleBudget,
    usage: CycleUsage,
    oscillation: OscillationPolicy,
) -> CycleGuardDecision:
    """Return a deterministic continue-or-hold decision for one cycle."""

    reasons: list[CycleGuardReason] = []
    if usage.cycles >= budget.max_cycles:
        reasons.append(CycleGuardReason.MAX_CYCLES_REACHED)
    if usage.elapsed_seconds >= budget.max_elapsed_seconds:
        reasons.append(CycleGuardReason.MAX_ELAPSED_REACHED)
    if usage.cost_units >= budget.max_cost_units:
        reasons.append(CycleGuardReason.MAX_COST_REACHED)
    if usage.rollbacks > budget.max_rollbacks:
        reasons.append(CycleGuardReason.MAX_ROLLBACKS_EXCEEDED)

    window = usage.correction_history[-oscillation.window_size :]
    if _sign_changes(window) >= oscillation.max_sign_changes:
        reasons.append(CycleGuardReason.OSCILLATION_DETECTED)

    if reasons:
        return CycleGuardDecision(CycleGuardStatus.HOLD, tuple(reasons))
    return CycleGuardDecision(
        CycleGuardStatus.CONTINUE,
        (CycleGuardReason.WITHIN_BOUNDS,),
    )


__all__ = [
    "CycleBudget",
    "CycleGuardDecision",
    "CycleGuardReason",
    "CycleGuardStatus",
    "CycleUsage",
    "OscillationPolicy",
    "evaluate_cycle_guard",
]
