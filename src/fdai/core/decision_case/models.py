"""Immutable decision-case values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class ObjectiveEffect:
    """Expected utility for one objective, normalized to [-1, 1]."""

    objective_id: str
    utility: float
    confidence: float
    metric: str
    expected_min: float
    expected_max: float
    observation_window_seconds: int

    def __post_init__(self) -> None:
        if not self.objective_id or not self.metric:
            raise ValueError("objective effect identities MUST be non-empty")
        numeric = (self.utility, self.confidence, self.expected_min, self.expected_max)
        if not all(isfinite(value) for value in numeric):
            raise ValueError("objective effect numeric values MUST be finite")
        if not -1.0 <= self.utility <= 1.0 or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("objective effect utility/confidence MUST be normalized")
        if self.expected_min > self.expected_max or self.observation_window_seconds < 1:
            raise ValueError("objective effect range/window is invalid")


@dataclass(frozen=True, slots=True)
class ActionOption:
    """One bounded action, hold, or no-op option considered in a case."""

    option_id: str
    action_type: str | None
    effects: tuple[ObjectiveEffect, ...]
    evidence_refs: tuple[str, ...]
    violated_constraint_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.option_id or not self.effects or not self.evidence_refs:
            raise ValueError("action option MUST have id, effects, and evidence")
        objective_ids = [effect.objective_id for effect in self.effects]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("action option MUST contain one effect per objective")


@dataclass(frozen=True, slots=True)
class DecisionCase:
    """Immutable semantic input shared by judge, arbiter, approver, and audit."""

    case_id: str
    correlation_id: str
    context_snapshot_id: str
    created_at: datetime
    no_action_effects: tuple[ObjectiveEffect, ...]
    options: tuple[ActionOption, ...]
    protected_objective_ids: tuple[str, ...]
    active_constraint_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all((self.case_id, self.correlation_id, self.context_snapshot_id)):
            raise ValueError("decision case identities MUST be non-empty")
        if self.created_at.tzinfo is None:
            raise ValueError("decision case timestamp MUST be timezone-aware")
        if not self.no_action_effects or not self.options or not self.evidence_refs:
            raise ValueError("decision case MUST include baseline, options, and evidence")


@dataclass(frozen=True, slots=True)
class DecisionSelection:
    selected_option_id: str | None
    objective_scores: tuple[tuple[str, float], ...]
    margin: float
    requires_human_approval: bool
    reason: str


@dataclass(frozen=True, slots=True)
class DecisionClosure:
    case_id: str
    selected_option_id: str
    outcome_id: str
    effect_verified: bool
    guard_regression: bool
    reusable: bool
    reason: str
