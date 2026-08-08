"""Production composition for durable forecast evaluation and closure."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator, ForecastTargetSpec
from fdai.core.detection.forecast_observation import MetricForecastObservationProvider
from fdai.core.detection.metric_source import MetricSeriesSource
from fdai.delivery.persistence.postgres_forecast_episode import (
    PostgresForecastEpisodeStore,
    PostgresForecastEpisodeStoreConfig,
)
from fdai.shared.providers.metric import MetricProvider


@dataclass(frozen=True, slots=True)
class ForecastLearningRuntime:
    store: PostgresForecastEpisodeStore
    evaluator: ForecastEpisodeEvaluator
    closer: ForecastClosureCoordinator


def build_forecast_learning_runtime(
    *,
    dsn: str | None,
    targets_json: str | None,
    metric_provider: MetricProvider,
) -> ForecastLearningRuntime | None:
    targets = parse_forecast_targets(targets_json)
    if not targets:
        return None
    if dsn is None or not dsn.strip():
        raise RuntimeError("forecast learning targets require FDAI_STATE_STORE_DSN")
    store = PostgresForecastEpisodeStore(config=PostgresForecastEpisodeStoreConfig(dsn=dsn.strip()))
    return ForecastLearningRuntime(
        store=store,
        evaluator=ForecastEpisodeEvaluator(
            source=MetricSeriesSource(metric_provider),
            store=store,
            targets=targets,
        ),
        closer=ForecastClosureCoordinator(
            store=store,
            observations=MetricForecastObservationProvider(metric_provider),
        ),
    )


def parse_forecast_targets(raw: str | None) -> tuple[ForecastTargetSpec, ...]:
    if raw is None or not raw.strip():
        return ()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("FDAI_FORECAST_TARGETS_JSON MUST be valid JSON") from exc
    if not isinstance(decoded, list):
        raise ValueError("FDAI_FORECAST_TARGETS_JSON MUST be an array")
    targets: list[ForecastTargetSpec] = []
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise ValueError(f"FDAI_FORECAST_TARGETS_JSON[{index}] MUST be an object")
        try:
            targets.append(ForecastTargetSpec(**item))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"FDAI_FORECAST_TARGETS_JSON[{index}] is invalid") from exc
    identities = {
        (target.access_scope_digest, target.detector_id, target.resource_ref, target.metric)
        for target in targets
    }
    if len(identities) != len(targets):
        raise ValueError("FDAI_FORECAST_TARGETS_JSON contains duplicate target identities")
    return tuple(targets)


__all__ = [
    "ForecastLearningRuntime",
    "build_forecast_learning_runtime",
    "parse_forecast_targets",
]
