"""Verify an immutable forecast source for bounded human response timing, never authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Protocol
from uuid import UUID

from fdai.core.detection.forecast_episode import (
    ForecastEpisode,
    ForecastEpisodeState,
    ForecastEvaluationKind,
    forecast_episode_id,
)


@dataclass(frozen=True, slots=True)
class ForecastUrgencySource:
    """An exact authoritative episode joined to its retained forecast publication."""

    episode: ForecastEpisode
    payload: Mapping[str, Any]


class ForecastUrgencyReader(Protocol):
    """Read one source without accepting forecast facts from an approval request."""

    async def read(self, episode_id: UUID) -> ForecastUrgencySource | None: ...


@dataclass(frozen=True, slots=True)
class VerifiedForecastUrgency:
    """Process-local timing proof; serialization or a caller boolean cannot reconstruct it."""

    episode_id: UUID
    source_digest: str
    feature_cutoff: datetime
    predicted_breach_at: datetime
    expires_at: datetime
    confidence: float

    def __post_init__(self) -> None:
        if (
            len(self.source_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.source_digest)
            or any(
                value.utcoffset() is None
                for value in (
                    self.feature_cutoff,
                    self.predicted_breach_at,
                    self.expires_at,
                )
            )
            or not self.feature_cutoff < self.expires_at <= self.predicted_breach_at
            or type(self.confidence) not in {int, float}
            or not isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("verified forecast timing is malformed")

    def remaining_seconds(self, at: datetime) -> int | None:
        """Return only an unexpired positive ETA at a timezone-aware current clock."""
        if at.utcoffset() is None or not self.feature_cutoff <= at < self.expires_at:
            return None
        seconds = int((self.predicted_breach_at - at).total_seconds())
        return seconds if seconds > 0 else None


def verify_forecast_urgency(
    source: ForecastUrgencySource,
    *,
    episode_id: UUID,
    target_ref: str,
    at: datetime,
    maximum_age_seconds: int = 300,
) -> VerifiedForecastUrgency | None:
    """Require exact lineage, current open state, a breached band, and retained timing metadata."""
    episode, payload = source.episode, source.payload
    if not isinstance(payload, Mapping):
        return None
    if at.utcoffset() is None or type(maximum_age_seconds) is not int or maximum_age_seconds < 1:
        raise ValueError("forecast timing requires an aware clock and positive age bound")
    if (
        episode.episode_id != episode_id
        or episode.target_ref != target_ref
        or episode.correlation_id != f"forecast:{episode_id}"
        or episode.state is not ForecastEpisodeState.OPEN
        or episode.evaluation_kind is not ForecastEvaluationKind.PREDICTED_BREACH
        or not episode.feature_cutoff <= at < episode.horizon_ended_at
        or at - episode.feature_cutoff >= timedelta(seconds=maximum_age_seconds)
    ):
        return None
    timestamps: dict[str, datetime] = {}
    for key in ("feature_cutoff", "horizon_started_at", "horizon_ended_at"):
        value = payload.get(key)
        if not isinstance(value, str):
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None or parsed != getattr(episode, key):
            return None
        timestamps[key] = parsed
    canonical_id = forecast_episode_id(
        access_scope_digest=episode.access_scope_digest,
        detector_id=episode.detector_id,
        detector_version=episode.detector_version,
        target_ref=episode.target_ref,
        metric=episode.metric,
        feature_cutoff=timestamps["feature_cutoff"],
        horizon_ended_at=timestamps["horizon_ended_at"],
    )
    if episode_id != canonical_id:
        return None
    expected = {
        "prediction_id": str(episode_id),
        "correlation_id": episode.correlation_id,
        "idempotency_key": f"forecast:{episode_id}",
        "resource_id": target_ref,
        "target_digest": episode.target_digest,
        "detector_id": episode.detector_id,
        "detector_version": episode.detector_version,
        "access_scope_digest": episode.access_scope_digest,
        "metric": episode.metric,
        "feature_cutoff": payload["feature_cutoff"],
        "horizon_started_at": payload["horizon_started_at"],
        "horizon_ended_at": payload["horizon_ended_at"],
        "direction": episode.direction,
        "threshold": episode.threshold,
        "predicted_value": episode.predicted_value,
        "interval_lower": episode.interval_lower,
        "interval_upper": episode.interval_upper,
        "evidence_refs": list(episode.evidence_refs),
        "mode": episode.mode.value,
    }
    if set(payload) != set(expected) | {"approval_timing"} or any(
        payload.get(key) != value for key, value in expected.items()
    ):
        return None
    if any(
        isinstance(payload[field], bool)
        for field in (
            "threshold",
            "predicted_value",
            "interval_lower",
            "interval_upper",
        )
    ):
        return None
    if (
        episode.interval_lower is None
        or episode.interval_upper is None
        or episode.predicted_value is None
        or not episode.interval_lower <= episode.predicted_value <= episode.interval_upper
        or (episode.direction == "rising" and episode.interval_lower < episode.threshold)
        or (episode.direction == "falling" and episode.interval_upper > episode.threshold)
    ):
        return None
    timing = payload.get("approval_timing")
    if not isinstance(timing, Mapping) or set(timing) != {
        "schema_version",
        "predicted_breach_at",
        "confidence_level",
    }:
        return None
    if timing["schema_version"] != "1.0.0" or timing["confidence_level"] not in {
        "0.80",
        "0.90",
        "0.95",
        "0.99",
    }:
        return None
    breach = datetime.fromisoformat(timing["predicted_breach_at"])
    if breach.utcoffset() is None or not at < breach <= episode.horizon_ended_at:
        return None
    canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(canonical.encode()) > 65536:
        return None
    return VerifiedForecastUrgency(
        episode_id=episode_id,
        source_digest=hashlib.sha256(canonical.encode()).hexdigest(),
        feature_cutoff=episode.feature_cutoff,
        predicted_breach_at=breach,
        expires_at=min(breach, episode.feature_cutoff + timedelta(seconds=maximum_age_seconds)),
        confidence=float(timing["confidence_level"]),
    )


async def bind_forecast_timing_context(
    reader: ForecastUrgencyReader | None,
    *,
    correlation_id: str,
    target_ref: str,
    impact: str,
    context: Mapping[str, Any] | None,
    at: datetime,
) -> dict[str, Any]:
    """Resolve a bounded current source or keep conservative timing with a stable reason."""
    result = {"finding_class": (context or {}).get("finding_class"), "impact": impact}
    result["forecast_timing_status"] = "unavailable"
    if reader is None or not correlation_id.startswith("forecast:"):
        return result
    try:
        episode_id = UUID(correlation_id.removeprefix("forecast:"))
        if correlation_id != f"forecast:{episode_id}":
            return result
        async with asyncio.timeout(5):
            source = await reader.read(episode_id)
        verified = (
            None
            if source is None
            else verify_forecast_urgency(
                source,
                episode_id=episode_id,
                target_ref=target_ref,
                at=at,
            )
        )
    except (TimeoutError, OSError, RuntimeError, TypeError, ValueError):
        return result
    if verified is not None:
        result.update(
            finding_class="forecast.breach",
            verified_forecast_urgency=verified,
            forecast_timing_status="verified",
        )
    return result


__all__ = [
    "ForecastUrgencyReader",
    "ForecastUrgencySource",
    "VerifiedForecastUrgency",
    "bind_forecast_timing_context",
    "verify_forecast_urgency",
]
