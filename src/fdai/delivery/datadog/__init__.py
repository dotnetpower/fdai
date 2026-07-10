"""Datadog delivery adapters.

Ships a live :class:`~fdai.shared.providers.metric.MetricProvider`
implementation against the Datadog metrics query API. ``core/`` never
imports this package; a fork binds it at the composition root in place
of :class:`~fdai.shared.providers.metric.NoopMetricProvider`.
"""

from fdai.delivery.datadog.metric import (
    DatadogMetricConfig,
    DatadogMetricProvider,
)

__all__ = [
    "DatadogMetricConfig",
    "DatadogMetricProvider",
]
