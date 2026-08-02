"""Proposal-only bridge from an operational plan to a MutationPlan."""

from __future__ import annotations

from datetime import datetime

from fdai.core.decision_case import DecisionClosure, close_decision
from fdai.core.ontology_platform import (
    MutationEffect,
    MutationEffectKind,
    MutationPlan,
    build_mutation_plan,
)
from fdai.shared.contracts.models import OntologyTypeRef, ResponseOutcome
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .models import CandidateDisposition, OperationalPlan


def compile_selected_mutation_plan(
    *,
    plan: OperationalPlan,
    target: OntologyObjectRecord,
    action_type_ref: OntologyTypeRef,
    command_ref: str,
    rollback_command_ref: str,
    created_at: datetime,
    max_affected_objects: int,
) -> MutationPlan:
    selected_id = plan.selection.selected_option_id
    if not plan.complete or selected_id is None:
        raise ValueError("operational plan has no complete selection")
    selected_option = next(
        (option for option in plan.decision_case.options if option.option_id == selected_id),
        None,
    )
    if selected_option is None or selected_option.action_type != action_type_ref.name:
        raise ValueError("selected option does not match ActionType release reference")
    assessment = next(
        (item for item in plan.assessments if item.candidate_id == selected_id),
        None,
    )
    if assessment is None or assessment.disposition is not CandidateDisposition.SELECTED:
        raise ValueError("selected option is not eligible for mutation planning")
    if not selected_option.simulation_receipt_refs or not selected_option.logic_receipt_refs:
        raise ValueError("selected option lacks logic or simulation receipts")
    effects = (
        MutationEffect(
            kind=MutationEffectKind.PROVIDER_COMMAND,
            target_id=target.id,
            command_ref=command_ref,
        ),
    )
    rollback_effects = (
        MutationEffect(
            kind=MutationEffectKind.PROVIDER_COMMAND,
            target_id=target.id,
            command_ref=rollback_command_ref,
        ),
    )
    expected_effects = tuple(
        MutationEffect(
            kind=MutationEffectKind.EXPECTED_PROPERTY,
            target_id=target.id,
            property_name=effect.metric,
            value={"min": effect.expected_min, "max": effect.expected_max},
        )
        for effect in selected_option.effects
    )
    return build_mutation_plan(
        action_type_ref=action_type_ref,
        planner_ref=plan.plan_id,
        targets=(target,),
        effects=effects,
        rollback_effects=rollback_effects,
        expected_effects=expected_effects,
        created_at=created_at,
        max_affected_objects=max_affected_objects,
    )


def close_operational_plan(
    plan: OperationalPlan,
    mutation: MutationPlan,
    outcome: ResponseOutcome,
) -> DecisionClosure:
    if not plan.complete:
        raise ValueError("incomplete operational plan cannot close as an executed decision")
    selected = next(
        (
            option
            for option in plan.decision_case.options
            if option.option_id == plan.selection.selected_option_id
        ),
        None,
    )
    if mutation.planner_ref != plan.plan_id:
        raise ValueError("mutation plan does not cite the operational plan")
    if selected is None or mutation.action_type_ref.name != selected.action_type:
        raise ValueError("mutation plan ActionType does not match selected option")
    if outcome.prediction_id != mutation.plan_id:
        raise ValueError("response outcome does not cite the mutation plan prediction")
    return close_decision(plan.decision_case, plan.selection, outcome)


__all__ = ["close_operational_plan", "compile_selected_mutation_plan"]
