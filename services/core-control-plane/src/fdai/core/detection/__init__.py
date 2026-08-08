"""Detection signals - anomaly / forecast finding producers.

See [observability](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md).
Detectors are out-of-band producers: they emit normalized findings that
re-enter ``event-ingest`` and flow through the same trust-router ->
risk-gate path, never a side channel.
"""

from __future__ import annotations

from fdai.core.detection.anomaly import AnomalyFinding, MetricAnomalyDetector
from fdai.core.detection.composite import (
    CompositeAnomalyDetector,
    CompositeAnomalyFinding,
)
from fdai.core.detection.forecast import ForecastFinding, LinearForecastDetector
from fdai.core.detection.forecast_band import ForecastBand, prediction_band
from fdai.core.detection.insight_source import OperationalInsightSource
from fdai.core.detection.insights import (
    InsightObservation,
    InsightOperator,
    InsightRecipe,
    OperationalInsightEngine,
    OperationalInsightFinding,
)
from fdai.core.detection.metric_source import MetricSeries, MetricSeriesSource
from fdai.core.detection.seasonal import PhaseFn, SeasonalAnomalyDetector
from fdai.core.detection.series import MetricSample
from fdai.core.detection.signals import (
    SIGNAL_BACKEND_HEALTH,
    SIGNAL_DB_CPU,
    SIGNAL_GATEWAY_LATENCY,
    SIGNAL_HOST_CPU,
    SIGNAL_HOST_MEMORY,
    SIGNAL_MEMBER_HOTSPOT,
    SIGNAL_NODE_CPU,
    SIGNAL_POD_RESTART,
    SIGNAL_RATE_LIMIT,
    SIGNAL_REQUEST_FAILURE,
    SIGNAL_ROLLOUT_STALL,
    SignalRole,
    SignalSpec,
    is_known_signal,
    known_signals,
    signals_with_role,
)

__all__ = [
    "SIGNAL_BACKEND_HEALTH",
    "SIGNAL_DB_CPU",
    "SIGNAL_GATEWAY_LATENCY",
    "SIGNAL_HOST_CPU",
    "SIGNAL_HOST_MEMORY",
    "SIGNAL_MEMBER_HOTSPOT",
    "SIGNAL_NODE_CPU",
    "SIGNAL_POD_RESTART",
    "SIGNAL_RATE_LIMIT",
    "SIGNAL_REQUEST_FAILURE",
    "SIGNAL_ROLLOUT_STALL",
    "AnomalyFinding",
    "CompositeAnomalyDetector",
    "CompositeAnomalyFinding",
    "ForecastBand",
    "ForecastFinding",
    "InsightObservation",
    "InsightOperator",
    "InsightRecipe",
    "LinearForecastDetector",
    "MetricAnomalyDetector",
    "MetricSample",
    "MetricSeries",
    "MetricSeriesSource",
    "OperationalInsightEngine",
    "OperationalInsightFinding",
    "OperationalInsightSource",
    "PhaseFn",
    "SeasonalAnomalyDetector",
    "SignalRole",
    "SignalSpec",
    "is_known_signal",
    "known_signals",
    "prediction_band",
    "signals_with_role",
]
