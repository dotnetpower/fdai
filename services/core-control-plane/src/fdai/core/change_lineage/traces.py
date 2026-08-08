"""Immutable decision and resilience values embedded in Change lineage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class ChangeObjectiveTrace:
    """One selected objective effect preserved for deterministic replay."""

    objective_id: str
    utility: float
    confidence: float
    metric: str
    expected_min: float
    expected_max: float
    observation_window_seconds: int

    def __post_init__(self) -> None:
        if not self.objective_id.strip() or not self.metric.strip():
            raise ValueError("change objective trace identities MUST be non-empty")
        numeric = (self.utility, self.confidence, self.expected_min, self.expected_max)
        if not all(isfinite(value) for value in numeric):
            raise ValueError("change objective trace numeric values MUST be finite")
        if not -1.0 <= self.utility <= 1.0 or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("change objective trace utility/confidence MUST be normalized")
        if self.expected_min > self.expected_max or self.observation_window_seconds < 1:
            raise ValueError("change objective trace range/window is invalid")

    def to_mapping(self) -> dict[str, Any]:
        """Return the canonical objective-effect projection."""

        return {
            "objective_id": self.objective_id,
            "utility": self.utility,
            "confidence": self.confidence,
            "metric": self.metric,
            "expected_min": self.expected_min,
            "expected_max": self.expected_max,
            "observation_window_seconds": self.observation_window_seconds,
        }


@dataclass(frozen=True, slots=True)
class ChangeDecisionTrace:
    """Canonical rationale for the selected action with no decision authority."""

    context_snapshot_id: str
    selected_option_id: str
    option_scores: tuple[tuple[str, float], ...]
    margin: float
    requires_human_approval: bool
    reason: str
    protected_objective_ids: tuple[str, ...]
    active_constraint_ids: tuple[str, ...]
    selected_effects: tuple[ChangeObjectiveTrace, ...]
    violated_constraint_ids: tuple[str, ...]
    proposing_agents: tuple[str, ...]
    logic_receipt_refs: tuple[str, ...]
    simulation_receipt_refs: tuple[str, ...]
    constraint_evaluation_refs: tuple[str, ...]
    assumptions: tuple[str, ...]
    process_id: str | None
    logic_release_digest: str | None

    def __post_init__(self) -> None:
        text_values = (self.context_snapshot_id, self.selected_option_id, self.reason)
        if any(not value.strip() for value in text_values):
            raise ValueError("change decision trace identities and reason MUST be non-empty")
        if not isfinite(self.margin):
            raise ValueError("change decision trace margin MUST be finite")
        score_ids = [option_id for option_id, score in self.option_scores if isfinite(score)]
        if (
            len(score_ids) != len(self.option_scores)
            or len(score_ids) != len(set(score_ids))
            or any(not option_id.strip() for option_id in score_ids)
            or self.option_scores != tuple(sorted(self.option_scores))
        ):
            raise ValueError("change decision option scores MUST be finite, sorted, and unique")
        if self.selected_option_id not in score_ids:
            raise ValueError("change decision option scores MUST include the selected option")
        if not self.selected_effects:
            raise ValueError("change decision trace MUST include selected effects")
        effect_ids = tuple(effect.objective_id for effect in self.selected_effects)
        if effect_ids != tuple(sorted(set(effect_ids))):
            raise ValueError("change decision effects MUST be sorted and unique")
        canonical_sets = (
            self.protected_objective_ids,
            self.active_constraint_ids,
            self.violated_constraint_ids,
            self.proposing_agents,
            self.logic_receipt_refs,
            self.simulation_receipt_refs,
            self.constraint_evaluation_refs,
            self.assumptions,
        )
        if any(values != tuple(sorted(set(values))) for values in canonical_sets):
            raise ValueError("change decision trace collections MUST be sorted and unique")
        if any(
            value is not None and not value.strip()
            for value in (self.process_id, self.logic_release_digest)
        ):
            raise ValueError("change decision optional identities MUST be non-empty when supplied")

    def to_mapping(self) -> dict[str, Any]:
        """Return the bounded rationale projection used by replay consumers."""

        return {
            "context_snapshot_id": self.context_snapshot_id,
            "selected_option_id": self.selected_option_id,
            "option_scores": [list(score) for score in self.option_scores],
            "margin": self.margin,
            "requires_human_approval": self.requires_human_approval,
            "reason": self.reason,
            "protected_objective_ids": list(self.protected_objective_ids),
            "active_constraint_ids": list(self.active_constraint_ids),
            "selected_effects": [effect.to_mapping() for effect in self.selected_effects],
            "violated_constraint_ids": list(self.violated_constraint_ids),
            "proposing_agents": list(self.proposing_agents),
            "logic_receipt_refs": list(self.logic_receipt_refs),
            "simulation_receipt_refs": list(self.simulation_receipt_refs),
            "constraint_evaluation_refs": list(self.constraint_evaluation_refs),
            "assumptions": list(self.assumptions),
            "process_id": self.process_id,
            "logic_release_digest": self.logic_release_digest,
        }


@dataclass(frozen=True, slots=True)
class ChangeResilienceTrace:
    """Bounded resilience intent and observed recovery state for replay."""

    execution_mode: str
    blast_radius_scope: str
    blast_radius_count: int | None
    rollback_kind: str
    verification_status: str
    execution_outcome: str
    predicted_at: datetime | None
    observation_deadline: datetime | None
    observed_at: datetime | None
    rollback_succeeded: bool | None

    def __post_init__(self) -> None:
        text_values = (
            self.execution_mode,
            self.blast_radius_scope,
            self.rollback_kind,
            self.verification_status,
            self.execution_outcome,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("change resilience trace values MUST be non-empty")
        if self.blast_radius_count is not None and self.blast_radius_count < 1:
            raise ValueError("change resilience blast radius count MUST be positive")
        timestamps = (self.predicted_at, self.observation_deadline, self.observed_at)
        if any(value is not None and value.tzinfo is None for value in timestamps):
            raise ValueError("change resilience timestamps MUST be timezone-aware")
        if (self.predicted_at is None) != (self.observation_deadline is None):
            raise ValueError("change resilience prediction window MUST be supplied together")
        if (
            self.predicted_at is not None
            and self.observation_deadline is not None
            and self.predicted_at > self.observation_deadline
        ):
            raise ValueError("change resilience deadline MUST NOT precede prediction")
        if self.observed_at is not None:
            if self.predicted_at is None or self.observation_deadline is None:
                raise ValueError("change resilience observation requires a prediction window")
            if not self.predicted_at <= self.observed_at <= self.observation_deadline:
                raise ValueError("change resilience observation MUST fall inside its effect window")

    def to_mapping(self) -> dict[str, Any]:
        """Return the canonical mapping included in lineage identity and projections."""

        return {
            "execution_mode": self.execution_mode,
            "blast_radius_scope": self.blast_radius_scope,
            "blast_radius_count": self.blast_radius_count,
            "rollback_kind": self.rollback_kind,
            "verification_status": self.verification_status,
            "execution_outcome": self.execution_outcome,
            "predicted_at": self.predicted_at.isoformat() if self.predicted_at else None,
            "observation_deadline": (
                self.observation_deadline.isoformat() if self.observation_deadline else None
            ),
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "rollback_succeeded": self.rollback_succeeded,
        }


__all__ = ["ChangeDecisionTrace", "ChangeObjectiveTrace", "ChangeResilienceTrace"]
