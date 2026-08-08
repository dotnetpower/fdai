"""Build objective-aware decision cases from bounded specialist advice."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from fdai.core.operational_context import OperationalContextSnapshot

from .models import ActionOption, DecisionCase, DecisionSelection, ObjectiveEffect
from .service import build_decision_case, select_action_option

_ACTION_TYPES = {"scale_up": "ops.scale-out", "scale_down": "ops.scale-in"}


@dataclass(frozen=True, slots=True)
class DomainDecisionProjection:
    case: DecisionCase
    selection: DecisionSelection
    option_by_domain: tuple[tuple[str, str], ...]

    def option_for_domain(self, domain: str) -> ActionOption | None:
        option_id = dict(self.option_by_domain).get(domain)
        return next((item for item in self.case.options if item.option_id == option_id), None)

    def to_mapping(self) -> dict[str, object]:
        return {
            "case_id": self.case.case_id,
            "correlation_id": self.case.correlation_id,
            "context_snapshot_id": self.case.context_snapshot_id,
            "created_at": self.case.created_at.isoformat(),
            "protected_objective_ids": list(self.case.protected_objective_ids),
            "active_constraint_ids": list(self.case.active_constraint_ids),
            "no_action_effects": [
                _effect_mapping(effect) for effect in self.case.no_action_effects
            ],
            "selected_option_id": self.selection.selected_option_id,
            "requires_human_approval": self.selection.requires_human_approval,
            "selection_reason": self.selection.reason,
            "objective_scores": dict(self.selection.objective_scores),
            "option_by_domain": dict(self.option_by_domain),
            "options": [
                {
                    "option_id": option.option_id,
                    "action_type": option.action_type,
                    "effects": [_effect_mapping(effect) for effect in option.effects],
                    "evidence_refs": list(option.evidence_refs),
                    "violated_constraint_ids": list(option.violated_constraint_ids),
                }
                for option in self.case.options
            ],
            "evidence_refs": list(self.case.evidence_refs),
        }


class DomainDecisionCoordinator:
    """Compile specialist advice against service, recovery, and cost objectives."""

    def build(
        self,
        *,
        correlation_id: str,
        context: OperationalContextSnapshot,
        advice: Mapping[str, str],
        impacts: Mapping[str, float],
        created_at: datetime,
    ) -> DomainDecisionProjection | None:
        if not context.objective_ids:
            return None
        protected = (*context.service_objective_ids, *context.recovery_objective_ids)
        options: list[ActionOption] = []
        option_by_domain: list[tuple[str, str]] = []
        for domain, recommendation in sorted(advice.items()):
            action_type = _ACTION_TYPES.get(recommendation)
            if action_type is None:
                continue
            impact = max(0.0, min(1.0, float(impacts.get(domain, 1.0))))
            effects = _effects(
                domain=domain,
                recommendation=recommendation,
                impact=impact,
                context=context,
            )
            if not effects:
                continue
            option_id = f"{domain}:{recommendation}"
            options.append(
                ActionOption(
                    option_id=option_id,
                    action_type=action_type,
                    effects=effects,
                    evidence_refs=(f"specialist:{domain}:{correlation_id}",),
                )
            )
            option_by_domain.append((domain, option_id))
        if not options:
            return None
        capacity_risk = -max(0.0, min(1.0, float(impacts.get("capacity", 0.0))))
        cost_risk = -max(0.0, min(1.0, float(impacts.get("cost", 0.0))))
        baseline = (
            *(
                _effect(objective_id, capacity_risk, "no_action_reliability_risk")
                for objective_id in protected
            ),
            *(
                _effect(objective_id, cost_risk, "no_action_cost_risk")
                for objective_id in context.cost_objective_ids
            ),
        )
        case = build_decision_case(
            correlation_id=correlation_id,
            context=context,
            created_at=created_at,
            no_action_effects=baseline,
            options=options,
            protected_objective_ids=protected,
            evidence_refs=tuple(
                f"specialist:{domain}:{correlation_id}" for domain in sorted(advice)
            ),
        )
        weights = {
            **{objective_id: 1.0 for objective_id in protected},
            **{objective_id: 0.7 for objective_id in context.cost_objective_ids},
        }
        return DomainDecisionProjection(
            case=case,
            selection=select_action_option(case, objective_weights=weights),
            option_by_domain=tuple(option_by_domain),
        )


def _effects(
    *,
    domain: str,
    recommendation: str,
    impact: float,
    context: OperationalContextSnapshot,
) -> tuple[ObjectiveEffect, ...]:
    effects: list[ObjectiveEffect] = []
    reliability_utility = (
        impact if domain == "capacity" and recommendation == "scale_up" else -impact
    )
    for objective_id in (*context.service_objective_ids, *context.recovery_objective_ids):
        effects.append(_effect(objective_id, reliability_utility, "reliability_utility"))
    cost_utility = impact if domain == "cost" and recommendation == "scale_down" else -impact
    for objective_id in context.cost_objective_ids:
        effects.append(_effect(objective_id, cost_utility, "cost_utility"))
    return tuple(effects)


def _effect(objective_id: str, utility: float, metric: str) -> ObjectiveEffect:
    return ObjectiveEffect(
        objective_id=objective_id,
        utility=utility,
        confidence=0.9,
        metric=metric,
        expected_min=-1.0,
        expected_max=1.0,
        observation_window_seconds=300,
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


__all__ = ["DomainDecisionCoordinator", "DomainDecisionProjection"]
