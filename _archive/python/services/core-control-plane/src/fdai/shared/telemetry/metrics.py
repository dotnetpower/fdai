"""OpenTelemetry metrics wiring.

Day-zero uses an in-memory :class:`InMemoryMetricReader` so tests can
inspect emitted metrics without a network round trip. OTLP export lands
with W4.1.
"""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource

_CONFIGURED = False
_READER: InMemoryMetricReader | None = None


def configure_metrics(
    service_name: str,
    env: str,
    *,
    otlp_endpoint: str | None = None,
    otlp_insecure: bool = False,
) -> None:
    """Install a :class:`MeterProvider` if one has not been installed yet.

    Idempotent - a repeat call is a no-op.
    """
    global _CONFIGURED, _READER
    if _CONFIGURED:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "runtime.env": env,
        }
    )
    readers: list[MetricReader] = []
    if otlp_endpoint is None:
        _READER = InMemoryMetricReader()
        readers.append(_READER)
    else:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=otlp_endpoint, insecure=otlp_insecure)
            )
        )
    provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(provider)
    _CONFIGURED = True


def get_meter(name: str) -> metrics.Meter:
    """Return an OTel meter keyed by ``name`` (typically ``__name__``)."""
    return metrics.get_meter(name)


def in_memory_reader() -> InMemoryMetricReader | None:
    """Return the in-memory reader installed by :func:`configure_metrics`.

    Test helper - returns ``None`` when metrics have not been configured.
    """
    return _READER


__all__ = ["configure_metrics", "get_meter", "in_memory_reader"]
