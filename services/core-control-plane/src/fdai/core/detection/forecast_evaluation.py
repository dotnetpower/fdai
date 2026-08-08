"""Evaluate configured metric targets into durable forecast episodes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from fdai.core.detection.forecast import (
    ForecastDetectorDecision,
    LinearForecastDetector,
)
from fdai.core.detection.forecast_band import prediction_band
from fdai.core.detection.forecast_episode import (
    ForecastEpisode,
    ForecastEpisodeStore,
    ForecastEvaluationKind,
    forecast_episode_id,
)
from fdai.core.detection.metric_source import MetricSeriesSource
from fdai.shared.contracts.models import Mode


@dataclass(frozen=True, slots=True)
class ForecastTargetSpec:
    detector_id: str
    detector_version: str
    scorer_version: str
    access_scope_digest: str
    resource_ref: str
    metric: str
    threshold: float
    horizon_seconds: int
    lookback_seconds: int
    telemetry_grace_seconds: int
    direction: str = "rising"
    min_samples: int = 5
    min_r_squared: float = 0.5
    confidence_level: str = "0.90"
    mode: Mode = Mode.SHADOW

    def __post_init__(self) -> None:
        if not all(
            (
                self.detector_id,
                self.detector_version,
                self.scorer_version,
                self.resource_ref,
                self.metric,
            )
        ):
            raise ValueError("forecast target identity MUST be non-empty")
        if len(self.access_scope_digest) != 64:
            raise ValueError("forecast target access scope MUST be a SHA-256 digest")
        if self.horizon_seconds < 1 or self.lookback_seconds < 1:
            raise ValueError("forecast target horizon and lookback MUST be positive")
        if self.telemetry_grace_seconds < 0:
            raise ValueError("forecast target telemetry grace MUST be non-negative")


class ForecastEpisodeEvaluator:
    def __init__(
        self,
        *,
        source: MetricSeriesSource,
        store: ForecastEpisodeStore,
        targets: tuple[ForecastTargetSpec, ...],
        bucket_seconds: int = 60,
    ) -> None:
        if bucket_seconds < 1:
            raise ValueError("forecast evaluation bucket MUST be positive")
        self._source = source
        self._store = store
        self._targets = targets
        self._bucket_seconds = bucket_seconds

    async def evaluate(self, *, now: datetime) -> int:
        if now.tzinfo is None:
            raise ValueError("forecast evaluation clock MUST be timezone-aware")
        bucket = datetime.fromtimestamp(
            int(now.timestamp()) // self._bucket_seconds * self._bucket_seconds,
            tz=now.tzinfo,
        )
        created = 0
        for target in self._targets:
            created += int(await self._evaluate_target(target, evaluated_at=now, bucket=bucket))
        return created

    async def _evaluate_target(
        self,
        target: ForecastTargetSpec,
        *,
        evaluated_at: datetime,
        bucket: datetime,
    ) -> bool:
        series = await self._source.fetch(
            metric_name=target.metric,
            resource_ref=target.resource_ref,
            since=evaluated_at - timedelta(seconds=target.lookback_seconds),
            until=evaluated_at,
        )
        detector = LinearForecastDetector(
            detector_id=target.detector_id,
            threshold=target.threshold,
            horizon_seconds=target.horizon_seconds,
            direction=target.direction,
            min_samples=target.min_samples,
            min_r_squared=target.min_r_squared,
            clock=lambda: bucket,
        )
        if series is None:
            decision = ForecastDetectorDecision.ABSTAINED
            finding = None
            reason = "telemetry_unavailable"
            feature_cutoff = bucket
        else:
            samples = (*series.history, series.observed)
            result = detector.evaluate_result(
                metric=target.metric,
                resource_ref=target.resource_ref,
                history=samples,
                window_bucket=bucket.isoformat(),
            )
            decision = result.decision
            finding = result.finding
            reason = result.reason
            feature_cutoff = series.observed.timestamp
            if finding is not None:
                band = prediction_band(finding, confidence_level=target.confidence_level)
                if not band.confident_breach:
                    decision = ForecastDetectorDecision.ABSTAINED
                    finding = None
                    reason = "uncertain_interval"
        horizon_ended_at = feature_cutoff + timedelta(seconds=target.horizon_seconds)
        episode_id = forecast_episode_id(
            access_scope_digest=target.access_scope_digest,
            detector_id=target.detector_id,
            detector_version=target.detector_version,
            target_ref=target.resource_ref,
            metric=target.metric,
            feature_cutoff=feature_cutoff,
            horizon_ended_at=horizon_ended_at,
        )
        evidence_ref = _evidence_ref(target, feature_cutoff=feature_cutoff, bucket=bucket)
        if finding is not None:
            band = prediction_band(finding, confidence_level=target.confidence_level)
            evaluation_kind = ForecastEvaluationKind.PREDICTED_BREACH
            predicted_value = finding.projected_at_horizon
            interval_lower = band.lower
            interval_upper = band.upper
            abstain_reason = None
        else:
            evaluation_kind = ForecastEvaluationKind(decision.value)
            predicted_value = None
            interval_lower = None
            interval_upper = None
            abstain_reason = reason if decision is ForecastDetectorDecision.ABSTAINED else None
        episode = ForecastEpisode(
            episode_id=episode_id,
            correlation_id=f"forecast:{episode_id}",
            detector_id=target.detector_id,
            detector_version=target.detector_version,
            scorer_version=target.scorer_version,
            access_scope_digest=target.access_scope_digest,
            target_ref=target.resource_ref,
            metric=target.metric,
            feature_cutoff=feature_cutoff,
            horizon_started_at=feature_cutoff,
            horizon_ended_at=horizon_ended_at,
            telemetry_grace_seconds=target.telemetry_grace_seconds,
            direction=target.direction,
            threshold=target.threshold,
            evaluation_kind=evaluation_kind,
            predicted_value=predicted_value,
            interval_lower=interval_lower,
            interval_upper=interval_upper,
            abstain_reason=abstain_reason,
            evidence_refs=(evidence_ref,),
            mode=target.mode,
        )
        payload = _forecast_payload(episode) if finding is not None else None
        return await self._store.record(episode, forecast_payload=payload)


def _forecast_payload(episode: ForecastEpisode) -> dict[str, object]:
    return {
        "correlation_id": episode.correlation_id,
        "idempotency_key": f"forecast:{episode.episode_id}",
        "prediction_id": str(episode.episode_id),
        "detector_id": episode.detector_id,
        "detector_version": episode.detector_version,
        "access_scope_digest": episode.access_scope_digest,
        "resource_id": episode.target_ref,
        "target_digest": episode.target_digest,
        "metric": episode.metric,
        "feature_cutoff": episode.feature_cutoff.isoformat(),
        "horizon_started_at": episode.horizon_started_at.isoformat(),
        "horizon_ended_at": episode.horizon_ended_at.isoformat(),
        "direction": episode.direction,
        "threshold": episode.threshold,
        "predicted_value": episode.predicted_value,
        "interval_lower": episode.interval_lower,
        "interval_upper": episode.interval_upper,
        "evidence_refs": list(episode.evidence_refs),
        "mode": episode.mode.value,
    }


def _evidence_ref(
    target: ForecastTargetSpec,
    *,
    feature_cutoff: datetime,
    bucket: datetime,
) -> str:
    material = ":".join(
        (target.detector_id, target.resource_ref, target.metric, feature_cutoff.isoformat())
    )
    return f"metric-window:{bucket.isoformat()}:{hashlib.sha256(material.encode()).hexdigest()}"


__all__ = ["ForecastEpisodeEvaluator", "ForecastTargetSpec"]
