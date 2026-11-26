"""Typed prerequisite reasons for remaining closed-form operators."""

from __future__ import annotations

from .semantic_reasoning_form import FormGoal, GoalOperation, MeasureKind, SubjectScope
from .semantic_reasoning_nodes import OperatorResult

_REASONS = {
    GoalOperation.RANK: "rank_measure_unreviewed",
    GoalOperation.AGGREGATE: "aggregate_measure_unreviewed",
    GoalOperation.COMPARE_WINDOWS: "compare_windows_requires_two_typed_windows",
    GoalOperation.COMPARE_ENTITIES: "compare_entities_requires_two_bound_anchors",
    GoalOperation.DIFF_VERSIONS: "version_history_unavailable",
    GoalOperation.VERIFY_EVIDENCE: "link_evidence_allowlist_unavailable",
    GoalOperation.DIAGNOSE: "diagnose_recipe_unavailable",
    GoalOperation.PATH: "path_grammar_unavailable",
}


def remaining_operator_result(goal: FormGoal) -> OperatorResult | None:
    """Return the exact missing prerequisite for an E9 operator, if it is not implemented."""

    # A collection ranked by one reviewed metric compiles through the metric reader (E11).
    if (
        goal.effective_operation is GoalOperation.RANK
        and goal.subject_scope is SubjectScope.COLLECTION
        and goal.relation is None
        and goal.measure is not None
        and goal.measure.kind is MeasureKind.METRIC
    ):
        return None
    reason = _REASONS.get(goal.effective_operation)
    return OperatorResult(unsupported=(reason,)) if reason is not None else None


__all__ = ["remaining_operator_result"]
