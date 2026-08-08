from __future__ import annotations

import asyncio
from datetime import timedelta

from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import ForecastEpisode, ForecastEvaluationKind
from fdai.core.detection.forecast_episode_testing import InMemoryForecastEpisodeStore
from fdai.core.detection.forecast_outcome import ForecastObservation
from fdai.shared.contracts.models import TelemetryCompleteness

from .test_forecast_episode import T0, _episode


class _Observations:
    def __init__(self, observation: ForecastObservation) -> None:
        self._observation = observation

    async def observe(self, episode: ForecastEpisode) -> ForecastObservation:
        del episode
        return self._observation


async def test_duplicate_closure_creates_one_terminal_outcome_and_outbox() -> None:
    store = InMemoryForecastEpisodeStore()
    await store.record(_episode())
    coordinator = ForecastClosureCoordinator(
        store=store,
        observations=_Observations(
            ForecastObservation(
                observed_value=96.0,
                actual_breach_at=T0 + timedelta(minutes=30),
                telemetry_completeness=TelemetryCompleteness.COMPLETE,
                evidence_refs=("observation:1",),
            )
        ),
    )
    now = T0 + timedelta(hours=1, minutes=5)
    assert await coordinator.close_due(now=now) == 1
    assert await coordinator.close_due(now=now) == 0
    assert len(store.closures) == 1
    assert len(store.outbox) == 1


async def test_concurrent_closure_claims_one_episode_once() -> None:
    store = InMemoryForecastEpisodeStore()
    await store.record(_episode())
    coordinator = ForecastClosureCoordinator(
        store=store,
        observations=_Observations(
            ForecastObservation(
                observed_value=70.0,
                actual_breach_at=None,
                telemetry_completeness=TelemetryCompleteness.COMPLETE,
                evidence_refs=("observation:1",),
            )
        ),
    )
    now = T0 + timedelta(hours=1, minutes=5)
    results = await asyncio.gather(
        coordinator.close_due(now=now),
        coordinator.close_due(now=now),
    )
    assert sum(results) == 1
    assert len(store.outbox) == 1


async def test_negative_evaluation_breach_becomes_false_negative() -> None:
    store = InMemoryForecastEpisodeStore()
    await store.record(
        _episode(
            evaluation_kind=ForecastEvaluationKind.PREDICTED_NO_BREACH,
            predicted_value=None,
            interval_lower=None,
            interval_upper=None,
        )
    )
    coordinator = ForecastClosureCoordinator(
        store=store,
        observations=_Observations(
            ForecastObservation(
                observed_value=96.0,
                actual_breach_at=T0 + timedelta(minutes=30),
                telemetry_completeness=TelemetryCompleteness.COMPLETE,
                evidence_refs=("breach:1",),
            )
        ),
    )
    assert await coordinator.close_due(now=T0 + timedelta(hours=1, minutes=5)) == 1
    payload = next(
        item.payload for item in store.outbox.values() if item.topic == "object.forecast-outcome"
    )
    assert payload["label"] == "false_negative"
    assert payload["miss_origin"] == "model"


async def test_abstained_evaluation_breach_is_pipeline_miss() -> None:
    store = InMemoryForecastEpisodeStore()
    await store.record(
        _episode(
            evaluation_kind=ForecastEvaluationKind.ABSTAINED,
            predicted_value=None,
            interval_lower=None,
            interval_upper=None,
            abstain_reason="telemetry_unavailable",
        )
    )
    coordinator = ForecastClosureCoordinator(
        store=store,
        observations=_Observations(
            ForecastObservation(
                observed_value=96.0,
                actual_breach_at=T0 + timedelta(minutes=30),
                telemetry_completeness=TelemetryCompleteness.COMPLETE,
                evidence_refs=("breach:1",),
            )
        ),
    )
    assert await coordinator.close_due(now=T0 + timedelta(hours=1, minutes=5)) == 1
    payload = next(
        item.payload for item in store.outbox.values() if item.topic == "object.forecast-outcome"
    )
    assert payload["label"] == "false_negative"
    assert payload["miss_origin"] == "pipeline"


async def test_negative_evaluation_does_not_count_post_horizon_breach_as_miss() -> None:
    store = InMemoryForecastEpisodeStore()
    await store.record(
        _episode(
            evaluation_kind=ForecastEvaluationKind.PREDICTED_NO_BREACH,
            predicted_value=None,
            interval_lower=None,
            interval_upper=None,
        )
    )
    coordinator = ForecastClosureCoordinator(
        store=store,
        observations=_Observations(
            ForecastObservation(
                observed_value=96.0,
                actual_breach_at=T0 + timedelta(hours=1, minutes=1),
                telemetry_completeness=TelemetryCompleteness.COMPLETE,
                evidence_refs=("late-breach:1",),
            )
        ),
    )
    assert await coordinator.close_due(now=T0 + timedelta(hours=1, minutes=5)) == 1
    assert store.outbox == {}
