"""Seasonal anomaly detector - phase-aware baseline, deterministic-first.

The base :class:`~fdai.core.detection.anomaly.MetricAnomalyDetector`
compares an observed value against a single flat baseline over the whole
history. That over-fires on any metric with a periodic shape: a Monday
morning traffic peak or a nightly batch-job spike looks anomalous against
a 24x7 mean even though it is perfectly normal *for that time*.

`SeasonalAnomalyDetector` closes that gap while staying deterministic,
explainable, and shadow-first. It buckets history by a **seasonal phase**
(hour-of-day or day-of-week by default, or a custom phase function) and
compares the observed sample only against past samples in the *same
phase*. It is a thin wrapper over the base detector - it filters the
history to the observed sample's phase and delegates the z-score,
cold-start-abstain, flat-baseline, and event-normalization logic - so the
two detectors cannot drift apart.

This addresses the "seasonality beyond a single configured window" gap in
[observability-and-detection.md](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md)
section 2. Like every detector here it emits a shadow-mode finding that
re-enters ``event-ingest``; it never auto-remediates.

CSP-neutral: imports only ``fdai.core.detection`` peers and the standard
library, so it stays under the ``core/`` import rule.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from fdai.core.detection.anomaly import (
    _DEFAULT_SOURCE,
    AnomalyFinding,
    MetricAnomalyDetector,
)
from fdai.core.detection.series import MetricSample
from fdai.shared.contracts.models import Category, Event, Mode

# Built-in phase functions. A phase is a small integer bucket the sample
# is compared within; "same phase" means "comparable seasonal position".
PhaseFn = Callable[[datetime], int]

_PHASE_RESOLVERS: dict[str, PhaseFn] = {
    "hour_of_day": lambda ts: ts.hour,  # 0..23
    "day_of_week": lambda ts: ts.weekday(),  # 0 (Mon) .. 6 (Sun)
    "hour_of_week": lambda ts: ts.weekday() * 24 + ts.hour,  # 0..167
}


def _resolve_phase(phase: str | PhaseFn) -> tuple[str, PhaseFn]:
    if callable(phase):
        return ("custom", phase)
    resolver = _PHASE_RESOLVERS.get(phase)
    if resolver is None:
        raise ValueError(
            f"unknown seasonal phase {phase!r}; "
            f"choose one of {sorted(_PHASE_RESOLVERS)} or pass a callable"
        )
    return (phase, resolver)


class SeasonalAnomalyDetector:
    """Phase-aware anomaly detector built on the base z-score detector.

    Configuration-driven: the phase function, minimum per-phase sample
    count, and z-threshold are constructor args so a fork tunes the
    seasonality without editing this class.
    """

    def __init__(
        self,
        *,
        detector_id: str,
        phase: str | PhaseFn = "hour_of_day",
        category: Category = Category.RELIABILITY,
        min_samples_per_phase: int = 10,
        z_threshold: float = 3.0,
        source: str = _DEFAULT_SOURCE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._phase_label, self._phase_of = _resolve_phase(phase)
        # A per-phase baseline needs variance to compute a z-score; the
        # inner detector enforces >= 2, but validate here too so the error
        # names the seasonal parameter the caller actually passed.
        if min_samples_per_phase < 2:
            raise ValueError("min_samples_per_phase MUST be >= 2 (a baseline needs variance)")
        # The inner detector owns the statistics; per-phase samples are its
        # "history", so min_samples maps to min_samples_per_phase.
        self._inner = MetricAnomalyDetector(
            detector_id=detector_id,
            category=category,
            min_samples=min_samples_per_phase,
            z_threshold=z_threshold,
            source=source,
            clock=clock or (lambda: datetime.now(tz=UTC)),
        )

    def evaluate(
        self,
        *,
        metric: str,
        resource_ref: str,
        history: Sequence[MetricSample],
        observed: MetricSample,
        window_bucket: str,
    ) -> AnomalyFinding | None:
        """Return a finding when ``observed`` deviates *within its phase*.

        History is filtered to samples sharing the observed sample's
        phase, then the base detector's deterministic check runs. A phase
        with too few samples cold-starts (abstains) independently of other
        phases - a thin Sunday baseline never borrows Monday's data.
        """
        phase = self._phase_of(observed.timestamp)
        same_phase = [s for s in history if self._phase_of(s.timestamp) == phase]
        phase_bucket = f"{window_bucket}:{self._phase_label}={phase}"
        return self._inner.evaluate(
            metric=metric,
            resource_ref=resource_ref,
            history=same_phase,
            observed=observed,
            window_bucket=phase_bucket,
        )

    def to_event(self, finding: AnomalyFinding, *, mode: Mode = Mode.SHADOW) -> Event:
        """Normalize a finding into an Event (delegates to the base detector)."""
        return self._inner.to_event(finding, mode=mode)


__all__ = [
    "PhaseFn",
    "SeasonalAnomalyDetector",
]
