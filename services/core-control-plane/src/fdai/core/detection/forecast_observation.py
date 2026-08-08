"""Build forecast closure observations from provider-neutral metric telemetry."""

from __future__ import annotations

import hashlib
import math

from fdai.core.detection.forecast_episode import ForecastEpisode
from fdai.core.detection.forecast_outcome import ForecastObservation
from fdai.shared.contracts.models import TelemetryCompleteness
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)


class MetricForecastObservationProvider:
    def __init__(self, provider: MetricProvider, *, resource_label: str = "resource_id") -> None:
        self._provider = provider
        self._resource_label = resource_label

    async def observe(self, episode: ForecastEpisode) -> ForecastObservation:
        query = MetricQuery(
            metric_name=episode.metric,
            labels={self._resource_label: episode.target_ref},
            since=episode.horizon_started_at,
            until=episode.closure_due_at,
        )
        try:
            points = [point async for point in self._provider.query(query)]
        except MetricProviderError:
            return ForecastObservation(
                observed_value=None,
                actual_breach_at=None,
                telemetry_completeness=TelemetryCompleteness.UNAVAILABLE,
                evidence_refs=(_evidence_ref(episode, "provider-error"),),
            )
        usable = sorted(
            (
                point
                for point in points
                if math.isfinite(point.value)
                and episode.horizon_started_at <= point.at <= episode.closure_due_at
            ),
            key=lambda point: point.at,
        )
        if not usable:
            return ForecastObservation(
                observed_value=None,
                actual_breach_at=None,
                telemetry_completeness=TelemetryCompleteness.UNAVAILABLE,
                evidence_refs=(_evidence_ref(episode, "empty-window"),),
            )
        latest = usable[-1]
        completeness = (
            TelemetryCompleteness.COMPLETE
            if latest.at >= episode.horizon_ended_at
            else TelemetryCompleteness.PARTIAL
        )
        breach = next((point for point in usable if _breached(episode, point)), None)
        horizon_points = [point for point in usable if point.at <= episode.horizon_ended_at]
        observed = horizon_points[-1].value if horizon_points else None
        return ForecastObservation(
            observed_value=observed,
            actual_breach_at=breach.at if breach is not None else None,
            telemetry_completeness=completeness,
            evidence_refs=(_evidence_ref(episode, _window_digest(usable)),),
        )


def _breached(episode: ForecastEpisode, point: MetricPoint) -> bool:
    if episode.direction == "rising":
        return point.value >= episode.threshold
    return point.value <= episode.threshold


def _window_digest(points: list[MetricPoint]) -> str:
    material = "|".join(f"{point.at.isoformat()}:{point.value:.17g}" for point in points)
    return hashlib.sha256(material.encode()).hexdigest()


def _evidence_ref(episode: ForecastEpisode, suffix: str) -> str:
    return f"metric-observation:{episode.metric}:{suffix}"


__all__ = ["MetricForecastObservationProvider"]
