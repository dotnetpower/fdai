"""Versioned effect calibration and deterministic Dynamic branch simulation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fdai.shared.contracts.models import CausalEvidenceGrade, ResponseOutcome

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class EffectModelStatus(StrEnum):
    ACTIVE = "active"
    CHALLENGER = "challenger"


_EVIDENCE_RANK = {
    CausalEvidenceGrade.ASSOCIATION: 0,
    CausalEvidenceGrade.PREDICTIVE_PRECEDENCE: 1,
    CausalEvidenceGrade.QUASI_EXPERIMENTAL: 2,
    CausalEvidenceGrade.INTERVENTIONAL: 3,
}


@dataclass(frozen=True, slots=True)
class EffectModel:
    """One immutable calibration model for an action and target metric."""

    model_id: str
    version: str
    revision: int
    action_type_id: str
    metric: str
    status: EffectModelStatus
    evidence_grade: CausalEvidenceGrade
    learned_at: datetime
    learned_through: datetime
    sample_count: int = 0
    bias_correction: float = 0.0
    mean_absolute_error: float = 0.0
    interval_radius: float = 0.0

    def __post_init__(self) -> None:
        if not all((self.model_id, self.action_type_id, self.metric)):
            raise ValueError("effect model identity MUST be non-empty")
        if _SEMVER.fullmatch(self.version) is None:
            raise ValueError("effect model version MUST use MAJOR.MINOR.PATCH")
        if self.revision < 1 or self.sample_count < 0:
            raise ValueError("effect model revision and sample count MUST be non-negative")
        if self.learned_at.tzinfo is None or self.learned_through.tzinfo is None:
            raise ValueError("effect model timestamps MUST be timezone-aware")
        if self.learned_through < self.learned_at:
            raise ValueError("effect model learned_through MUST NOT precede learned_at")
        numeric = (self.bias_correction, self.mean_absolute_error, self.interval_radius)
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("effect model numeric values MUST be finite")
        if self.mean_absolute_error < 0.0 or self.interval_radius < 0.0:
            raise ValueError("effect model errors and interval radius MUST be non-negative")

    def predict(
        self,
        raw_prediction: float,
        raw_interval_radius: float,
    ) -> tuple[float, float, float]:
        if not math.isfinite(raw_prediction) or not math.isfinite(raw_interval_radius):
            raise ValueError("simulation prediction inputs MUST be finite")
        if raw_interval_radius < 0.0:
            raise ValueError("simulation interval radius MUST be non-negative")
        predicted = raw_prediction + self.bias_correction
        radius = max(raw_interval_radius, self.interval_radius, self.mean_absolute_error)
        return predicted, predicted - radius, predicted + radius


@dataclass(frozen=True, slots=True)
class ChallengerUpdate:
    model: EffectModel
    accepted: bool
    reason: str


def update_challenger(model: EffectModel, outcome: ResponseOutcome) -> ChallengerUpdate:
    """Update only a challenger from one post-cutoff scorable outcome."""

    if model.status is not EffectModelStatus.CHALLENGER:
        return ChallengerUpdate(model, False, "active_model_is_immutable")
    if not outcome.scorable:
        return ChallengerUpdate(model, False, "outcome_unscorable")
    if outcome.action_type_id != model.action_type_id or outcome.metric != model.metric:
        return ChallengerUpdate(model, False, "outcome_scope_mismatch")
    if outcome.recorded_at <= model.learned_through:
        return ChallengerUpdate(model, False, "outcome_not_after_learning_cutoff")
    if (
        outcome.expected_min is None
        or outcome.expected_max is None
        or outcome.observed_value is None
    ):
        return ChallengerUpdate(model, False, "outcome_effect_evidence_incomplete")

    raw_prediction = (outcome.expected_min + outcome.expected_max) / 2.0
    residual = outcome.observed_value - raw_prediction
    prediction_error = abs(residual - model.bias_correction)
    sample_count = model.sample_count + 1
    bias = model.bias_correction + (residual - model.bias_correction) / sample_count
    mae = (model.mean_absolute_error * model.sample_count + prediction_error) / sample_count
    updated = replace(
        model,
        revision=model.revision + 1,
        learned_through=outcome.recorded_at,
        sample_count=sample_count,
        bias_correction=bias,
        mean_absolute_error=mae,
        interval_radius=max(model.interval_radius, prediction_error),
    )
    return ChallengerUpdate(updated, True, "outcome_accepted")


@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    snapshot_id: str
    target_digest: str
    metric: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.metric:
            raise ValueError("simulation snapshot identity MUST be non-empty")
        if len(self.target_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.target_digest
        ):
            raise ValueError("simulation snapshot target_digest MUST be SHA-256")
        if self.observed_at.tzinfo is None:
            raise ValueError("simulation snapshot observed_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class SimulationBranch:
    branch_id: str
    action_type_id: str
    raw_prediction: float
    raw_interval_radius: float

    def __post_init__(self) -> None:
        if not self.branch_id or not self.action_type_id:
            raise ValueError("simulation branch identity MUST be non-empty")
        if not math.isfinite(self.raw_prediction) or not math.isfinite(self.raw_interval_radius):
            raise ValueError("simulation branch values MUST be finite")
        if self.raw_interval_radius < 0.0:
            raise ValueError("simulation branch interval radius MUST be non-negative")


@dataclass(frozen=True, slots=True)
class BranchPrediction:
    branch_id: str
    action_type_id: str
    active_model_ref: str | None
    active_value: float | None
    active_min: float | None
    active_max: float | None
    challenger_model_ref: str | None
    challenger_value: float | None
    divergence: float | None
    evidence_grade: CausalEvidenceGrade | None
    requires_review: bool
    reason: str


@dataclass(frozen=True, slots=True)
class DynamicSimulationResult:
    simulation_id: str
    snapshot_id: str
    metric: str
    objective: Literal["minimize", "maximize"]
    predictions: tuple[BranchPrediction, ...]
    ordered_branch_ids: tuple[str, ...]
    requires_review: bool


def simulate_effect_branches(
    *,
    snapshot: SimulationSnapshot,
    branches: tuple[SimulationBranch, ...],
    active_models: Mapping[str, EffectModel],
    challenger_models: Mapping[str, EffectModel] | None = None,
    objective: Literal["minimize", "maximize"] = "minimize",
    divergence_threshold: float = 0.0,
) -> DynamicSimulationResult:
    """Evaluate no-op and action branches using active authority only."""

    if not branches or len({branch.branch_id for branch in branches}) != len(branches):
        raise ValueError("simulation branches MUST be non-empty with unique ids")
    if divergence_threshold < 0.0 or not math.isfinite(divergence_threshold):
        raise ValueError("divergence_threshold MUST be finite and non-negative")
    challengers = challenger_models or {}
    predictions = tuple(
        _predict_branch(
            branch=branch,
            metric=snapshot.metric,
            active=active_models.get(branch.action_type_id),
            challenger=challengers.get(branch.action_type_id),
            divergence_threshold=divergence_threshold,
        )
        for branch in sorted(branches, key=lambda item: item.branch_id)
    )
    ranked = [item for item in predictions if item.active_value is not None]
    ranked.sort(key=lambda item: _branch_sort_key(item, objective=objective))
    material = {
        "snapshot_id": snapshot.snapshot_id,
        "target_digest": snapshot.target_digest,
        "metric": snapshot.metric,
        "observed_at": snapshot.observed_at.isoformat(),
        "objective": objective,
        "branches": [
            {
                "branch_id": branch.branch_id,
                "action_type_id": branch.action_type_id,
                "raw_prediction": branch.raw_prediction,
                "raw_interval_radius": branch.raw_interval_radius,
                "active_model_ref": prediction.active_model_ref,
                "challenger_model_ref": prediction.challenger_model_ref,
            }
            for branch, prediction in zip(
                sorted(branches, key=lambda item: item.branch_id),
                predictions,
                strict=True,
            )
        ],
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DynamicSimulationResult(
        simulation_id=str(uuid5(NAMESPACE_URL, f"fdai-dynamic-simulation:{digest}")),
        snapshot_id=snapshot.snapshot_id,
        metric=snapshot.metric,
        objective=objective,
        predictions=predictions,
        ordered_branch_ids=tuple(item.branch_id for item in ranked),
        requires_review=any(item.requires_review for item in predictions),
    )


def _predict_branch(
    *,
    branch: SimulationBranch,
    metric: str,
    active: EffectModel | None,
    challenger: EffectModel | None,
    divergence_threshold: float,
) -> BranchPrediction:
    if active is None:
        return BranchPrediction(
            branch_id=branch.branch_id,
            action_type_id=branch.action_type_id,
            active_model_ref=None,
            active_value=None,
            active_min=None,
            active_max=None,
            challenger_model_ref=None,
            challenger_value=None,
            divergence=None,
            evidence_grade=None,
            requires_review=True,
            reason="active_model_unavailable",
        )
    _validate_model_scope(active, branch=branch, metric=metric, status=EffectModelStatus.ACTIVE)
    active_value, active_min, active_max = active.predict(
        branch.raw_prediction, branch.raw_interval_radius
    )
    challenger_value = None
    challenger_ref = None
    divergence = None
    if challenger is not None:
        _validate_model_scope(
            challenger,
            branch=branch,
            metric=metric,
            status=EffectModelStatus.CHALLENGER,
        )
        challenger_value = challenger.predict(branch.raw_prediction, branch.raw_interval_radius)[0]
        challenger_ref = _model_ref(challenger)
        divergence = abs(active_value - challenger_value)
    low_evidence = (
        _EVIDENCE_RANK[active.evidence_grade]
        < _EVIDENCE_RANK[CausalEvidenceGrade.QUASI_EXPERIMENTAL]
    )
    divergent = divergence is not None and divergence > divergence_threshold
    return BranchPrediction(
        branch_id=branch.branch_id,
        action_type_id=branch.action_type_id,
        active_model_ref=_model_ref(active),
        active_value=active_value,
        active_min=active_min,
        active_max=active_max,
        challenger_model_ref=challenger_ref,
        challenger_value=challenger_value,
        divergence=divergence,
        evidence_grade=active.evidence_grade,
        requires_review=low_evidence or divergent,
        reason=(
            "active_challenger_divergence"
            if divergent
            else "causal_evidence_below_quasi_experimental"
            if low_evidence
            else "active_model_applied"
        ),
    )


def _validate_model_scope(
    model: EffectModel,
    *,
    branch: SimulationBranch,
    metric: str,
    status: EffectModelStatus,
) -> None:
    if model.status is not status:
        raise ValueError(f"simulation {status.value} model has the wrong status")
    if model.action_type_id != branch.action_type_id or model.metric != metric:
        raise ValueError("simulation effect model scope does not match its branch")


def _branch_sort_key(
    prediction: BranchPrediction,
    *,
    objective: Literal["minimize", "maximize"],
) -> tuple[float, str]:
    value = prediction.active_value
    if value is None:
        return math.inf, prediction.branch_id
    return (value if objective == "minimize" else -value), prediction.branch_id


def _model_ref(model: EffectModel) -> str:
    return f"{model.model_id}@{model.version}:r{model.revision}"


__all__ = [
    "BranchPrediction",
    "CausalEvidenceGrade",
    "ChallengerUpdate",
    "DynamicSimulationResult",
    "EffectModel",
    "EffectModelStatus",
    "SimulationBranch",
    "SimulationSnapshot",
    "simulate_effect_branches",
    "update_challenger",
]
