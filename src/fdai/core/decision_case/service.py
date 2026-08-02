"""Pure construction, arbitration, and closure for decision cases."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from math import isfinite

from fdai.core.operational_context import OperationalContextSnapshot
from fdai.shared.contracts.models import ResponseOutcome, ResponseOutcomeLabel

from .models import (
    ActionOption,
    DecisionCase,
    DecisionClosure,
    DecisionSelection,
    ObjectiveEffect,
)


def build_decision_case(
    *,
    correlation_id: str,
    context: OperationalContextSnapshot,
    created_at: datetime,
    no_action_effects: Sequence[ObjectiveEffect],
    options: Sequence[ActionOption],
    protected_objective_ids: Sequence[str],
    evidence_refs: Sequence[str],
    process_id: str | None = None,
    logic_release_digest: str | None = None,
) -> DecisionCase:
    """Build one replay-stable case from an operational context snapshot."""
    canonical_baseline = tuple(sorted(no_action_effects, key=_effect_sort_key))
    canonical_options = tuple(
        sorted((_canonical_option(option) for option in options), key=lambda item: item.option_id)
    )
    material = {
        "context": context.snapshot_id,
        "correlation": correlation_id,
        "evidence": sorted(set(evidence_refs)),
        "logic_release_digest": logic_release_digest,
        "no_action_effects": [_effect_material(effect) for effect in canonical_baseline],
        "options": [_option_material(option) for option in canonical_options],
        "process_id": process_id,
        "protected_objective_ids": sorted(set(protected_objective_ids)),
    }
    case_id = hashlib.sha256(
        json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return DecisionCase(
        case_id=case_id,
        correlation_id=correlation_id,
        context_snapshot_id=context.snapshot_id,
        created_at=created_at,
        no_action_effects=canonical_baseline,
        options=canonical_options,
        protected_objective_ids=tuple(sorted(set(protected_objective_ids))),
        active_constraint_ids=context.constraint_ids,
        evidence_refs=tuple(sorted(set(evidence_refs))),
        process_id=process_id,
        logic_release_digest=logic_release_digest,
    )


def select_action_option(
    case: DecisionCase,
    *,
    objective_weights: Mapping[str, float],
    hil_margin: float = 0.10,
) -> DecisionSelection:
    """Select the highest eligible option and hold close or unsafe choices."""

    if not isfinite(hil_margin) or hil_margin < 0.0:
        raise ValueError("hil_margin MUST be finite and >= 0")
    weights = _validated_weights(objective_weights)
    protected = set(case.protected_objective_ids)
    active_constraints = set(case.active_constraint_ids)
    eligible: list[tuple[ActionOption, float]] = []
    rejected: list[str] = []
    for option in case.options:
        if active_constraints.intersection(option.violated_constraint_ids):
            rejected.append(f"{option.option_id}:constraint")
            continue
        protected_regression = any(
            effect.objective_id in protected and effect.utility < 0.0 for effect in option.effects
        )
        if protected_regression:
            rejected.append(f"{option.option_id}:protected_objective")
            continue
        score = sum(
            weights.get(effect.objective_id, 0.0) * effect.utility * effect.confidence
            for effect in option.effects
        )
        eligible.append((option, round(score, 6)))
    if not eligible:
        return DecisionSelection(None, (), 0.0, True, "no_safe_option")
    eligible.sort(key=lambda item: (-item[1], item[0].option_id))
    top_option, top_score = eligible[0]
    second_score = eligible[1][1] if len(eligible) > 1 else 0.0
    margin = round((top_score - second_score) / abs(top_score), 6) if top_score else 0.0
    close = len(eligible) > 1 and margin < hil_margin
    reason = "close_call" if close else "weighted_objective_score"
    if rejected:
        reason = f"{reason};rejected={','.join(sorted(rejected))}"
    return DecisionSelection(
        selected_option_id=top_option.option_id,
        objective_scores=tuple((item.option_id, score) for item, score in eligible),
        margin=margin,
        requires_human_approval=close,
        reason=reason,
    )


def close_decision(
    case: DecisionCase,
    selection: DecisionSelection,
    outcome: ResponseOutcome,
) -> DecisionClosure:
    """Join a selected option to an independently observed response outcome."""

    selected = next(
        (option for option in case.options if option.option_id == selection.selected_option_id),
        None,
    )
    if selected is None or selected.action_type is None:
        raise ValueError("decision closure requires one selected executable option")
    if selected.action_type != outcome.action_type_id:
        raise ValueError("response outcome action type does not match selected option")
    verified = outcome.label is ResponseOutcomeLabel.VERIFIED
    guard_regression = outcome.rollback_succeeded is False
    reusable = verified and not guard_regression and outcome.scorable
    return DecisionClosure(
        case_id=case.case_id,
        selected_option_id=selected.option_id,
        outcome_id=str(outcome.outcome_id),
        effect_verified=verified,
        guard_regression=guard_regression,
        reusable=reusable,
        reason="verified" if reusable else "outcome_not_reusable",
    )


def _validated_weights(value: Mapping[str, float]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for objective_id, weight in value.items():
        numeric = float(weight)
        if not objective_id or not isfinite(numeric) or numeric < 0.0:
            raise ValueError("objective weights MUST be named, finite, and >= 0")
        weights[objective_id] = numeric
    return weights


def _effect_material(effect: ObjectiveEffect) -> dict[str, object]:
    return {
        "objective_id": effect.objective_id,
        "utility": effect.utility,
        "confidence": effect.confidence,
        "metric": effect.metric,
        "expected_min": effect.expected_min,
        "expected_max": effect.expected_max,
        "observation_window_seconds": effect.observation_window_seconds,
    }


def _effect_sort_key(effect: ObjectiveEffect) -> tuple[str, str]:
    return effect.objective_id, effect.metric


def _canonical_option(option: ActionOption) -> ActionOption:
    return replace(
        option,
        effects=tuple(sorted(option.effects, key=_effect_sort_key)),
        evidence_refs=tuple(sorted(set(option.evidence_refs))),
        violated_constraint_ids=tuple(sorted(set(option.violated_constraint_ids))),
        proposing_agents=tuple(sorted(set(option.proposing_agents))),
        logic_receipt_refs=tuple(sorted(set(option.logic_receipt_refs))),
        simulation_receipt_refs=tuple(sorted(set(option.simulation_receipt_refs))),
        constraint_evaluation_refs=tuple(sorted(set(option.constraint_evaluation_refs))),
        assumptions=tuple(sorted(set(option.assumptions))),
    )


def _option_material(option: ActionOption) -> dict[str, object]:
    return {
        "option_id": option.option_id,
        "action_type": option.action_type,
        "effects": [_effect_material(effect) for effect in option.effects],
        "evidence_refs": list(option.evidence_refs),
        "violated_constraint_ids": list(option.violated_constraint_ids),
        "proposing_agents": list(option.proposing_agents),
        "logic_receipt_refs": list(option.logic_receipt_refs),
        "simulation_receipt_refs": list(option.simulation_receipt_refs),
        "constraint_evaluation_refs": list(option.constraint_evaluation_refs),
        "assumptions": list(option.assumptions),
    }


__all__ = ["build_decision_case", "close_decision", "select_action_option"]
