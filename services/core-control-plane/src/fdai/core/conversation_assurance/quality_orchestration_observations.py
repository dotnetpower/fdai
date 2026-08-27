"""Qualification contributions from bounded planning and handoff results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.core.conversation.answer_planning import AnswerPlanningResult, PlanningStatus
from fdai.core.conversation_assurance.quality_observation_models import (
    QualificationDimensionContribution,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)
from fdai.core.human_assignment.model import AssignmentCase, AssignmentState


@dataclass(frozen=True, slots=True)
class PlanningOrchestrationScenarioResult:
    case_id: str
    expected_primary_agent: str | None
    expected_status: PlanningStatus
    expected_contributor_agents: tuple[str, ...]
    expected_conflict_ref_digests: tuple[str, ...]
    actual: AnswerPlanningResult
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class HandoffScenarioResult:
    case_id: str
    expected_state: AssignmentState
    expected_required_effects: bool
    actual: AssignmentCase
    evidence_digest: str


def observe_planning_orchestration(
    result: PlanningOrchestrationScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure items 31-34 from one bounded shadow planning result."""

    _require_digest(result.evidence_digest)
    expected_agents = tuple(sorted(set(result.expected_contributor_agents)))
    actual_agents = tuple(
        sorted(contribution.agent for contribution in result.actual.contributions)
    )
    actual_conflicts = tuple(
        sorted(
            hashlib.sha256(reference.encode()).hexdigest()
            for reference in result.actual.conflicting_evidence_refs
        )
    )
    attributed = actual_agents == expected_agents and all(
        contribution.evidence_refs for contribution in result.actual.contributions
    )
    budget_compliant = (
        len(result.actual.consulted_agents) <= result.actual.budget.max_contributors
        and result.actual.elapsed_ms <= result.actual.budget.max_wall_ms
        and result.actual.estimated_added_tokens <= result.actual.budget.max_added_tokens
    )
    observed_digest = _digest(result.actual.to_dict())
    return (
        _contribution(
            result.case_id,
            item_id=31,
            correct=result.actual.primary_agent == result.expected_primary_agent,
            reason="primary_owner_match",
            evidence_digest=result.evidence_digest,
            observed_digest=observed_digest,
        ),
        _contribution(
            result.case_id,
            item_id=32,
            correct=budget_compliant and result.actual.status is result.expected_status,
            reason="bounded_fanout_and_status_match",
            evidence_digest=result.evidence_digest,
            observed_digest=observed_digest,
        ),
        _contribution(
            result.case_id,
            item_id=33,
            correct=attributed,
            reason="contributor_attribution_match",
            evidence_digest=result.evidence_digest,
            observed_digest=observed_digest,
        ),
        _contribution(
            result.case_id,
            item_id=34,
            correct=actual_conflicts == tuple(sorted(set(result.expected_conflict_ref_digests))),
            reason="conflict_reference_set_match",
            evidence_digest=result.evidence_digest,
            observed_digest=observed_digest,
        ),
    )


def observe_handoff(
    result: HandoffScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 35 from the revisioned assignment handoff state."""

    _require_digest(result.evidence_digest)
    correct = (
        result.actual.state is result.expected_state
        and result.actual.has_required_effects is result.expected_required_effects
    )
    return _contribution(
        result.case_id,
        item_id=35,
        correct=correct,
        reason="handoff_state_and_effects_match",
        evidence_digest=result.evidence_digest,
        observed_digest=_digest(result.actual.to_dict()),
    )


def _contribution(
    case_id: str,
    *,
    item_id: int,
    correct: bool,
    reason: str,
    evidence_digest: str,
    observed_digest: str,
) -> QualificationDimensionContribution:
    item = CHATOPS_QUALITY_CONTRACT_V1.items[item_id - 1]
    return QualificationDimensionContribution(
        case_id=case_id,
        item_id=item_id,
        workstream=item.workstream,
        metric=item.metric,
        dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
        value=1.0 if correct else 0.0,
        reason_code=reason,
        evidence_ref_digests=(evidence_digest, observed_digest),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _require_digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("scenario evidence_digest MUST be a lowercase SHA-256 digest")


__all__ = [
    "HandoffScenarioResult",
    "PlanningOrchestrationScenarioResult",
    "observe_handoff",
    "observe_planning_orchestration",
]
