"""Metric anomaly detector - deterministic-first, shadow-mode finding producer.

Implements the anomaly-detection stance of
[observability-and-detection.md](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md)
section 2: compute a statistical baseline (mean / population std) over a
metric history and flag a deviation past a z-score threshold as an
:class:`AnomalyFinding`. The finding normalizes to an
:class:`~fdai.shared.contracts.models.Event`
(``event_type="anomaly.finding"``) that re-enters ``event-ingest`` like
any event - it is never a side channel and it never auto-remediates on
its own.

Deterministic and explainable
------------------------------

- No model call. The baseline mean/std, the observed value, the
  deviation magnitude (z-score), and its **direction** (over / under)
  are all recorded on the finding so a human can see *why* it fired.
- **Cold-start abstains.** A history below ``min_samples`` emits no
  finding (returns ``None``) rather than firing on a thin baseline.
- **Flat baseline is safe.** When every historical sample is identical
  (population std == 0) the z-score is undefined; a value equal to the
  baseline is *not* anomalous (``None``), and a value that differs is
  reported with ``z_score=None`` and ``CRITICAL`` severity rather than a
  division error.
- **Shadow-first.** The emitted event defaults to ``Mode.SHADOW``; a
  finding is a signal for the risk gate, not an action.

CSP-neutral: this module imports only ``fdai.shared.contracts`` and the
standard library, so it stays under the ``core/`` import rule.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from fdai.core.detection.series import MetricSample
from fdai.shared.contracts.models import Category, Event, Mode, Severity

_ANOMALY_EVENT_TYPE = "anomaly.finding"
_DEFAULT_SOURCE = "fdai.core.detection.anomaly"


@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    """A deterministic, evidence-backed anomaly signal.

    Carries the full baseline context so the audit trail and any
    downstream reasoning can reconstruct the decision without re-reading
    the raw series.
    """

    detector_id: str
    metric: str
    resource_ref: str
    window_bucket: str
    baseline_mean: float
    baseline_std: float
    observed: float
    z_score: float | None
    """Absolute z-score; ``None`` when the baseline is flat (std == 0)."""
    direction: str
    """``"over"`` (observed above baseline) or ``"under"`` (below)."""
    category: Category
    severity: Severity
    idempotency_key: str
    reason: str


def _severity_from_z(z: float | None) -> Severity:
    """Map the deviation magnitude onto a severity.

    ``None`` (flat-baseline deviation) is treated as the most severe
    because a change against a previously-constant series is a strong
    signal. Otherwise larger z-scores escalate.
    """
    if z is None or z >= 5.0:
        return Severity.CRITICAL
    if z >= 4.0:
        return Severity.HIGH
    return Severity.MEDIUM


class MetricAnomalyDetector:
    """Deterministic z-score anomaly detector over a single metric series.

    Configuration-driven (thresholds and category are constructor args,
    not literals) so a fork tunes it without editing this class.
    """

    def __init__(
        self,
        *,
        detector_id: str,
        category: Category = Category.RELIABILITY,
        min_samples: int = 30,
        z_threshold: float = 3.0,
        source: str = _DEFAULT_SOURCE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not detector_id:
            raise ValueError("detector_id MUST be non-empty")
        if min_samples < 2:
            raise ValueError("min_samples MUST be >= 2 (a baseline needs variance)")
        if z_threshold <= 0:
            raise ValueError("z_threshold MUST be > 0")
        self._detector_id = detector_id
        self._category = category
        self._min_samples = min_samples
        self._z_threshold = z_threshold
        self._source = source
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def evaluate(
        self,
        *,
        metric: str,
        resource_ref: str,
        history: Sequence[MetricSample],
        observed: MetricSample,
        window_bucket: str,
    ) -> AnomalyFinding | None:
        """Return an :class:`AnomalyFinding` when ``observed`` deviates.

        ``None`` means "no finding": cold-start (history below
        ``min_samples``), a within-threshold deviation, or a flat
        baseline whose observed value matches it. The check is pure - the
        same inputs always yield the same result (deterministic replay).
        """
        if len(history) < self._min_samples:
            return None  # cold-start: abstain rather than fire on a thin baseline
        values = [s.value for s in history]
        # Non-finite input (NaN / +-Inf) poisons the baseline: a NaN makes
        # every ``abs(z) < threshold`` comparison False (so the detector would
        # FIRE a spurious finding), and an Inf yields z=Inf that serializes to
        # invalid JSON (``Infinity``) in the emitted Event payload. Abstain
        # (fail-closed), exactly like a cold-start, rather than judge on
        # corrupt telemetry.
        if not math.isfinite(observed.value) or not all(math.isfinite(v) for v in values):
            return None
        mean = statistics.fmean(values)
        std = statistics.pstdev(values)

        if std == 0.0:
            if observed.value == mean:
                return None
            z: float | None = None
            direction = "over" if observed.value > mean else "under"
            reason = "flat_baseline_deviation"
        else:
            z_signed = (observed.value - mean) / std
            if abs(z_signed) < self._z_threshold:
                return None
            z = abs(z_signed)
            direction = "over" if z_signed > 0 else "under"
            reason = f"z_score {z:.2f} >= threshold {self._z_threshold:.2f}"

        return AnomalyFinding(
            detector_id=self._detector_id,
            metric=metric,
            resource_ref=resource_ref,
            window_bucket=window_bucket,
            baseline_mean=mean,
            baseline_std=std,
            observed=observed.value,
            z_score=z,
            direction=direction,
            category=self._category,
            severity=_severity_from_z(z),
            idempotency_key=self._idempotency_key(metric=metric, window_bucket=window_bucket),
            reason=reason,
        )

    def to_event(self, finding: AnomalyFinding, *, mode: Mode = Mode.SHADOW) -> Event:
        """Normalize a finding into an Event that re-enters event-ingest.

        The idempotency key is derived from ``detector + metric + window``
        so repeated evaluation ticks on the same window deduplicate
        instead of piling up (per observability-and-detection.md section 2).
        """
        now = self._clock()
        payload: dict[str, object] = {
            "kind": "anomaly",
            "detector_id": finding.detector_id,
            "metric": finding.metric,
            "resource": {"resource_ref": finding.resource_ref},
            "baseline_mean": finding.baseline_mean,
            "baseline_std": finding.baseline_std,
            "observed": finding.observed,
            "z_score": finding.z_score,
            "direction": finding.direction,
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
            event_type=_ANOMALY_EVENT_TYPE,
            resource_ref=finding.resource_ref,
            payload=payload,
            detected_at=now,
            ingested_at=now,
            mode=mode,
        )

    def _idempotency_key(self, *, metric: str, window_bucket: str) -> str:
        return str(
            uuid5(NAMESPACE_URL, f"fdai-anomaly:{self._detector_id}:{metric}:{window_bucket}")
        )


__all__ = [
    "AnomalyFinding",
    "MetricAnomalyDetector",
]
