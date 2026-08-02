from __future__ import annotations

from dataclasses import replace

from fdai.core.decision_case import ActionOption, ObjectiveEffect
from fdai.core.operational_planning import (
    ConstitutionalPlanningConstraintEvaluator,
    ConstraintStatus,
)
from fdai.shared.contracts.models import Autonomy

from .test_coordinator import _context


async def test_constitutional_constraints_fail_protected_regression() -> None:
    option = ActionOption(
        option_id="cost:scale_down",
        action_type="ops.scale-in",
        effects=(
            ObjectiveEffect("reliability", -0.2, 0.9, "availability", 0.8, 0.9, 300),
            ObjectiveEffect("cost", 0.8, 0.9, "usd", 10.0, 20.0, 300),
        ),
        evidence_refs=("forecast:cost",),
    )

    results = await ConstitutionalPlanningConstraintEvaluator().evaluate(
        context=_context(),
        option=option,
    )

    by_id = {result.constraint_id: result for result in results}
    assert by_id["context_complete"].status is ConstraintStatus.PASSED
    assert by_id["protected_objectives"].status is ConstraintStatus.FAILED


async def test_constitutional_constraints_treat_review_context_as_unknown() -> None:
    context = replace(
        _context(),
        stale_sources=("inventory",),
        autonomy_ceiling=Autonomy.SHADOW_ONLY,
    )
    option = ActionOption(
        option_id="capacity:scale_up",
        action_type="ops.scale-out",
        effects=(ObjectiveEffect("reliability", 0.8, 0.9, "availability", 0.9, 1.0, 300),),
        evidence_refs=("forecast:capacity",),
    )

    results = await ConstitutionalPlanningConstraintEvaluator().evaluate(
        context=context,
        option=option,
    )

    assert results[0].status is ConstraintStatus.UNKNOWN
