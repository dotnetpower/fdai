"""Compile correlated specialist evidence into an operational plan."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.decision_case import (
    ActionOption,
    DecisionCase,
    DecisionSelection,
    DomainDecisionCoordinator,
    ObjectiveEffect,
)
from fdai.core.operational_context import OperationalContextSnapshot

from .models import (
    ConstraintEvaluation,
    OperationalPlan,
    PlanCandidate,
    PlanningRequest,
    SimulationReceipt,
    SpecialistContribution,
)
from .selection import build_operational_plan

_DOMAIN_AGENT = {
    "capacity": "Freyr",
    "cost": "Njord",
    "resilience": "Loki",
}


class PlanningConstraintEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        context: OperationalContextSnapshot,
        option: ActionOption,
    ) -> tuple[ConstraintEvaluation, ...]: ...


class PlanningCandidateSimulator(Protocol):
    async def simulate(
        self,
        *,
        context: OperationalContextSnapshot,
        candidate_id: str,
        action_type: str | None,
        effects: tuple[ObjectiveEffect, ...],
        observed_at: datetime,
    ) -> SimulationReceipt: ...


@dataclass(frozen=True, slots=True)
class SpecialistPlanningProjection:
    plan: OperationalPlan
    option_by_domain: tuple[tuple[str, str], ...]

    @property
    def case(self) -> DecisionCase:
        return self.plan.decision_case

    @property
    def selection(self) -> DecisionSelection:
        return self.plan.selection

    def option_for_domain(self, domain: str) -> ActionOption | None:
        option_id = dict(self.option_by_domain).get(domain)
        return next(
            (option for option in self.plan.decision_case.options if option.option_id == option_id),
            None,
        )

    def to_mapping(self) -> dict[str, object]:
        case = self.plan.decision_case
        selection = self.plan.selection
        return {
            "case_id": case.case_id,
            "process_id": case.process_id,
            "correlation_id": case.correlation_id,
            "context_snapshot_id": case.context_snapshot_id,
            "logic_release_digest": case.logic_release_digest,
            "created_at": case.created_at.isoformat(),
            "protected_objective_ids": list(case.protected_objective_ids),
            "active_constraint_ids": list(case.active_constraint_ids),
            "no_action_effects": [_effect_mapping(effect) for effect in case.no_action_effects],
            "selected_option_id": selection.selected_option_id,
            "requires_human_approval": selection.requires_human_approval,
            "selection_reason": selection.reason,
            "objective_scores": dict(selection.objective_scores),
            "option_by_domain": dict(self.option_by_domain),
            "options": [_option_mapping(option) for option in case.options],
            "evidence_refs": list(case.evidence_refs),
            "operational_plan": {
                "plan_id": self.plan.plan_id,
                "complete": self.plan.complete,
                "reason": self.plan.reason,
                "assessments": [
                    {
                        "candidate_id": item.candidate_id,
                        "disposition": item.disposition.value,
                        "reasons": list(item.reasons),
                    }
                    for item in self.plan.assessments
                ],
            },
        }


class SpecialistPlanningCoordinator:
    """Join existing specialist evidence with independent planning receipts."""

    def __init__(
        self,
        *,
        logic_release_digest: str,
        constraint_evaluator: PlanningConstraintEvaluator,
        simulator: PlanningCandidateSimulator,
        decision_coordinator: DomainDecisionCoordinator | None = None,
    ) -> None:
        if not logic_release_digest.startswith("sha256:") or len(logic_release_digest) != 71:
            raise ValueError("planning logic release digest MUST be SHA-256")
        self._logic_release_digest = logic_release_digest
        self._constraint_evaluator = constraint_evaluator
        self._simulator = simulator
        self._decision_coordinator = decision_coordinator or DomainDecisionCoordinator()

    async def build(
        self,
        *,
        correlation_id: str,
        context: OperationalContextSnapshot,
        advice: dict[str, str],
        impacts: dict[str, float],
        created_at: datetime,
    ) -> SpecialistPlanningProjection | None:
        base = self._decision_coordinator.build(
            correlation_id=correlation_id,
            context=context,
            advice=advice,
            impacts=impacts,
            created_at=created_at,
        )
        if base is None:
            return None
        candidates: list[PlanCandidate] = []
        option_by_domain: list[tuple[str, str]] = []
        for domain, option_id in base.option_by_domain:
            option = base.option_for_domain(domain)
            if option is None:
                continue
            agent = _DOMAIN_AGENT.get(domain)
            if agent is None:
                continue
            contribution = SpecialistContribution(
                agent=agent,
                domain=domain,
                recommendation=advice[domain],
                observed_at=created_at,
                impact=impacts.get(domain, 1.0),
                evidence_refs=option.evidence_refs,
            )
            constraints = await self._constraint_evaluator.evaluate(
                context=context,
                option=option,
            )
            simulation = await self._simulator.simulate(
                context=context,
                candidate_id=option.option_id,
                action_type=option.action_type,
                effects=option.effects,
                observed_at=created_at,
            )
            simulated_effects = simulation.predicted_effects or option.effects
            candidates.append(
                PlanCandidate(
                    candidate_id=option.option_id,
                    action_type=option.action_type,
                    effects=simulated_effects,
                    contributions=(contribution,),
                    constraints=constraints,
                    simulations=(simulation,),
                    evidence_refs=tuple(
                        dict.fromkeys((*option.evidence_refs, *simulation.evidence_refs))
                    ),
                )
            )
            option_by_domain.append((domain, option_id))
        if not candidates:
            return None
        process_identity = hashlib.sha256(
            f"{correlation_id}:{context.snapshot_id}:{self._logic_release_digest}".encode()
        ).hexdigest()
        plan = build_operational_plan(
            PlanningRequest(
                process_id=f"operational-planning:{process_identity}",
                correlation_id=correlation_id,
                logic_release_digest=self._logic_release_digest,
                context=context,
                no_action_effects=base.case.no_action_effects,
                protected_objective_ids=base.case.protected_objective_ids,
                candidates=tuple(candidates),
                objective_weights=tuple(_objective_weights(context)),
                created_at=created_at,
            )
        )
        return SpecialistPlanningProjection(plan=plan, option_by_domain=tuple(option_by_domain))


def _objective_weights(context: OperationalContextSnapshot) -> tuple[tuple[str, float], ...]:
    return tuple(
        {
            **{objective_id: 1.0 for objective_id in context.service_objective_ids},
            **{objective_id: 1.0 for objective_id in context.recovery_objective_ids},
            **{objective_id: 0.7 for objective_id in context.cost_objective_ids},
        }.items()
    )


def _effect_mapping(effect: ObjectiveEffect) -> dict[str, object]:
    return {
        "objective_id": effect.objective_id,
        "utility": effect.utility,
        "confidence": effect.confidence,
        "metric": effect.metric,
        "expected_min": effect.expected_min,
        "expected_max": effect.expected_max,
        "observation_window_seconds": effect.observation_window_seconds,
    }


def _option_mapping(option: ActionOption) -> dict[str, object]:
    return {
        "option_id": option.option_id,
        "action_type": option.action_type,
        "effects": [_effect_mapping(effect) for effect in option.effects],
        "evidence_refs": list(option.evidence_refs),
        "violated_constraint_ids": list(option.violated_constraint_ids),
        "proposing_agents": list(option.proposing_agents),
        "logic_receipt_refs": list(option.logic_receipt_refs),
        "simulation_receipt_refs": list(option.simulation_receipt_refs),
        "constraint_evaluation_refs": list(option.constraint_evaluation_refs),
        "assumptions": list(option.assumptions),
    }


__all__ = [
    "PlanningCandidateSimulator",
    "PlanningConstraintEvaluator",
    "SpecialistPlanningCoordinator",
    "SpecialistPlanningProjection",
]
