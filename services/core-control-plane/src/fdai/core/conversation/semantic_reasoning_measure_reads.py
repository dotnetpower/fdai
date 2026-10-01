"""Compile a health lookup and a state history of one bound Resource.

A health lookup reads the reviewed single-target health assessment, the same shape the
current path plans, with its fixed window. A state history reads the reviewed state
transitions of the anchor in the stated or default window, across every reviewed
transition type and target state; the reader reports its own coverage, so an answer
never claims a complete history that the source didn't observe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    QueryNodeKind,
    canonical_json,
)

from fdai.core.ontology_platform.state_transitions import (
    RESOURCE_STATE_TRANSITION_TYPES,
    RESOURCE_STATE_TRANSITION_VALUES,
    RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
)

from .semantic_planning_models import SemanticOutputShape
from .semantic_reasoning_form import FormGoal
from .semantic_reasoning_nodes import (
    FUNCTION_ANCHOR_LIMIT,
    RESOURCE_OBJECT_TYPE,
    CompileContext,
    OperatorResult,
    anchor_node,
    function_declared,
    plan_spec,
)
from .semantic_target_health import (
    TARGET_HEALTH_FUNCTIONS,
    TARGET_HEALTH_WINDOW,
    target_health_nodes,
)

STATE_TRANSITION_LIMIT = 256
HEALTH_WINDOW_REQUIREMENT = f"window.fixed.{int(TARGET_HEALTH_WINDOW.total_seconds())}"


def health_lookup(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    """Read the reviewed health assessment of the goal's one bound Resource."""

    if goal.subject is None:
        return OperatorResult(unsupported=("anchor_missing",))
    for name in sorted(TARGET_HEALTH_FUNCTIONS):
        if not function_declared(ctx, name):
            return OperatorResult(unsupported=(f"function_unavailable:{name}",))
    anchor = anchor_node(f"{goal.id}-anchor", goal.subject, ctx, FUNCTION_ANCHOR_LIMIT)
    if isinstance(anchor, OperatorResult):
        return anchor
    nodes = target_health_nodes(goal.id, anchor.node_id, ctx.evaluation_time)
    seconds = int(TARGET_HEALTH_WINDOW.total_seconds())
    return OperatorResult(
        specs=(
            plan_spec(
                goal,
                (anchor, *nodes),
                (nodes[-1].node_id,),
                ctx,
                subjects=(RESOURCE_OBJECT_TYPE,),
                output_shape=SemanticOutputShape.TARGET_HEALTH_ASSESSMENT,
                evidence_requirements=(HEALTH_WINDOW_REQUIREMENT,),
            ),
        ),
        # The assessment reads a fixed window, stated so the answer restates it.
        limitations=(f"time_window_fixed:{seconds}",),
    )


def state_transition_arguments(evaluation_time: datetime, seconds: int) -> dict[str, Any]:
    """Return the reviewed transition read over every type and target state."""

    end = evaluation_time.astimezone(UTC)
    return {
        "state_types": list(RESOURCE_STATE_TRANSITION_TYPES),
        "to_states": list(RESOURCE_STATE_TRANSITION_VALUES),
        "start_at": (end - timedelta(seconds=seconds)).isoformat(),
        "end_at": end.isoformat(),
        "known_at": end.isoformat(),
        "limit": STATE_TRANSITION_LIMIT,
    }


def state_history(
    goal: FormGoal, ctx: CompileContext, seconds: int, requirement: str
) -> OperatorResult:
    """Read the state transitions of the goal's one bound Resource in the window."""

    if goal.subject is None:
        return OperatorResult(unsupported=("anchor_missing",))
    if not function_declared(ctx, RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME):
        name = RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME
        return OperatorResult(unsupported=(f"function_unavailable:{name}",))
    anchor = anchor_node(f"{goal.id}-anchor", goal.subject, ctx, FUNCTION_ANCHOR_LIMIT)
    if isinstance(anchor, OperatorResult):
        return anchor
    read = OntologyQueryNode(
        node_id=f"{goal.id}-transitions",
        kind=QueryNodeKind.FUNCTION,
        depends_on=(anchor.node_id,),
        arguments_json=canonical_json(
            {
                "function_name": RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
                "arguments": state_transition_arguments(ctx.evaluation_time, seconds),
                "dependency_arguments": {anchor.node_id: "query_result"},
            }
        ),
        output_kind="query.table",
    )
    return OperatorResult(
        specs=(
            plan_spec(
                goal,
                (anchor, read),
                (read.node_id,),
                ctx,
                subjects=(RESOURCE_OBJECT_TYPE,),
                output_shape=SemanticOutputShape.RESOURCE_STATE_TRANSITIONS,
                evidence_requirements=(requirement,),
            ),
        )
    )


__all__ = [
    "HEALTH_WINDOW_REQUIREMENT",
    "STATE_TRANSITION_LIMIT",
    "health_lookup",
    "state_history",
    "state_transition_arguments",
]
