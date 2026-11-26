"""Build objective-aware decision cases from bounded specialist advice."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from fdai.core.operational_context import OperationalContextSnapshot

from .models import (
    ActionArguments,
    ActionOption,
    DecisionCase,
    DecisionSelection,
    ObjectiveEffect,
)
from .service import build_decision_case, select_action_option

_ACTION_TYPES = {"scale_up": "ops.scale-out", "scale_down": "ops.scale-in"}

# Hard cap on the objective effects one domain may declare for its option,
# so a malformed producer cannot inflate a case beyond bounded review.
MAX_DOMAIN_EVIDENCE_EFFECTS = 16


@dataclass(frozen=True, slots=True)
class DomainOptionEvidence:
    """One domain's runtime-grounded option: what it built and what it costs.

    ``action_type`` is the ActionType that domain's own deterministic
    runtime produced, ``effects`` are the signed objective utilities that
    action is expected to have, and ``evidence_refs`` is the canonical
    lineage both were read from (the event id, the cited rule ids, the
    audit digest). Supplying it replaces the coarse
    recommendation-to-ActionType projection for that domain, so a conflict
    rests on objective effects rather than on a recommendation vocabulary.
    """

    domain: str
    action_type: str
    effects: tuple[ObjectiveEffect, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.domain or not self.action_type:
            raise ValueError("domain option evidence identities MUST be non-empty")
        if not self.effects or not self.evidence_refs:
            raise ValueError("domain option evidence MUST carry effects and lineage")
        if len(self.effects) > MAX_DOMAIN_EVIDENCE_EFFECTS:
            raise ValueError("domain option evidence objective count exceeds the hard limit")
        objective_ids = [effect.objective_id for effect in self.effects]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("domain option evidence MUST carry one effect per objective")

    def utility_for(self, objective_id: str) -> float | None:
        """Return this option's signed utility for one objective, if declared."""
        return next(
            (effect.utility for effect in self.effects if effect.objective_id == objective_id),
            None,
        )


def conflicting_objective_effects(
    evidence: Sequence[DomainOptionEvidence],
) -> tuple[tuple[str, str, str], ...]:
    """Return every ``(domain, other_domain, objective_id)`` that opposes.

    Two domains conflict when one and the same objective moves in opposite
    directions under their two actions. The relation reads signed
    utilities only: it never inspects a recommendation label, so a shared
    direction vocabulary cannot manufacture a disagreement, and two
    options that push every objective the same way are never arbitrated as
    a conflict. Zero utility is an abstention on that objective, not an
    opposition.
    """

    ordered = sorted(evidence, key=lambda item: item.domain)
    found: set[tuple[str, str, str]] = set()
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if left.domain == right.domain:
                continue
            for effect in left.effects:
                other = right.utility_for(effect.objective_id)
                if other is None or effect.utility == 0.0 or other == 0.0:
                    continue
                if (effect.utility > 0.0) is not (other > 0.0):
                    found.add((left.domain, right.domain, effect.objective_id))
    return tuple(sorted(found))


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
                    "arguments": (
                        option.arguments.to_mapping() if option.arguments is not None else None
                    ),
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
        arguments_by_domain: Mapping[str, Mapping[str, object]] | None = None,
        evidence_by_domain: Mapping[str, DomainOptionEvidence] | None = None,
    ) -> DomainDecisionProjection | None:
        if not context.objective_ids:
            return None
        protected = (*context.service_objective_ids, *context.recovery_objective_ids)
        grounded = dict(evidence_by_domain or {})
        known_objectives = set(context.objective_ids)
        options: list[ActionOption] = []
        option_by_domain: list[tuple[str, str]] = []
        for domain in sorted({*advice, *grounded}):
            evidence = grounded.get(domain)
            if evidence is not None:
                # Runtime-grounded: the ActionType, the objective effects,
                # and the lineage all come from that domain's own replay.
                # Effects on objectives this context does not govern are
                # dropped rather than scored against an absent objective.
                effects = tuple(
                    effect for effect in evidence.effects if effect.objective_id in known_objectives
                )
                action_type = evidence.action_type
                option_id = f"{domain}:{action_type}"
                evidence_refs = tuple(
                    dict.fromkeys(
                        (*evidence.evidence_refs, f"specialist:{domain}:{correlation_id}")
                    )
                )
            else:
                recommendation = str(advice.get(domain, ""))
                projected = _ACTION_TYPES.get(recommendation)
                if projected is None:
                    continue
                action_type = projected
                impact = max(0.0, min(1.0, float(impacts.get(domain, 1.0))))
                effects = _effects(
                    domain=domain,
                    recommendation=recommendation,
                    impact=impact,
                    context=context,
                )
                option_id = f"{domain}:{recommendation}"
                evidence_refs = (f"specialist:{domain}:{correlation_id}",)
            if not effects:
                continue
            options.append(
                ActionOption(
                    option_id=option_id,
                    action_type=action_type,
                    effects=effects,
                    evidence_refs=evidence_refs,
                    arguments=(
                        ActionArguments.create(arguments_by_domain[domain])
                        if arguments_by_domain is not None and domain in arguments_by_domain
                        else None
                    ),
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
            # Case lineage is the union of what every option was built
            # from, so a runtime-grounded option carries its canonical
            # refs into the case instead of only the specialist marker.
            evidence_refs=(
                *(ref for option in options for ref in option.evidence_refs),
                *(
                    f"specialist:{domain}:{correlation_id}"
                    for domain in sorted({*advice, *grounded})
                ),
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


__all__ = [
    "MAX_DOMAIN_EVIDENCE_EFFECTS",
    "DomainDecisionCoordinator",
    "DomainDecisionProjection",
    "DomainOptionEvidence",
    "conflicting_objective_effects",
]
