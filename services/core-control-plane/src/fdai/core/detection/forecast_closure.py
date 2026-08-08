"""Deterministic terminal closure of due forecast episodes."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from fdai.core.detection.forecast_episode import (
    ForecastClosureReason,
    ForecastEpisode,
    ForecastEpisodeClosure,
    ForecastEpisodeStore,
    ForecastEvaluationKind,
)
from fdai.core.detection.forecast_outcome import (
    ForecastExpectation,
    ForecastObservation,
    close_forecast,
    close_missed_breach,
)
from fdai.shared.contracts.models import (
    ForecastMissOrigin,
    ForecastOutcome,
    TelemetryCompleteness,
)


class ForecastObservationProvider(Protocol):
    async def observe(self, episode: ForecastEpisode) -> ForecastObservation: ...


class ForecastClosureCoordinator:
    def __init__(
        self,
        *,
        store: ForecastEpisodeStore,
        observations: ForecastObservationProvider,
        lease_seconds: int = 60,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("forecast closure lease MUST be positive")
        self._store = store
        self._observations = observations
        self._lease_seconds = lease_seconds

    async def close_due(self, *, now: datetime, limit: int = 100) -> int:
        if now.tzinfo is None:
            raise ValueError("forecast closure clock MUST be timezone-aware")
        if not 1 <= limit <= 1_000:
            raise ValueError("forecast closure limit MUST be in [1, 1000]")
        episodes = await self._store.claim_due(
            now=now,
            limit=limit,
            lease_until=now + timedelta(seconds=self._lease_seconds),
        )
        closed = 0
        for episode in episodes:
            observation = await self._observations.observe(episode)
            outcome, reason = _close_episode(episode, observation, closed_at=now)
            created = await self._store.close(
                ForecastEpisodeClosure(
                    episode_id=episode.episode_id,
                    expected_revision=episode.revision,
                    closed_at=now,
                    reason=reason,
                    outcome_payload=(outcome.model_dump(mode="json") if outcome else None),
                )
            )
            closed += int(created)
        return closed


def _close_episode(
    episode: ForecastEpisode,
    observation: ForecastObservation,
    *,
    closed_at: datetime,
) -> tuple[ForecastOutcome | None, ForecastClosureReason]:
    if episode.evaluation_kind is ForecastEvaluationKind.PREDICTED_BREACH:
        if (
            episode.predicted_value is None
            or episode.interval_lower is None
            or episode.interval_upper is None
        ):
            raise RuntimeError("predicted breach episode lost its prediction evidence")
        return (
            close_forecast(
                ForecastExpectation(
                    prediction_id=episode.episode_id,
                    correlation_id=episode.correlation_id,
                    detector_id=episode.detector_id,
                    detector_version=episode.detector_version,
                    access_scope_digest=episode.access_scope_digest,
                    target_ref=episode.target_ref,
                    metric=episode.metric,
                    feature_cutoff=episode.feature_cutoff,
                    horizon_started_at=episode.horizon_started_at,
                    horizon_ended_at=episode.horizon_ended_at,
                    direction=episode.direction,  # type: ignore[arg-type]
                    threshold=episode.threshold,
                    predicted_value=episode.predicted_value,
                    interval_lower=episode.interval_lower,
                    interval_upper=episode.interval_upper,
                    evidence_refs=episode.evidence_refs,
                    mode=episode.mode,
                ),
                observation,
                closed_at=closed_at,
            ),
            ForecastClosureReason.SCORED,
        )
    if (
        observation.actual_breach_at is not None
        and observation.actual_breach_at <= episode.horizon_ended_at
    ):
        miss_origin = (
            ForecastMissOrigin.PIPELINE
            if episode.evaluation_kind is ForecastEvaluationKind.ABSTAINED
            else ForecastMissOrigin.MODEL
        )
        return (
            close_missed_breach(
                correlation_id=episode.correlation_id,
                detector_id=episode.detector_id,
                detector_version=episode.detector_version,
                access_scope_digest=episode.access_scope_digest,
                target_ref=episode.target_ref,
                metric=episode.metric,
                feature_cutoff=episode.feature_cutoff,
                horizon_started_at=episode.horizon_started_at,
                horizon_ended_at=episode.horizon_ended_at,
                direction=episode.direction,  # type: ignore[arg-type]
                threshold=episode.threshold,
                observed_value=(
                    observation.observed_value
                    if observation.observed_value is not None
                    else episode.threshold
                ),
                actual_breach_at=observation.actual_breach_at,
                evidence_refs=tuple(sorted(set(episode.evidence_refs + observation.evidence_refs))),
                closed_at=closed_at,
                miss_origin=miss_origin,
            ),
            ForecastClosureReason.SCORED,
        )
    if observation.telemetry_completeness is not TelemetryCompleteness.COMPLETE:
        return None, ForecastClosureReason.ABSTAINED_NO_BREACH
    reason = (
        ForecastClosureReason.ABSTAINED_NO_BREACH
        if episode.evaluation_kind is ForecastEvaluationKind.ABSTAINED
        else ForecastClosureReason.NEGATIVE_NO_BREACH
    )
    return None, reason


__all__ = ["ForecastClosureCoordinator", "ForecastObservationProvider"]
