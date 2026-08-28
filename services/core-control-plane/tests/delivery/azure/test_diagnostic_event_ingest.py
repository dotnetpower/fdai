"""Diagnostic Event Hub normalization bridge tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.delivery.azure.diagnostic_event_ingest import DiagnosticEventIngestBridge
from fdai.delivery.azure.monitor_events import DiagnosticNormalizerOptions
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
_TARGET = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/providers/Microsoft.ContainerService/"
    "managedClusters/aks-example"
)


def _bridge(
    source: InMemoryEventBus,
    target: InMemoryEventBus,
) -> DiagnosticEventIngestBridge:
    return DiagnosticEventIngestBridge(
        source_bus=source,
        target_bus=target,
        source_topic="azure.diagnostics",
        target_topic="fdai.events",
        consumer_group="fdai-diagnostic-normalizer",
        options=DiagnosticNormalizerOptions(metric_whitelist=("node_cpu_percent",)),
        clock=lambda: _NOW,
    )


async def test_bridge_publishes_normalized_events_with_resource_partition_key() -> None:
    source = InMemoryEventBus()
    target = InMemoryEventBus()
    bridge = _bridge(source, target)
    envelope = EventEnvelope(
        topic="azure.diagnostics",
        key="source-record-1",
        payload={
            "records": [
                {
                    "time": (_NOW - timedelta(seconds=10)).isoformat(),
                    "resourceId": _TARGET,
                    "category": "AllMetrics",
                    "metricName": "node_cpu_percent",
                    "average": 72.5,
                }
            ]
        },
        offset=1,
    )

    count = await bridge.process(envelope)
    published = await anext(target.subscribe("fdai.events", "test-reader"))

    assert count == 1
    assert published.key == published.payload["resource_ref"]
    assert published.payload["source"] == "azure_diagnostic_metrics"
    assert published.payload["incident_correlation"] == "none"


async def test_bridge_dead_letters_malformed_matching_record() -> None:
    source = InMemoryEventBus()
    target = InMemoryEventBus()
    bridge = _bridge(source, target)
    envelope = EventEnvelope(
        topic="azure.diagnostics",
        key="source-record-1",
        payload={
            "records": [
                {
                    "time": (_NOW - timedelta(seconds=10)).isoformat(),
                    "resourceId": _TARGET,
                    "category": "AllMetrics",
                    "metricName": "node_cpu_percent",
                    "average": "NaN",
                }
            ]
        },
        offset=1,
    )

    count = await bridge.process(envelope)
    dead_letter = await anext(source.subscribe("azure.diagnostics.dlq", "test-dlq-reader"))

    assert count == 0
    assert dead_letter.key == "source-record-1"
    assert dead_letter.payload["reason"] == "AzureMonitorNormalizationError"


async def test_bridge_skips_non_whitelisted_records_without_dead_letter() -> None:
    source = InMemoryEventBus()
    target = InMemoryEventBus()
    bridge = _bridge(source, target)
    envelope = EventEnvelope(
        topic="azure.diagnostics",
        key="source-record-1",
        payload={
            "records": [
                {
                    "time": (_NOW - timedelta(seconds=10)).isoformat(),
                    "resourceId": _TARGET,
                    "category": "AllMetrics",
                    "metricName": "ignored_metric",
                    "average": 72.5,
                }
            ]
        },
        offset=1,
    )

    assert await bridge.process(envelope) == 0
