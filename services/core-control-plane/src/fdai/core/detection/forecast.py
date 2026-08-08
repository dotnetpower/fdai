"""Linear forecast detector - proactive threshold-breach prediction.

Implements the forecasting stance of
[observability-and-detection.md](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md)
section 3: fit a least-squares linear trend to a metric series and
predict whether the projected value will cross a configured threshold
**within a forecast horizon**, raising a :class:`ForecastFinding` with a
positive **lead time** (breach ETA) when so.

A forecast is a projection with stated uncertainty (R-squared +
residual std), **not deterministic truth and not an LLM oracle** - it
never grants execution eligibility. The finding is shadow-mode by
default and normalizes to an
:class:`~fdai.shared.contracts.models.Event`
(``event_type="forecast.finding"``) that re-enters ``event-ingest`` and
passes the risk gate like any event.

Deterministic-first, explainable, and conservative:

- a history below ``min_samples`` abstains (cold-start);
- a trend whose R-squared is below ``min_r_squared`` abstains (a weak
  signal must not over-predict);
- a flat or wrong-direction trend yields no breach;
- an already-breached series (ETA <= 0) is left to the anomaly detector
  (section 2) - forecasting only speaks about the future;
- a breach projected **beyond** the horizon yields no finding.

CSP-neutral: imports only ``fdai.shared.contracts``, the shared series
type, and the standard library.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid4, uuid5

from fdai.core.detection.series import MetricSample
from fdai.shared.contracts.models import Category, Event, Mode, Severity

_FORECAST_EVENT_TYPE = "forecast.finding"
_DEFAULT_SOURCE = "fdai.core.detection.forecast"
_DIRECTIONS = ("rising", "falling")


class ForecastDetectorDecision(StrEnum):
    PREDICTED_BREACH = "predicted_breach"
    PREDICTED_NO_BREACH = "predicted_no_breach"
    ABSTAINED = "abstained"


@dataclass(frozen=True, slots=True)
class ForecastFinding:
    """A deterministic, evidence-backed breach forecast.

    Carries the full trend context (slope, intercept, fit quality) plus
    the projected value and the lead time so the audit trail and any
    downstream reasoning can reconstruct the projection without re-reading
    the raw series.
    """

    detector_id: str
    metric: str
    resource_ref: str
    window_bucket: str
    slope_per_second: float
    intercept: float
    r_squared: float
    residual_std: float
    horizon_seconds: float
    threshold: float
    direction: str
    """``"rising"`` (crossing upward) or ``"falling"`` (downward)."""
    value_now: float
    projected_at_horizon: float
    lead_time_seconds: float
    """ETA to the projected breach; always positive and <= horizon."""
    category: Category
    severity: Severity
    idempotency_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class ForecastDetectorEvaluation:
    decision: ForecastDetectorDecision
    finding: ForecastFinding | None
    reason: str


def _severity_from_lead(lead: float, horizon: float) -> Severity:
    """Sooner breach -> higher severity (imminence)."""
    ratio = lead / horizon if horizon > 0 else 1.0
    if ratio <= 0.25:
        return Severity.CRITICAL
    if ratio <= 0.5:
        return Severity.HIGH
    return Severity.MEDIUM


def _fit_quality(
    xs: Sequence[float], ys: Sequence[float], slope: float, intercept: float
) -> tuple[float, float]:
    """Return (R-squared, residual population std) for a linear fit."""
    mean_y = statistics.fmean(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys, strict=True)]
    ss_res = sum(r * r for r in residuals)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 0.0
    resid_std = statistics.pstdev(residuals) if len(residuals) > 1 else 0.0
    return r_squared, resid_std


class LinearForecastDetector:
    """Least-squares linear forecaster for a single metric series.

    Configuration-driven (threshold, horizon, direction, fit gate) so a
    fork tunes it without editing this class.
    """

    def __init__(
        self,
        *,
        detector_id: str,
        threshold: float,
        horizon_seconds: float,
        direction: str = "rising",
        category: Category = Category.RELIABILITY,
        min_samples: int = 5,
        min_r_squared: float = 0.5,
        source: str = _DEFAULT_SOURCE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not detector_id:
            raise ValueError("detector_id MUST be non-empty")
        if direction not in _DIRECTIONS:
            raise ValueError(f"direction MUST be one of {_DIRECTIONS}")
        if horizon_seconds <= 0:
            raise ValueError("horizon_seconds MUST be > 0")
        if min_samples < 2:
            raise ValueError("min_samples MUST be >= 2 (a trend needs at least two points)")
        if not 0.0 <= min_r_squared <= 1.0:
            raise ValueError("min_r_squared MUST be in [0, 1]")
        self._detector_id = detector_id
        self._threshold = float(threshold)
        self._horizon = float(horizon_seconds)
        self._direction = direction
        self._category = category
        self._min_samples = min_samples
        self._min_r_squared = float(min_r_squared)
        self._source = source
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def evaluate(
        self,
        *,
        metric: str,
        resource_ref: str,
        history: Sequence[MetricSample],
        window_bucket: str,
    ) -> ForecastFinding | None:
        """Return a positive finding while preserving the legacy API."""
        return self.evaluate_result(
            metric=metric,
            resource_ref=resource_ref,
            history=history,
            window_bucket=window_bucket,
        ).finding

    def evaluate_result(
        self,
        *,
        metric: str,
        resource_ref: str,
        history: Sequence[MetricSample],
        window_bucket: str,
    ) -> ForecastDetectorEvaluation:
        """Return an explicit positive, negative, or abstained evaluation."""
        if len(history) < self._min_samples:
            return ForecastDetectorEvaluation(
                ForecastDetectorDecision.ABSTAINED, None, "insufficient_samples"
            )
        t0 = history[0].timestamp
        xs = [(s.timestamp - t0).total_seconds() for s in history]
        ys = [s.value for s in history]
        if xs[-1] == xs[0]:
            return ForecastDetectorEvaluation(
                ForecastDetectorDecision.ABSTAINED, None, "zero_time_span"
            )

        # A non-finite sample (NaN / +-Inf) poisons the least-squares fit:
        # slope/intercept/r_squared become NaN, and every abstain guard below
        # (``r_squared < min``, ``lead <= 0``, ``lead > horizon``) is a NaN
        # comparison that is always False - so the detector would emit a
        # ForecastFinding full of NaN. Abstain (fail-closed) on corrupt input.
        if not all(math.isfinite(y) for y in ys):
            return ForecastDetectorEvaluation(
                ForecastDetectorDecision.ABSTAINED, None, "non_finite_sample"
            )

        slope, intercept = statistics.linear_regression(xs, ys)
        if slope == 0.0:
            return ForecastDetectorEvaluation(
                ForecastDetectorDecision.PREDICTED_NO_BREACH, None, "flat_trend"
            )

        r_squared, resid_std = _fit_quality(xs, ys, slope, intercept)
        if r_squared < self._min_r_squared:
            return ForecastDetectorEvaluation(ForecastDetectorDecision.ABSTAINED, None, "weak_fit")

        x_last = xs[-1]
        value_now = intercept + slope * x_last
        if self._direction == "rising":
            if slope <= 0.0 or self._threshold <= value_now:
                if self._threshold <= value_now:
                    return ForecastDetectorEvaluation(
                        ForecastDetectorDecision.ABSTAINED, None, "already_breached"
                    )
                return ForecastDetectorEvaluation(
                    ForecastDetectorDecision.PREDICTED_NO_BREACH, None, "wrong_direction"
                )
        elif slope >= 0.0 or self._threshold >= value_now:
            if self._threshold >= value_now:
                return ForecastDetectorEvaluation(
                    ForecastDetectorDecision.ABSTAINED, None, "already_breached"
                )
            return ForecastDetectorEvaluation(
                ForecastDetectorDecision.PREDICTED_NO_BREACH, None, "wrong_direction"
            )

        x_cross = (self._threshold - intercept) / slope
        lead = x_cross - x_last
        if lead <= 0.0 or lead > self._horizon:
            if lead <= 0.0:
                return ForecastDetectorEvaluation(
                    ForecastDetectorDecision.ABSTAINED, None, "already_breached"
                )
            return ForecastDetectorEvaluation(
                ForecastDetectorDecision.PREDICTED_NO_BREACH, None, "beyond_horizon"
            )

        projected = intercept + slope * (x_last + self._horizon)
        finding = ForecastFinding(
            detector_id=self._detector_id,
            metric=metric,
            resource_ref=resource_ref,
            window_bucket=window_bucket,
            slope_per_second=slope,
            intercept=intercept,
            r_squared=r_squared,
            residual_std=resid_std,
            horizon_seconds=self._horizon,
            threshold=self._threshold,
            direction=self._direction,
            value_now=value_now,
            projected_at_horizon=projected,
            lead_time_seconds=lead,
            category=self._category,
            severity=_severity_from_lead(lead, self._horizon),
            idempotency_key=self._idempotency_key(metric=metric, window_bucket=window_bucket),
            reason=(
                f"projected {self._direction} crossing of {self._threshold:g} "
                f"in {lead:.0f}s (r2={r_squared:.2f})"
            ),
        )
        return ForecastDetectorEvaluation(
            ForecastDetectorDecision.PREDICTED_BREACH,
            finding,
            "threshold_crossing",
        )

    def to_event(self, finding: ForecastFinding, *, mode: Mode = Mode.SHADOW) -> Event:
        """Normalize a forecast into an Event that re-enters event-ingest.

        Keyed by ``detector + metric + window`` so repeated evaluation
        ticks on the same window deduplicate.
        """
        now = self._clock()
        payload: dict[str, object] = {
            "kind": "forecast",
            "detector_id": finding.detector_id,
            "metric": finding.metric,
            "resource": {"resource_ref": finding.resource_ref},
            "slope_per_second": finding.slope_per_second,
            "intercept": finding.intercept,
            "r_squared": finding.r_squared,
            "residual_std": finding.residual_std,
            "horizon_seconds": finding.horizon_seconds,
            "threshold": finding.threshold,
            "direction": finding.direction,
            "value_now": finding.value_now,
            "projected_at_horizon": finding.projected_at_horizon,
            "lead_time_seconds": finding.lead_time_seconds,
            "category": finding.category.value,
            "severity": finding.severity.value,
            "window_bucket": finding.window_bucket,
            "reason": finding.reason,
        }
        return Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=finding.idempotency_key,
            source=self._source,
            event_type=_FORECAST_EVENT_TYPE,
            resource_ref=finding.resource_ref,
            payload=payload,
            detected_at=now,
            ingested_at=now,
            mode=mode,
        )

    def _idempotency_key(self, *, metric: str, window_bucket: str) -> str:
        return str(
            uuid5(NAMESPACE_URL, f"fdai-forecast:{self._detector_id}:{metric}:{window_bucket}")
        )


__all__ = [
    "ForecastDetectorDecision",
    "ForecastDetectorEvaluation",
    "ForecastFinding",
    "LinearForecastDetector",
]
