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

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SLIKind):
            raise ValueError("SLI.kind MUST be an SLIKind")
        if not self.good_query.strip() or not self.total_query.strip():
            raise ValueError("SLI good_query and total_query MUST be non-empty")


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
        if not self.name.strip():
            raise ValueError("name MUST be non-empty")
        if not self.severity.strip():
            raise ValueError("severity MUST be non-empty")
        # The evaluator fires when ``rate >= burn_rate_threshold`` and a
        # burn rate is always >= 0. A threshold <= 0 therefore makes BOTH
        # windows trivially exceed on every pass - a fail-OPEN alert that
        # screams with zero bad events; a non-finite threshold (NaN) makes
        # every comparison False - a silently dead alert. Require a finite,
        # strictly-positive threshold so the alert means what it says.
        if (
            isinstance(self.burn_rate_threshold, bool)
            or not math.isfinite(self.burn_rate_threshold)
            or self.burn_rate_threshold <= 0.0
        ):
            raise ValueError("burn_rate_threshold MUST be finite and > 0")
        if isinstance(self.short_window_minutes, bool) or self.short_window_minutes < 1:
            raise ValueError("short_window_minutes MUST be >= 1")
        if isinstance(self.long_window_minutes, bool) or self.long_window_minutes < 1:
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
        if not self.id.strip() or not self.schema_version.strip():
            raise ValueError("SLO id and schema_version MUST be non-empty")
        if (
            isinstance(self.objective_ratio, bool)
            or not math.isfinite(self.objective_ratio)
            or not (0 < self.objective_ratio <= 1)
        ):
            raise ValueError("objective_ratio MUST be in (0, 1]")
        if isinstance(self.window_days, bool) or self.window_days < 1:
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
        if not self.slo_id.strip():
            raise ValueError("slo_id MUST be non-empty")
        if isinstance(self.good_events, bool) or self.good_events < 0:
            raise ValueError("good_events MUST be >= 0")
        if isinstance(self.total_events, bool) or self.total_events < 0:
            raise ValueError("total_events MUST be >= 0")
        if self.good_events > self.total_events:
            raise ValueError("good_events MUST be <= total_events")
        if (
            isinstance(self.objective_ratio, bool)
            or not math.isfinite(self.objective_ratio)
            or not 0.0 <= self.objective_ratio <= 1.0
        ):
            raise ValueError("objective_ratio MUST be in [0.0, 1.0]")

    @property
    def burned_events(self) -> int:
        """Total bad events observed in the window (`total_events - good_events`)."""
        return self.total_events - self.good_events

    @property
    def is_exhausted(self) -> bool:
        """True when the remaining error budget fraction is zero."""
        return self.budget_remaining_fraction <= 0.0

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
