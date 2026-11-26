"""Deterministic constitutional eligibility checks for planning options."""

from __future__ import annotations

from fdai.core.decision_case import ActionOption
from fdai.core.operational_context import OperationalContextSnapshot

from .models import MAX_PLAN_CONSTRAINTS, ConstraintEvaluation, ConstraintStatus


class ConstitutionalPlanningConstraintEvaluator:
    """Evaluate context completeness and declared hard constraints without I/O."""

    async def evaluate(
        self,
        *,
        context: OperationalContextSnapshot,
        option: ActionOption,
    ) -> tuple[ConstraintEvaluation, ...]:
        if len(context.constraint_ids) + 2 > MAX_PLAN_CONSTRAINTS:
            raise ValueError("planning constraint count exceeds the hard limit")
        evidence = (f"context:{context.snapshot_id}", *option.evidence_refs)
        results = [
            ConstraintEvaluation(
                constraint_id="context_complete",
                status=(
                    ConstraintStatus.UNKNOWN if context.review_required else ConstraintStatus.PASSED
                ),
                precedence=1,
                reason_code=(
                    "context_requires_review" if context.review_required else "context_complete"
                ),
                evidence_refs=evidence,
            )
        ]
        protected = set(context.service_objective_ids) | set(context.recovery_objective_ids)
        regresses_protected = any(
            effect.objective_id in protected and effect.utility < 0.0 for effect in option.effects
        )
        results.append(
            ConstraintEvaluation(
                constraint_id="protected_objectives",
                status=(
                    ConstraintStatus.FAILED if regresses_protected else ConstraintStatus.PASSED
                ),
                precedence=3,
                reason_code=(
                    "protected_objective_regression"
                    if regresses_protected
                    else "protected_objectives_preserved"
                ),
                evidence_refs=evidence,
            )
        )
        violated = set(option.violated_constraint_ids)
        for constraint_id in sorted(context.constraint_ids):
            failed = constraint_id in violated
            results.append(
                ConstraintEvaluation(
                    constraint_id=constraint_id,
                    status=ConstraintStatus.FAILED if failed else ConstraintStatus.PASSED,
                    precedence=4,
                    reason_code="declared_constraint_failed" if failed else "constraint_preserved",
                    evidence_refs=evidence,
                )
            )
        return tuple(results)


__all__ = ["ConstitutionalPlanningConstraintEvaluator"]
