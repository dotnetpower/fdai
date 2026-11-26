"""Prometheus-compatible delivery adapters."""

from fdai.delivery.prometheus.metric import (
    PrometheusMetricConfig,
    PrometheusMetricProvider,
)
from fdai.delivery.prometheus.queries import aks_managed_prometheus_queries

__all__ = [
    "PrometheusMetricConfig",
    "PrometheusMetricProvider",
    "aks_managed_prometheus_queries",
]
