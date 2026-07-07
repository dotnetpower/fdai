"""Multi-window multi-burn-rate alert evaluator.

Reference: Google SRE Workbook Ch. 5, Section "Multi-Window,
Multi-Burn-Rate Alerts". The evaluator fires an alert when BOTH the
short-window and long-window observed burn rates exceed the configured
threshold. The short window catches fast burns; the long window
suppresses noise on transient spikes.

Burn rate definition (unitless):

    burn_rate = observed_bad_ratio / (1 - objective_ratio)

Interpretation: a burn rate of 1.0 means the SLO is being consumed at
exactly the rate the objective allows. A burn rate of 10.0 means the
error budget is being consumed 10x faster than allowed.

Fail-closed: the evaluator NEVER auto-remediates. A breach emits a
finding via the standard trust-router / risk-gate / executor path so
the safety-invariant contract in
``architecture.instructions.md`` still governs any downstream action.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import SLO, BurnRateAlertDef


@dataclass(frozen=True, slots=True)
class BurnRate:
    """Observed burn rate for one window."""

    window_minutes: int
    good_events: int
    total_events: int
    objective_ratio: float

    def __post_init__(self) -> None:
        if self.window_minutes < 1:
            raise ValueError("window_minutes MUST be >= 1")
        if self.good_events < 0:
            raise ValueError("good_events MUST be >= 0")
        if self.total_events < 0:
            raise ValueError("total_events MUST be >= 0")
        if self.good_events > self.total_events:
            raise ValueError("good_events MUST be <= total_events")

    @property
    def bad_ratio(self) -> float:
        """`(total - good) / total`; 0.0 when no events observed."""
        return (
            (self.total_events - self.good_events) / self.total_events
            if self.total_events > 0
            else 0.0
        )

    @property
    def rate(self) -> float:
        """Unitless burn-rate multiple over the objective's allowance."""
        allowed = 1.0 - self.objective_ratio
        if allowed <= 0:
            # objective_ratio == 1 (impossibly strict). Any bad event
            # is an infinite burn; return a large sentinel so any
            # threshold breach fires deterministically.
            return float("inf") if self.bad_ratio > 0 else 0.0
        return self.bad_ratio / allowed


@dataclass(frozen=True, slots=True)
class BurnRateAlert:
    """One (slo, alert-def, short-observation, long-observation) tuple."""

    slo_id: str
    alert: BurnRateAlertDef
    short: BurnRate
    long: BurnRate


@dataclass(frozen=True, slots=True)
class BurnRateBreach:
    """A fired breach - both windows exceeded the threshold."""

    alert: BurnRateAlert

    @property
    def short_rate(self) -> float:
        return self.alert.short.rate

    @property
    def long_rate(self) -> float:
        return self.alert.long.rate


class BurnRateEvaluator:
    """Deterministic multi-window multi-burn-rate evaluator.

    Pure function of inputs - no I/O. Callers fetch metric samples from
    the layer-6 :class:`~fdai.shared.providers.metric.MetricProvider`
    seam, compress them into per-window good/total pairs, and hand the
    pairs here. Keeping metric fetch outside the evaluator makes the
    logic testable without a real telemetry backend.
    """

    def evaluate(self, alerts: Iterable[BurnRateAlert]) -> tuple[BurnRateBreach, ...]:
        """Return every alert whose BOTH windows exceed the threshold."""
        breaches: list[BurnRateBreach] = []
        for alert in alerts:
            threshold = alert.alert.burn_rate_threshold
            if alert.short.rate >= threshold and alert.long.rate >= threshold:
                breaches.append(BurnRateBreach(alert=alert))
        return tuple(breaches)


def build_alerts(*, slo: SLO, samples: dict[int, tuple[int, int]]) -> tuple[BurnRateAlert, ...]:
    """Convenience: per-window ``(good, total)`` samples -> :class:`BurnRateAlert` tuples.

    ``samples`` is keyed by window in minutes and maps to
    ``(good, total)``. Every window referenced by the SLO's alerts
    MUST be present; a missing window raises ``KeyError`` (fail-closed
    - the caller MUST NOT proceed with a stale evaluation).
    """
    out: list[BurnRateAlert] = []
    for alert_def in slo.burn_rate_alerts:
        short_g, short_t = samples[alert_def.short_window_minutes]
        long_g, long_t = samples[alert_def.long_window_minutes]
        out.append(
            BurnRateAlert(
                slo_id=slo.id,
                alert=alert_def,
                short=BurnRate(
                    window_minutes=alert_def.short_window_minutes,
                    good_events=short_g,
                    total_events=short_t,
                    objective_ratio=slo.objective_ratio,
                ),
                long=BurnRate(
                    window_minutes=alert_def.long_window_minutes,
                    good_events=long_g,
                    total_events=long_t,
                    objective_ratio=slo.objective_ratio,
                ),
            )
        )
    return tuple(out)


__all__ = [
    "BurnRate",
    "BurnRateAlert",
    "BurnRateBreach",
    "BurnRateEvaluator",
    "build_alerts",
]
