"""Challenger-only learning from independently closed graph effects."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from datetime import datetime

from fdai.core.assurance_twin.effect_model import EffectModelStatus
from fdai.core.assurance_twin.graph_effect import GraphEffectModel


@dataclass(frozen=True, slots=True)
class GraphModelLearningObservation:
    model_ref: str
    prediction_digest: str
    observation_digest: str
    object_ref: str
    metric: str
    predicted_value: float
    observed_value: float
    observed_at: datetime
    recorded_at: datetime
    evidence_refs: tuple[str, ...]
    independent_observer: bool
    complete: bool
    intervention_censored: bool = False

    def __post_init__(self) -> None:
        if not self.model_ref or len(self.model_ref) > 512:
            raise ValueError("graph learning model_ref MUST be bounded and non-empty")
        if not self.object_ref.strip() or not self.metric.strip():
            raise ValueError("graph learning slice identity MUST be non-empty")
        for digest in (self.prediction_digest, self.observation_digest):
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError("graph learning trajectory digests MUST be SHA-256")
        if any(not math.isfinite(value) for value in (self.predicted_value, self.observed_value)):
            raise ValueError("graph learning values MUST be finite")
        if self.observed_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("graph learning timestamps MUST be timezone-aware")
        if self.observed_at > self.recorded_at:
            raise ValueError("graph learning observation MUST NOT follow recording")
        if not self.evidence_refs or len(self.evidence_refs) > 256:
            raise ValueError("graph learning evidence_refs MUST be non-empty and bounded")

    @property
    def digest(self) -> str:
        material = "\0".join(
            (
                self.model_ref,
                self.prediction_digest,
                self.observation_digest,
                self.object_ref,
                self.metric,
                self.observed_at.isoformat(),
            )
        )
        return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class GraphChallengerUpdate:
    model: GraphEffectModel
    accepted: bool
    reason: str


def update_graph_challenger(
    model: GraphEffectModel,
    observation: GraphModelLearningObservation,
) -> GraphChallengerUpdate:
    """Update one challenger from complete post-cutoff independent evidence."""

    if model.status is not EffectModelStatus.CHALLENGER:
        return GraphChallengerUpdate(model, False, "active_model_is_immutable")
    if observation.model_ref.rsplit(":r", maxsplit=1)[0] != f"{model.model_id}@{model.version}":
        return GraphChallengerUpdate(model, False, "observation_model_mismatch")
    if observation.digest in model.applied_observation_digests:
        return GraphChallengerUpdate(model, False, "observation_already_applied")
    if not observation.complete:
        return GraphChallengerUpdate(model, False, "observation_incomplete")
    if not observation.independent_observer:
        return GraphChallengerUpdate(model, False, "observer_not_independent")
    if observation.intervention_censored:
        return GraphChallengerUpdate(model, False, "observation_intervention_censored")
    if observation.recorded_at <= model.learned_through:
        return GraphChallengerUpdate(model, False, "observation_not_after_learning_cutoff")
    if len(model.applied_observation_digests) >= 64:
        return GraphChallengerUpdate(model, False, "observation_digest_capacity_reached")
    residual = observation.observed_value - observation.predicted_value
    prediction_error = abs(residual)
    sample_count = model.sample_count + 1
    offset = model.offset + residual / sample_count
    mean_absolute_error = (
        model.mean_absolute_error * model.sample_count + prediction_error
    ) / sample_count
    if any(not math.isfinite(value) for value in (residual, offset, mean_absolute_error)):
        return GraphChallengerUpdate(model, False, "observation_arithmetic_non_finite")
    return GraphChallengerUpdate(
        replace(
            model,
            revision=model.revision + 1,
            learned_through=observation.recorded_at,
            sample_count=sample_count,
            offset=offset,
            mean_absolute_error=mean_absolute_error,
            interval_radius=max(model.interval_radius, prediction_error),
            applied_observation_digests=(*model.applied_observation_digests, observation.digest),
        ),
        True,
        "observation_accepted",
    )


__all__ = [
    "GraphChallengerUpdate",
    "GraphModelLearningObservation",
    "update_graph_challenger",
]
