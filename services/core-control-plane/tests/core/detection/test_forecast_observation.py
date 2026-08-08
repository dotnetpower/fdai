from __future__ import annotations

from datetime import timedelta

from fdai.core.detection.forecast_observation import MetricForecastObservationProvider
from fdai.shared.contracts.models import TelemetryCompleteness
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider

from .test_forecast_episode import T0, _episode


async def test_observation_uses_first_event_time_breach() -> None:
    episode = _episode()
    provider = MetricForecastObservationProvider(
        StaticMetricProvider(
            (
                MetricPoint(
                    metric_name=episode.metric,
                    at=T0 + timedelta(minutes=20),
                    value=80.0,
                    labels={"resource_id": episode.target_ref},
                ),
                MetricPoint(
                    metric_name=episode.metric,
                    at=T0 + timedelta(minutes=30),
                    value=91.0,
                    labels={"resource_id": episode.target_ref},
                ),
                MetricPoint(
                    metric_name=episode.metric,
                    at=T0 + timedelta(hours=1),
                    value=95.0,
                    labels={"resource_id": episode.target_ref},
                ),
            )
        )
    )
    observation = await provider.observe(episode)
    assert observation.actual_breach_at == T0 + timedelta(minutes=30)
    assert observation.observed_value == 95.0
    assert observation.telemetry_completeness is TelemetryCompleteness.COMPLETE


async def test_missing_window_is_unavailable_not_false_positive() -> None:
    observation = await MetricForecastObservationProvider(StaticMetricProvider(())).observe(
        _episode()
    )
    assert observation.actual_breach_at is None
    assert observation.observed_value is None
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE


async def test_stale_window_is_partial() -> None:
    episode = _episode()
    observation = await MetricForecastObservationProvider(
        StaticMetricProvider(
            (
                MetricPoint(
                    metric_name=episode.metric,
                    at=T0 + timedelta(minutes=30),
                    value=70.0,
                    labels={"resource_id": episode.target_ref},
                ),
            )
        )
    ).observe(episode)
    assert observation.telemetry_completeness is TelemetryCompleteness.PARTIAL
