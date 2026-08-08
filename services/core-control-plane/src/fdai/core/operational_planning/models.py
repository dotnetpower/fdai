"""Immutable values for bounded operational planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from fdai.core.decision_case import DecisionCase, DecisionSelection, ObjectiveEffect
from fdai.core.operational_context import OperationalContextSnapshot

MAX_PLAN_CANDIDATES = 32
MAX_PLAN_CONSTRAINTS = 64
MAX_PLAN_EFFECTS = 32
MAX_PLAN_EVIDENCE_REFS = 256
MAX_PLAN_ITEM_EVIDENCE_REFS = 64
MAX_PLAN_SPECIALIST_DOMAINS = 15
MAX_PLAN_SIMULATIONS = 8
MAX_PLAN_TEXT_LENGTH = 512


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
        _validate_strings(
            self.evidence_refs,
            field="specialist contribution evidence",
            limit=MAX_PLAN_ITEM_EVIDENCE_REFS,
        )
        _validate_strings(
            self.logic_receipt_refs,
            field="specialist contribution logic receipts",
            limit=MAX_PLAN_ITEM_EVIDENCE_REFS,
        )
        _validate_strings(
            self.assumptions,
            field="specialist contribution assumptions",
            limit=MAX_PLAN_ITEM_EVIDENCE_REFS,
        )


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
        _validate_strings(
            self.evidence_refs,
            field="constraint evaluation evidence",
            limit=MAX_PLAN_ITEM_EVIDENCE_REFS,
        )


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
        _validate_strings(
            self.evidence_refs,
            field="simulation receipt evidence",
            limit=MAX_PLAN_ITEM_EVIDENCE_REFS,
        )
        if len(self.predicted_effects) > MAX_PLAN_EFFECTS:
            raise ValueError("simulation receipt effect count exceeds the hard limit")
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
        if len(self.effects) > MAX_PLAN_EFFECTS:
            raise ValueError("plan candidate effect count exceeds the hard limit")
        if len(self.contributions) > MAX_PLAN_SPECIALIST_DOMAINS:
            raise ValueError("plan candidate contribution count exceeds the hard limit")
        if len(self.constraints) > MAX_PLAN_CONSTRAINTS:
            raise ValueError("plan candidate constraint count exceeds the hard limit")
        if len(self.simulations) > MAX_PLAN_SIMULATIONS:
            raise ValueError("plan candidate simulation count exceeds the hard limit")
        _validate_strings(
            self.evidence_refs,
            field="plan candidate evidence",
            limit=MAX_PLAN_ITEM_EVIDENCE_REFS,
        )
        _validate_strings(
            self.assumptions,
            field="plan candidate assumptions",
            limit=MAX_PLAN_ITEM_EVIDENCE_REFS,
        )
        objective_ids = [effect.objective_id for effect in self.effects]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("plan candidate MUST contain one effect per objective")

    @property
    def evidence_manifest(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self.evidence_refs,
                    *(
                        ref
                        for contribution in self.contributions
                        for ref in (
                            *contribution.evidence_refs,
                            *contribution.logic_receipt_refs,
                        )
                    ),
                    *(ref for evaluation in self.constraints for ref in evaluation.evidence_refs),
                    *(
                        ref
                        for receipt in self.simulations
                        for ref in (receipt.receipt_id, *receipt.evidence_refs)
                    ),
                )
            )
        )


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
        if len(self.no_action_effects) > MAX_PLAN_EFFECTS:
            raise ValueError("planning baseline effect count exceeds the hard limit")
        if len(self.protected_objective_ids) > MAX_PLAN_EFFECTS:
            raise ValueError("planning protected objective count exceeds the hard limit")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("planning candidate identities MUST be unique")
        weights = dict(self.objective_weights)
        if len(weights) != len(self.objective_weights):
            raise ValueError("planning objective weights MUST be unique")
        if len(weights) > MAX_PLAN_EFFECTS:
            raise ValueError("planning objective weight count exceeds the hard limit")
        if any(
            not objective or not isfinite(weight) or weight < 0.0
            for objective, weight in weights.items()
        ):
            raise ValueError("planning objective weights MUST be named, finite, and non-negative")
        evidence_refs = {self.logic_release_digest}
        evidence_refs.update(
            ref for candidate in self.candidates for ref in candidate.evidence_manifest
        )
        if len(evidence_refs) > MAX_PLAN_EVIDENCE_REFS:
            raise ValueError("planning evidence count exceeds the hard limit")


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    candidate_id: str
    disposition: CandidateDisposition
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperationalPlan:
    plan_id: str
    process_id: str
    target_resource_id: str
    logic_release_digest: str
    decision_case: DecisionCase
    selection: DecisionSelection
    assessments: tuple[CandidateAssessment, ...]
    complete: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.plan_id or not self.process_id or not self.target_resource_id:
            raise ValueError("operational plan identities MUST be non-empty")


def _validate_strings(values: tuple[str, ...], *, field: str, limit: int) -> None:
    if len(values) > limit:
        raise ValueError(f"{field} count exceeds the hard limit")
    if any(not value or len(value) > MAX_PLAN_TEXT_LENGTH for value in values):
        raise ValueError(f"{field} values MUST be non-empty and bounded")


__all__ = [
    "CandidateAssessment",
    "CandidateDisposition",
    "ConstraintEvaluation",
    "ConstraintStatus",
    "MAX_PLAN_CANDIDATES",
    "MAX_PLAN_CONSTRAINTS",
    "MAX_PLAN_EFFECTS",
    "MAX_PLAN_EVIDENCE_REFS",
    "MAX_PLAN_ITEM_EVIDENCE_REFS",
    "MAX_PLAN_SIMULATIONS",
    "MAX_PLAN_SPECIALIST_DOMAINS",
    "MAX_PLAN_TEXT_LENGTH",
    "OperationalPlan",
    "PlanCandidate",
    "PlanningPhase",
    "PlanningRequest",
    "SimulationReceipt",
    "SimulationStatus",
    "SpecialistContribution",
]
