"""Shared metric-series types for detection signals.

Both the anomaly detector (section 2) and the forecast detector
(section 3) of
[observability-and-detection.md](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md)
consume the same time-ordered metric series, so the sample type lives
here to avoid one detector importing the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MetricSample:
    """One observed point in a metric series (timezone-aware timestamp)."""

    timestamp: datetime
    value: float


__all__ = ["MetricSample"]
