"""SLO value objects mirroring ``shared/contracts/slo/schema.json``."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class SLIKind(StrEnum):
    """Google SRE Ch. 4 SLI taxonomy."""

    AVAILABILITY = "availability"
    LATENCY = "latency"
    CORRECTNESS = "correctness"
    FRESHNESS = "freshness"


@dataclass(frozen=True, slots=True)
class SLI:
    """Service Level Indicator - the raw ratio the SLO tracks."""

    kind: SLIKind
    good_query: str
    total_query: str
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BurnRateAlertDef:
    """One multi-window multi-burn-rate alert definition (see burn_rate.py).

    Field docs mirror the JSON Schema at
    ``shared/contracts/slo/schema.json``.
    """

    name: str
    short_window_minutes: int
    long_window_minutes: int
    burn_rate_threshold: float
    severity: str = "sev3"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name MUST be non-empty")
        # The evaluator fires when ``rate >= burn_rate_threshold`` and a
        # burn rate is always >= 0. A threshold <= 0 therefore makes BOTH
        # windows trivially exceed on every pass - a fail-OPEN alert that
        # screams with zero bad events; a non-finite threshold (NaN) makes
        # every comparison False - a silently dead alert. Require a finite,
        # strictly-positive threshold so the alert means what it says.
        if not math.isfinite(self.burn_rate_threshold) or self.burn_rate_threshold <= 0.0:
            raise ValueError("burn_rate_threshold MUST be finite and > 0")
        if self.short_window_minutes < 1:
            raise ValueError("short_window_minutes MUST be >= 1")
        if self.long_window_minutes < 1:
            raise ValueError("long_window_minutes MUST be >= 1")
        # Multi-window multi-burn-rate requires a strictly shorter fast
        # window and a longer noise-suppressing window; equal or swapped
        # windows collapse the design into a single-window alert or invert
        # its intent.
        if self.short_window_minutes >= self.long_window_minutes:
            raise ValueError(
                "short_window_minutes MUST be < long_window_minutes (multi-window invariant)"
            )


@dataclass(frozen=True, slots=True)
class SLO:
    """Rolling-window objective (compliance ratio + window)."""

    id: str
    objective_ratio: float
    window_days: int
    sli: SLI
    burn_rate_alerts: tuple[BurnRateAlertDef, ...] = ()
    description: str | None = None
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not (0 < self.objective_ratio <= 1):
            raise ValueError("objective_ratio MUST be in (0, 1]")
        if self.window_days < 1:
            raise ValueError("window_days MUST be >= 1")

    @property
    def error_budget_fraction(self) -> float:
        """Fraction of events allowed to be bad over the window (1 - objective)."""
        return 1.0 - self.objective_ratio


@dataclass(frozen=True, slots=True)
class ErrorBudget:
    """Current error-budget state derived from a good/total observation."""

    slo_id: str
    good_events: int
    total_events: int
    objective_ratio: float

    def __post_init__(self) -> None:
        if self.good_events < 0:
            raise ValueError("good_events MUST be >= 0")
        if self.total_events < 0:
            raise ValueError("total_events MUST be >= 0")
        if self.good_events > self.total_events:
            raise ValueError("good_events MUST be <= total_events")

    @property
    def observed_ratio(self) -> float:
        """`good / total` (0.0 when no events observed - fail-closed)."""
        return self.good_events / self.total_events if self.total_events > 0 else 0.0

    @property
    def budget_remaining_fraction(self) -> float:
        """Fraction of the error budget still unspent.

        Range ``[0.0, 1.0]``: 1.0 = fresh budget; 0.0 = fully burned.
        Clamped at 0 so a heavily-breached SLO doesn't return a
        misleading negative number (the breach is captured by the
        burn-rate itself).
        """
        max_bad = self.total_events * (1.0 - self.objective_ratio)
        actual_bad = self.total_events - self.good_events
        if max_bad <= 0:
            return 0.0 if actual_bad > 0 else 1.0
        remaining = 1.0 - (actual_bad / max_bad)
        return max(0.0, remaining)


__all__ = ["SLI", "SLO", "BurnRateAlertDef", "ErrorBudget", "SLIKind"]
