"""Immutable values for bounded operational planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from fdai.core.decision_case import DecisionCase, DecisionSelection, ObjectiveEffect
from fdai.core.operational_context import OperationalContextSnapshot

MAX_PLAN_CANDIDATES = 32


class ConstraintStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SimulationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNSCORABLE = "unscorable"


class CandidateDisposition(StrEnum):
    SELECTED = "selected"
    ELIGIBLE = "eligible"
    DOMINATED = "dominated"
    INELIGIBLE = "ineligible"


class PlanningPhase(StrEnum):
    CONTEXT_FROZEN = "context_frozen"
    PROPOSALS_COLLECTED = "proposals_collected"
    SIMULATIONS_CLOSED = "simulations_closed"
    CRITIQUES_CLOSED = "critiques_closed"
    ARBITRATION_CLOSED = "arbitration_closed"
    SELECTED = "selected"
    HELD = "held"
    ABSTAINED = "abstained"


@dataclass(frozen=True, slots=True)
class SpecialistContribution:
    agent: str
    domain: str
    recommendation: str
    observed_at: datetime
    impact: float
    evidence_refs: tuple[str, ...]
    logic_receipt_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.agent, self.domain, self.recommendation)):
            raise ValueError("specialist contribution identities MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("specialist contribution timestamp MUST be timezone-aware")
        if not isfinite(self.impact) or not 0.0 <= self.impact <= 1.0:
            raise ValueError("specialist contribution impact MUST be in [0, 1]")
        if not self.evidence_refs:
            raise ValueError("specialist contribution requires evidence")


@dataclass(frozen=True, slots=True)
class ConstraintEvaluation:
    constraint_id: str
    status: ConstraintStatus
    precedence: int
    reason_code: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.constraint_id or not self.reason_code:
            raise ValueError("constraint evaluation identity MUST be non-empty")
        if not 1 <= self.precedence <= 6:
            raise ValueError("constraint precedence MUST be in [1, 6]")
        if not self.evidence_refs:
            raise ValueError("constraint evaluation requires evidence")


@dataclass(frozen=True, slots=True)
class SimulationReceipt:
    receipt_id: str
    candidate_id: str
    snapshot_id: str
    logic_invocation_id: str
    status: SimulationStatus
    started_at: datetime
    completed_at: datetime
    evidence_refs: tuple[str, ...]
    predicted_effects: tuple[ObjectiveEffect, ...] = ()
    requires_review: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if not all(
            (self.receipt_id, self.candidate_id, self.snapshot_id, self.logic_invocation_id)
        ):
            raise ValueError("simulation receipt identities MUST be non-empty")
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("simulation receipt timestamps MUST be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("simulation receipt completion MUST follow start")
        if not self.evidence_refs:
            raise ValueError("simulation receipt requires evidence")
        objective_ids = [effect.objective_id for effect in self.predicted_effects]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("simulation receipt MUST contain one effect per objective")


@dataclass(frozen=True, slots=True)
class PlanCandidate:
    candidate_id: str
    action_type: str | None
    effects: tuple[ObjectiveEffect, ...]
    contributions: tuple[SpecialistContribution, ...]
    constraints: tuple[ConstraintEvaluation, ...]
    simulations: tuple[SimulationReceipt, ...]
    evidence_refs: tuple[str, ...]
    assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.effects:
            raise ValueError("plan candidate requires identity and effects")
        if not self.contributions or not self.constraints or not self.simulations:
            raise ValueError("plan candidate requires contributions, constraints, and simulations")
        if not self.evidence_refs:
            raise ValueError("plan candidate requires evidence")
        if any(receipt.candidate_id != self.candidate_id for receipt in self.simulations):
            raise ValueError("simulation receipt candidate does not match plan candidate")
        objective_ids = [effect.objective_id for effect in self.effects]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("plan candidate MUST contain one effect per objective")


@dataclass(frozen=True, slots=True)
class PlanningRequest:
    process_id: str
    correlation_id: str
    logic_release_digest: str
    context: OperationalContextSnapshot
    no_action_effects: tuple[ObjectiveEffect, ...]
    protected_objective_ids: tuple[str, ...]
    candidates: tuple[PlanCandidate, ...]
    objective_weights: tuple[tuple[str, float], ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.process_id or not self.correlation_id:
            raise ValueError("planning request identities MUST be non-empty")
        if (
            not self.logic_release_digest.startswith("sha256:")
            or len(self.logic_release_digest) != 71
        ):
            raise ValueError("planning request logic release digest MUST be SHA-256")
        if self.created_at.tzinfo is None:
            raise ValueError("planning request timestamp MUST be timezone-aware")
        if not self.no_action_effects or not self.candidates or not self.objective_weights:
            raise ValueError("planning request requires baseline, candidates, and weights")
        if len(self.candidates) > MAX_PLAN_CANDIDATES:
            raise ValueError("planning candidate count exceeds the hard limit")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("planning candidate identities MUST be unique")
        weights = dict(self.objective_weights)
        if len(weights) != len(self.objective_weights):
            raise ValueError("planning objective weights MUST be unique")
        if any(
            not objective or not isfinite(weight) or weight < 0.0
            for objective, weight in weights.items()
        ):
            raise ValueError("planning objective weights MUST be named, finite, and non-negative")


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    candidate_id: str
    disposition: CandidateDisposition
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperationalPlan:
    plan_id: str
    process_id: str
    logic_release_digest: str
    decision_case: DecisionCase
    selection: DecisionSelection
    assessments: tuple[CandidateAssessment, ...]
    complete: bool
    reason: str


__all__ = [
    "CandidateAssessment",
    "CandidateDisposition",
    "ConstraintEvaluation",
    "ConstraintStatus",
    "MAX_PLAN_CANDIDATES",
    "OperationalPlan",
    "PlanCandidate",
    "PlanningPhase",
    "PlanningRequest",
    "SimulationReceipt",
    "SimulationStatus",
    "SpecialistContribution",
]
