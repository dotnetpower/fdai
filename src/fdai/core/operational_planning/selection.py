"""Deterministic hard-constraint, Pareto, and objective selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from fdai.core.decision_case import (
    ActionOption,
    DecisionSelection,
    build_decision_case,
    select_action_option,
)

from .models import (
    CandidateAssessment,
    CandidateDisposition,
    ConstraintStatus,
    OperationalPlan,
    PlanCandidate,
    PlanningRequest,
    SimulationStatus,
)


def build_operational_plan(request: PlanningRequest) -> OperationalPlan:
    """Build one replay-stable plan without granting execution authority."""
    assessments: dict[str, CandidateAssessment] = {}
    eligible: list[PlanCandidate] = []
    options = tuple(_action_option(candidate) for candidate in request.candidates)
    decision_case = build_decision_case(
        correlation_id=request.correlation_id,
        context=request.context,
        created_at=request.created_at,
        no_action_effects=request.no_action_effects,
        options=options,
        protected_objective_ids=request.protected_objective_ids,
        evidence_refs=tuple(
            dict.fromkeys(
                (
                    request.logic_release_digest,
                    *(ref for candidate in request.candidates for ref in candidate.evidence_refs),
                )
            )
        ),
        process_id=request.process_id,
        logic_release_digest=request.logic_release_digest,
    )
    for candidate in request.candidates:
        reasons = _ineligibility_reasons(candidate, context_id=request.context.snapshot_id)
        if reasons:
            assessments[candidate.candidate_id] = CandidateAssessment(
                candidate.candidate_id,
                CandidateDisposition.INELIGIBLE,
                reasons,
            )
        else:
            eligible.append(candidate)
    survivors, dominated = _pareto_survivors(tuple(eligible))
    for candidate in dominated:
        assessments[candidate.candidate_id] = CandidateAssessment(
            candidate.candidate_id,
            CandidateDisposition.DOMINATED,
            ("pareto_dominated",),
        )
    if not survivors:
        selection = DecisionSelection(None, (), 0.0, True, "no_eligible_option")
        complete = False
        reason = "held_no_eligible_option"
    else:
        survivor_ids = {candidate.candidate_id for candidate in survivors}
        survivor_case = replace(
            decision_case,
            options=tuple(option for option in options if option.option_id in survivor_ids),
        )
        selection = select_action_option(
            survivor_case,
            objective_weights=dict(request.objective_weights),
        )
        complete = selection.selected_option_id is not None
        reason = "selected" if complete else "held_no_safe_option"
        for candidate in survivors:
            disposition = (
                CandidateDisposition.SELECTED
                if candidate.candidate_id == selection.selected_option_id
                else CandidateDisposition.ELIGIBLE
            )
            assessments[candidate.candidate_id] = CandidateAssessment(
                candidate.candidate_id,
                disposition,
                (),
            )
    ordered_assessments = tuple(assessments[candidate_id] for candidate_id in sorted(assessments))
    material = {
        "process_id": request.process_id,
        "target_resource_id": request.context.target_resource_id,
        "case_id": decision_case.case_id,
        "logic_release_digest": request.logic_release_digest,
        "selection": selection.selected_option_id,
        "assessments": [
            {
                "candidate_id": item.candidate_id,
                "disposition": item.disposition.value,
                "reasons": list(item.reasons),
            }
            for item in ordered_assessments
        ],
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return OperationalPlan(
        plan_id=f"operational-plan:{digest}",
        process_id=request.process_id,
        target_resource_id=request.context.target_resource_id,
        logic_release_digest=request.logic_release_digest,
        decision_case=decision_case,
        selection=selection,
        assessments=ordered_assessments,
        complete=complete,
        reason=reason,
    )


def _ineligibility_reasons(candidate: PlanCandidate, *, context_id: str) -> tuple[str, ...]:
    reasons = [
        f"constraint:{evaluation.constraint_id}:{evaluation.status.value}"
        for evaluation in sorted(candidate.constraints, key=lambda item: item.precedence)
        if evaluation.status is not ConstraintStatus.PASSED
    ]
    for receipt in candidate.simulations:
        if receipt.snapshot_id != context_id:
            reasons.append(f"simulation:{receipt.receipt_id}:stale_snapshot")
        elif receipt.status is not SimulationStatus.SUCCEEDED:
            reasons.append(f"simulation:{receipt.receipt_id}:{receipt.status.value}")
        elif receipt.requires_review:
            reasons.append(f"simulation:{receipt.receipt_id}:requires_review")
    return tuple(reasons)


def _pareto_survivors(
    candidates: tuple[PlanCandidate, ...],
) -> tuple[tuple[PlanCandidate, ...], tuple[PlanCandidate, ...]]:
    survivors: list[PlanCandidate] = []
    dominated: list[PlanCandidate] = []
    for candidate in candidates:
        if any(_dominates(other, candidate) for other in candidates if other is not candidate):
            dominated.append(candidate)
        else:
            survivors.append(candidate)
    return tuple(survivors), tuple(dominated)


def _dominates(left: PlanCandidate, right: PlanCandidate) -> bool:
    left_effects = {effect.objective_id: effect.utility for effect in left.effects}
    right_effects = {effect.objective_id: effect.utility for effect in right.effects}
    if left_effects.keys() != right_effects.keys():
        return False
    no_worse = all(left_effects[key] >= right_effects[key] for key in left_effects)
    strictly_better = any(left_effects[key] > right_effects[key] for key in left_effects)
    return no_worse and strictly_better


def _action_option(candidate: PlanCandidate) -> ActionOption:
    failed = tuple(
        evaluation.constraint_id
        for evaluation in candidate.constraints
        if evaluation.status is not ConstraintStatus.PASSED
    )
    return ActionOption(
        option_id=candidate.candidate_id,
        action_type=candidate.action_type,
        effects=candidate.effects,
        evidence_refs=candidate.evidence_refs,
        violated_constraint_ids=failed,
        proposing_agents=tuple(dict.fromkeys(item.agent for item in candidate.contributions)),
        logic_receipt_refs=tuple(
            dict.fromkeys(
                ref
                for contribution in candidate.contributions
                for ref in contribution.logic_receipt_refs
            )
        ),
        simulation_receipt_refs=tuple(receipt.receipt_id for receipt in candidate.simulations),
        constraint_evaluation_refs=tuple(
            f"constraint:{evaluation.constraint_id}:{evaluation.status.value}"
            for evaluation in candidate.constraints
        ),
        assumptions=candidate.assumptions,
    )


__all__ = ["build_operational_plan"]
