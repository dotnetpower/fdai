"""Independent checks for the health lookup and state history reads.

V-SEM and V-PROV recompute every argument these reads may carry from the admitted goal
and the evaluation time alone, so a plan that widens a window, swaps a metric, or reads a
different state history is rejected even though the compiler never emits one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import OntologyQueryNode

from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_health_assessment_queries import (
    TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
)
from fdai.core.ontology_platform.state_transitions import (
    RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
)

from .semantic_reasoning_form import FormGoal, GoalLevel, GoalOperation, MeasureKind, SubjectScope
from .semantic_reasoning_measure_reads import state_transition_arguments
from .semantic_target_health import (
    TARGET_HEALTH_METRICS,
    TARGET_HEALTH_WINDOW,
    target_health_window,
)

_HEALTH_CONCEPTS = frozenset(concept for _suffix, concept, _argument in TARGET_HEALTH_METRICS)


def is_health_lookup(goal: FormGoal) -> bool:
    return (
        goal.level is GoalLevel.INSTANCE
        and goal.effective_operation is GoalOperation.LOOKUP
        and goal.measure is not None
        and goal.measure.kind is MeasureKind.HEALTH
    )


def is_state_history(goal: FormGoal) -> bool:
    return (
        goal.level is GoalLevel.INSTANCE
        and goal.effective_operation is GoalOperation.HISTORY
        and goal.subject_scope is not SubjectScope.COLLECTION
        and goal.measure is not None
        and goal.measure.kind is MeasureKind.STATE
    )


def metric_scope_violations(
    node: OntologyQueryNode, goal: FormGoal, evaluation_time: datetime | None
) -> list[str]:
    """Accept a metric window only as one of the health assessment's reviewed inputs."""

    if not is_health_lookup(goal) or evaluation_time is None:
        return [f"prov_unexpected_node:{node.node_id}:{node.kind.value}"]
    start, end = target_health_window(evaluation_time)
    arguments = dict(node.arguments)
    concept = arguments.get("concept_id")
    if concept not in _HEALTH_CONCEPTS or arguments != {
        "concept_id": concept,
        "start": start,
        "end": end,
    }:
        return [f"prov_metric_window:{node.node_id}"]
    return []


def expected_measure_arguments(
    name: str | None,
    goal: FormGoal,
    lookback_seconds: int | None,
    evaluation_time: datetime | None,
) -> dict[str, Any] | None:
    """Return the only arguments a measure read may carry, or None when it has no rule here."""

    if is_health_lookup(goal):
        if name == RESOURCE_ACTIVITY_FUNCTION_NAME:
            return {"lookback_seconds": int(TARGET_HEALTH_WINDOW.total_seconds())}
        if name == TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME:
            return {}
    if name == RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME:
        if not is_state_history(goal) or lookback_seconds is None or evaluation_time is None:
            return {"unexpected": True}
        return state_transition_arguments(evaluation_time, lookback_seconds)
    return None


__all__ = [
    "expected_measure_arguments",
    "is_health_lookup",
    "is_state_history",
    "metric_scope_violations",
]
