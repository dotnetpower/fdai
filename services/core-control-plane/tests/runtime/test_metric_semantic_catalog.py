"""Reviewed metric semantic catalog and provider binding tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai.delivery.metric_window import ProviderMetricWindowReader
from fdai.runtime.metric_semantic_catalog import load_metric_semantic_registry
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 8, 10, tzinfo=UTC)


def test_shipped_metric_semantics_load_without_language_aliases() -> None:
    registry = load_metric_semantic_registry(ROOT / "rule-catalog/vocabulary/metric-semantics.yaml")

    assert set(registry.definitions) >= {
        "request.volume",
        "request.errors",
        "storage.write.success",
        "network.change",
    }
    assert not hasattr(registry.resolve("request.volume"), "aliases")


async def test_metric_provider_binding_preserves_zero_and_marks_empty_as_gap() -> None:
    registry = load_metric_semantic_registry(ROOT / "rule-catalog/vocabulary/metric-semantics.yaml")
    definition = registry.resolve("request.volume")
    reader = ProviderMetricWindowReader(
        provider=StaticMetricProvider(
            (
                MetricPoint(
                    metric_name=definition.provider_metric,
                    at=NOW,
                    value=0.0,
                    labels={"resource_id": "service-a"},
                ),
            )
        )
    )

    observed = await reader.read(
        definition=definition,
        resource_id="service-a",
        start=NOW,
        end=NOW + timedelta(minutes=5),
    )
    missing = await ProviderMetricWindowReader(provider=StaticMetricProvider(())).read(
        definition=definition,
        resource_id="service-a",
        start=NOW,
        end=NOW + timedelta(minutes=5),
    )

    assert observed.complete is True
    assert observed.samples[0].value == 0.0
    assert missing.complete is False
    assert missing.missing_reason == "provider_gap"
