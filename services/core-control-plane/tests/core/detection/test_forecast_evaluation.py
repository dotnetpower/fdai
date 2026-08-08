from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.detection.forecast_episode import ForecastEvaluationKind
from fdai.core.detection.forecast_episode_testing import InMemoryForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import (
    ForecastEpisodeEvaluator,
    ForecastTargetSpec,
)
from fdai.core.detection.metric_source import MetricSeriesSource
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider

T0 = datetime(2026, 7, 23, 15, 0, tzinfo=UTC)


def _target(**overrides: object) -> ForecastTargetSpec:
    values: dict[str, object] = {
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "scorer_version": "1.0.0",
        "access_scope_digest": "a" * 64,
        "resource_ref": "resource-1",
        "metric": "capacity_percent",
        "threshold": 20.0,
        "horizon_seconds": 100,
        "lookback_seconds": 300,
        "telemetry_grace_seconds": 60,
    }
    values.update(overrides)
    return ForecastTargetSpec(**values)  # type: ignore[arg-type]


def _source(values: list[float]) -> MetricSeriesSource:
    return MetricSeriesSource(
        StaticMetricProvider(
            [
                MetricPoint(
                    metric_name="capacity_percent",
                    at=T0 + timedelta(seconds=index),
                    value=value,
                    labels={"resource_id": "resource-1"},
                )
                for index, value in enumerate(values)
            ]
        )
    )


async def test_positive_evaluation_records_forecast_publication_atomically() -> None:
    store = InMemoryForecastEpisodeStore()
    evaluator = ForecastEpisodeEvaluator(
        source=_source([float(value) for value in range(10)]),
        store=store,
        targets=(_target(),),
    )
    assert await evaluator.evaluate(now=T0 + timedelta(seconds=10)) == 1
    episode = next(iter(store.episodes.values()))
    assert episode.evaluation_kind is ForecastEvaluationKind.PREDICTED_BREACH
    publication = next(iter(store.outbox.values()))
    assert publication.topic == "object.forecast"
    assert publication.payload["prediction_id"] == str(episode.episode_id)


async def test_flat_series_records_negative_without_publication() -> None:
    store = InMemoryForecastEpisodeStore()
    evaluator = ForecastEpisodeEvaluator(
        source=_source([5.0] * 10),
        store=store,
        targets=(_target(),),
    )
    assert await evaluator.evaluate(now=T0 + timedelta(seconds=10)) == 1
    episode = next(iter(store.episodes.values()))
    assert episode.evaluation_kind is ForecastEvaluationKind.PREDICTED_NO_BREACH
    assert store.outbox == {}


async def test_cold_start_records_abstain_not_negative() -> None:
    store = InMemoryForecastEpisodeStore()
    evaluator = ForecastEpisodeEvaluator(
        source=_source([1.0, 2.0]),
        store=store,
        targets=(_target(),),
    )
    assert await evaluator.evaluate(now=T0 + timedelta(seconds=10)) == 1
    episode = next(iter(store.episodes.values()))
    assert episode.evaluation_kind is ForecastEvaluationKind.ABSTAINED
    assert episode.abstain_reason == "insufficient_samples"
