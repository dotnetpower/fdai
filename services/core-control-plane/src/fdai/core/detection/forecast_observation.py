"""Build forecast closure observations from provider-neutral metric telemetry."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.detection.forecast_episode import ForecastEpisode
from fdai.core.detection.forecast_outcome import ForecastObservation
from fdai.shared.contracts.models import TelemetryCompleteness
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)


@dataclass(frozen=True, slots=True)
class ForecastObservationPolicy:
    """Bound telemetry admission independently of the forecast's ingestion grace."""

    min_samples: int = 3
    max_gap_seconds: int = 300
    max_points: int = 10_000
    timeout_seconds: float = 5.0
    min_coverage_ratio: float = 0.9

    def __post_init__(self) -> None:
        for name in ("min_samples", "max_gap_seconds", "max_points"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"forecast observation {name} MUST be a positive integer")
        if not 2 <= self.min_samples <= self.max_points <= 100_000:
            raise ValueError(
                "forecast observation sample bounds MUST satisfy 2 <= min <= max <= 100000"
            )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 60
        ):
            raise ValueError("forecast observation timeout MUST be finite and in (0, 60]")
        if (
            isinstance(self.min_coverage_ratio, bool)
            or not isinstance(self.min_coverage_ratio, (int, float))
            or not math.isfinite(self.min_coverage_ratio)
            or not 0 < self.min_coverage_ratio <= 1
        ):
            raise ValueError("forecast observation coverage ratio MUST be in (0, 1]")

    @property
    def evidence_ref(self) -> str:
        """Identify the exact admission policy used to score the observation."""
        material = json.dumps(
            {
                "version": "1.0.0",
                "min_samples": self.min_samples,
                "max_gap_seconds": self.max_gap_seconds,
                "max_points": self.max_points,
                "timeout_seconds": float(self.timeout_seconds),
                "min_coverage_ratio": float(self.min_coverage_ratio),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"forecast-observation-policy:{hashlib.sha256(material.encode()).hexdigest()}"


class MetricForecastObservationProvider:
    """Collect bounded target-specific telemetry and hold incomplete or conflicting windows."""

    def __init__(
        self,
        provider: MetricProvider,
        *,
        resource_label: str = "resource_id",
        policy: ForecastObservationPolicy | None = None,
    ) -> None:
        if not resource_label.strip():
            raise ValueError("forecast observation resource label MUST be non-empty")
        self._provider = provider
        self._resource_label = resource_label
        self._policy = policy or ForecastObservationPolicy()

    async def observe(self, episode: ForecastEpisode) -> ForecastObservation:
        """Return an explicit unavailable or partial result when admission cannot be proved."""
        query = MetricQuery(
            metric_name=episode.metric,
            labels={self._resource_label: episode.target_ref},
            since=episode.horizon_started_at,
            until=episode.closure_due_at,
        )
        by_time: dict[datetime, MetricPoint] = {}
        series_labels: dict[str, str] | None = None
        try:
            async with asyncio.timeout(self._policy.timeout_seconds):
                count = 0
                stream = self._provider.query(query)
                try:
                    async for point in stream:
                        count += 1
                        if count > self._policy.max_points:
                            return self._unavailable(episode, "point-limit")
                        if (
                            point.metric_name != episode.metric
                            or point.labels.get(self._resource_label) != episode.target_ref
                            or point.at.tzinfo is None
                            or isinstance(point.value, bool)
                            or not isinstance(point.value, (int, float))
                            or not math.isfinite(point.value)
                            or not episode.horizon_started_at <= point.at <= episode.closure_due_at
                        ):
                            return self._unavailable(episode, "invalid-sample")
                        if series_labels is not None and point.labels != series_labels:
                            return self._unavailable(episode, "mixed-series")
                        series_labels = dict(point.labels)
                        observed_at = point.at.astimezone(UTC)
                        previous = by_time.get(observed_at)
                        if previous is not None and previous.value != point.value:
                            return self._unavailable(episode, "conflicting-sample")
                        by_time[observed_at] = MetricPoint(
                            metric_name=point.metric_name,
                            at=observed_at,
                            value=point.value,
                            labels=series_labels,
                        )
                finally:
                    close = getattr(stream, "aclose", None)
                    if close is not None:
                        await close()
        except (MetricProviderError, TimeoutError, OverflowError):
            return self._unavailable(episode, "provider-unavailable")
        usable = [by_time[observed_at] for observed_at in sorted(by_time)]
        if not usable:
            return self._unavailable(episode, "empty-window")
        horizon_points = [point for point in usable if point.at <= episode.horizon_ended_at]
        boundaries = (
            episode.horizon_started_at,
            *(point.at for point in horizon_points),
            episode.horizon_ended_at,
        )
        horizon_seconds = (episode.horizon_ended_at - episode.horizon_started_at).total_seconds()
        covered_seconds = (
            (horizon_points[-1].at - horizon_points[0].at).total_seconds()
            if len(horizon_points) >= 2
            else 0.0
        )
        completeness = (
            TelemetryCompleteness.COMPLETE
            if len(horizon_points) >= self._policy.min_samples
            and horizon_seconds > 0
            and covered_seconds / horizon_seconds >= self._policy.min_coverage_ratio
            and all(
                (later - earlier).total_seconds() <= self._policy.max_gap_seconds
                for earlier, later in zip(boundaries, boundaries[1:], strict=False)
            )
            else TelemetryCompleteness.PARTIAL
        )
        breach = next((point for point in usable if _breached(episode, point)), None)
        observed = horizon_points[-1].value if horizon_points else None
        return ForecastObservation(
            observed_value=observed,
            actual_breach_at=breach.at if breach is not None else None,
            telemetry_completeness=completeness,
            evidence_refs=(
                _evidence_ref(episode, _window_digest(episode, usable)),
                self._policy.evidence_ref,
            ),
        )

    def _unavailable(self, episode: ForecastEpisode, reason: str) -> ForecastObservation:
        return ForecastObservation(
            observed_value=None,
            actual_breach_at=None,
            telemetry_completeness=TelemetryCompleteness.UNAVAILABLE,
            evidence_refs=(_evidence_ref(episode, reason), self._policy.evidence_ref),
        )


def _breached(episode: ForecastEpisode, point: MetricPoint) -> bool:
    if episode.direction == "rising":
        return point.value >= episode.threshold
    return point.value <= episode.threshold


def _window_digest(episode: ForecastEpisode, points: list[MetricPoint]) -> str:
    material = json.dumps(
        {
            "access_scope_digest": episode.access_scope_digest,
            "target_digest": episode.target_digest,
            "metric": episode.metric,
            "series_labels": dict(points[0].labels),
            "horizon_started_at": episode.horizon_started_at.astimezone(UTC).isoformat(),
            "horizon_ended_at": episode.horizon_ended_at.astimezone(UTC).isoformat(),
            "closure_due_at": episode.closure_due_at.astimezone(UTC).isoformat(),
            "points": [
                [
                    point.at.astimezone(UTC).isoformat(),
                    format(0.0 if point.value == 0 else point.value, ".17g"),
                ]
                for point in points
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _evidence_ref(episode: ForecastEpisode, suffix: str) -> str:
    return f"metric-observation:{episode.metric}:{suffix}"


__all__ = ["ForecastObservationPolicy", "MetricForecastObservationProvider"]
