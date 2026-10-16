from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.slo import SLI, SLO, SLIKind, SloRegistry
from fdai.core.slo.models import BurnRateAlertDef
from fdai.delivery.slo_burn_cli import (
    SloBurnJobConfigurationError,
    SloBurnJobSettings,
    execute_slo_burn,
    report_summary,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider

_NOW = datetime(2026, 10, 15, tzinfo=UTC)


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> PublishReceipt:
        self.published.append((topic, key))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published) - 1)


def _settings() -> SloBurnJobSettings:
    return SloBurnJobSettings(
        catalog_dir=Path("rule-catalog/slo"),
        bootstrap_servers="localhost:9092",
        topic="fdai.events",
    )


def _registry() -> SloRegistry:
    return SloRegistry(
        slos=(
            SLO(
                id="api.example.availability",
                objective_ratio=0.99,
                window_days=28,
                sli=SLI(
                    kind=SLIKind.AVAILABILITY,
                    good_query="good_events",
                    total_query="total_events",
                ),
                burn_rate_alerts=(
                    BurnRateAlertDef(
                        name="fast-burn",
                        short_window_minutes=5,
                        long_window_minutes=60,
                        burn_rate_threshold=1.0,
                    ),
                ),
            ),
        )
    )


def test_settings_require_catalog_bus_and_bounded_timeout() -> None:
    settings = SloBurnJobSettings.from_environ(
        {
            "FDAI_SLO_CATALOG_DIR": "rule-catalog/slo",
            "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
            "KAFKA_TOPIC_EVENTS": "fdai.events",
            "FDAI_SLO_BURN_TIMEOUT_SECONDS": "60",
        }
    )

    assert settings.timeout_seconds == 60
    assert settings.topic == "fdai.events"
    with pytest.raises(SloBurnJobConfigurationError, match="CATALOG_DIR"):
        SloBurnJobSettings.from_environ(
            {
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
                "KAFKA_TOPIC_EVENTS": "fdai.events",
            }
        )


async def test_execute_requires_non_empty_registry() -> None:
    with pytest.raises(SloBurnJobConfigurationError, match="at least one objective"):
        await execute_slo_burn(
            settings=_settings(),
            registry=SloRegistry(slos=()),
            metric_provider=StaticMetricProvider(()),
            event_bus=_Bus(),
        )


async def test_execute_publishes_breach_and_reports_no_authority() -> None:
    provider = StaticMetricProvider(
        (
            MetricPoint("good_events", _NOW, 980.0),
            MetricPoint("total_events", _NOW, 1000.0),
        )
    )
    bus = _Bus()

    report = await execute_slo_burn(
        settings=_settings(),
        registry=_registry(),
        metric_provider=provider,
        event_bus=bus,
        now=_NOW,
    )

    assert report.published == 1
    assert bus.published == [("fdai.events", "api.example.availability")]
    assert report_summary(report) == {
        "status": "completed",
        "evaluated": 1,
        "breached": 1,
        "published": 1,
        "insufficient": 0,
        "evaluation_error_count": 0,
        "publish_error_count": 0,
        "execution_authority": False,
    }


async def test_missing_metrics_require_retry_instead_of_all_clear() -> None:
    report = await execute_slo_burn(
        settings=_settings(),
        registry=_registry(),
        metric_provider=StaticMetricProvider(()),
        event_bus=_Bus(),
        now=_NOW,
    )

    assert report.insufficient == 1
    assert report_summary(report)["status"] == "retry_required"
