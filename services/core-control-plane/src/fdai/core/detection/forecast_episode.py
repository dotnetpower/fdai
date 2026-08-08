"""Immutable forecast evaluation episodes and frozen closure policy."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai.shared.contracts.models import Mode


class ForecastEvaluationKind(StrEnum):
    PREDICTED_BREACH = "predicted_breach"
    PREDICTED_NO_BREACH = "predicted_no_breach"
    ABSTAINED = "abstained"


class ForecastEpisodeState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class ForecastClosureReason(StrEnum):
    SCORED = "scored"
    NEGATIVE_NO_BREACH = "negative_no_breach"
    ABSTAINED_NO_BREACH = "abstained_no_breach"


@dataclass(frozen=True, slots=True)
class ForecastEpisodeClosure:
    episode_id: UUID
    expected_revision: int
    closed_at: datetime
    reason: ForecastClosureReason
    outcome_payload: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class ForecastPublicationOutboxItem:
    publication_id: UUID
    episode_id: UUID
    topic: str
    payload: Mapping[str, object]
    attempts: int


class ForecastEpisodeStore(Protocol):
    async def record(
        self,
        episode: ForecastEpisode,
        *,
        forecast_payload: Mapping[str, object] | None = None,
    ) -> bool: ...

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ForecastEpisode, ...]: ...

    async def close(self, closure: ForecastEpisodeClosure) -> bool: ...

    async def claim_publications(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ForecastPublicationOutboxItem, ...]: ...

    async def complete_publication(
        self,
        publication_id: UUID,
        *,
        published_at: datetime,
    ) -> None: ...

    async def release_publication(
        self,
        publication_id: UUID,
        *,
        available_at: datetime,
        error: str,
    ) -> None: ...

    async def dead_letter_publication(
        self,
        publication_id: UUID,
        *,
        failed_at: datetime,
        error: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ForecastEpisode:
    episode_id: UUID
    correlation_id: str
    detector_id: str
    detector_version: str
    scorer_version: str
    access_scope_digest: str
    target_ref: str
    metric: str
    feature_cutoff: datetime
    horizon_started_at: datetime
    horizon_ended_at: datetime
    telemetry_grace_seconds: int
    direction: str
    threshold: float
    evaluation_kind: ForecastEvaluationKind
    evidence_refs: tuple[str, ...]
    predicted_value: float | None = None
    interval_lower: float | None = None
    interval_upper: float | None = None
    abstain_reason: str | None = None
    mode: Mode = Mode.SHADOW
    state: ForecastEpisodeState = ForecastEpisodeState.OPEN
    revision: int = 1

    def __post_init__(self) -> None:
        if not all(
            (
                self.correlation_id,
                self.detector_id,
                self.detector_version,
                self.scorer_version,
                self.target_ref,
                self.metric,
            )
        ):
            raise ValueError("forecast episode identity MUST be non-empty")
        if len(self.access_scope_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.access_scope_digest
        ):
            raise ValueError("forecast episode access scope MUST be a SHA-256 digest")
        timestamps = (self.feature_cutoff, self.horizon_started_at, self.horizon_ended_at)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("forecast episode timestamps MUST be timezone-aware")
        if not self.feature_cutoff <= self.horizon_started_at <= self.horizon_ended_at:
            raise ValueError("forecast episode timestamps MUST be ordered")
        if self.telemetry_grace_seconds < 0:
            raise ValueError("forecast episode telemetry grace MUST be non-negative")
        if self.direction not in {"rising", "falling"}:
            raise ValueError("forecast episode direction MUST be rising or falling")
        numeric = (self.threshold, self.predicted_value, self.interval_lower, self.interval_upper)
        if any(value is not None and not isfinite(value) for value in numeric):
            raise ValueError("forecast episode numeric evidence MUST be finite")
        if not self.evidence_refs or any(not value for value in self.evidence_refs):
            raise ValueError("forecast episode MUST carry evidence references")
        if self.revision < 1:
            raise ValueError("forecast episode revision MUST be positive")
        prediction = (self.predicted_value, self.interval_lower, self.interval_upper)
        if self.evaluation_kind is ForecastEvaluationKind.PREDICTED_BREACH:
            if any(value is None for value in prediction):
                raise ValueError("predicted breach MUST carry value and interval")
            if self.abstain_reason is not None:
                raise ValueError("predicted breach MUST NOT carry an abstain reason")
        elif any(value is not None for value in prediction):
            raise ValueError("non-breach evaluation MUST NOT carry prediction evidence")
        if self.evaluation_kind is ForecastEvaluationKind.ABSTAINED:
            if not self.abstain_reason:
                raise ValueError("abstained evaluation MUST carry a reason")
        elif self.abstain_reason is not None:
            raise ValueError("non-abstained evaluation MUST NOT carry an abstain reason")
        if (
            self.interval_lower is not None
            and self.interval_upper is not None
            and self.interval_lower > self.interval_upper
        ):
            raise ValueError("forecast episode interval MUST be ordered")

    @property
    def closure_due_at(self) -> datetime:
        return self.horizon_ended_at + timedelta(seconds=self.telemetry_grace_seconds)

    @property
    def target_digest(self) -> str:
        return hashlib.sha256(self.target_ref.encode()).hexdigest()


def forecast_episode_id(
    *,
    access_scope_digest: str,
    detector_id: str,
    detector_version: str,
    target_ref: str,
    metric: str,
    feature_cutoff: datetime,
    horizon_ended_at: datetime,
) -> UUID:
    material = ":".join(
        (
            access_scope_digest,
            detector_id,
            detector_version,
            target_ref,
            metric,
            feature_cutoff.isoformat(),
            horizon_ended_at.isoformat(),
        )
    )
    return uuid5(NAMESPACE_URL, f"fdai-forecast-episode:{material}")


__all__ = [
    "ForecastClosureReason",
    "ForecastEpisode",
    "ForecastEpisodeClosure",
    "ForecastEpisodeState",
    "ForecastEpisodeStore",
    "ForecastEvaluationKind",
    "ForecastPublicationOutboxItem",
    "forecast_publication_id",
    "forecast_episode_id",
]


def forecast_publication_id(*, episode_id: UUID, topic: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fdai-forecast-publication:{episode_id}:{topic}")
