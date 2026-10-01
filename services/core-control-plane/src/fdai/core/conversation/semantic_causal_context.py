"""Build read-only causal context plans without naming a cause."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json

from .semantic_reasoning_form import FormGoal
from .semantic_reasoning_measure_reads import (
    RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
    state_transition_arguments,
)
from .semantic_reasoning_nodes import (
    FUNCTION_ANCHOR_LIMIT,
    RESOURCE_OBJECT_TYPE,
    CompileContext,
    OperatorResult,
    anchor_node,
    declared_measures,
    function_declared,
    plan_spec,
)

CAUSE_CONTEXT_SHAPE = "cause_context"
CAUSE_NOT_ESTABLISHED = "cause.not_established"
CURRENT_STATE_FUNCTION = "query.resource_current_state"
CHANGE_ACTIVITY_FUNCTION = "query.resource_change_activity"
CAUSAL_CONTEXT_FUNCTIONS = (
    CURRENT_STATE_FUNCTION,
    RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
    CHANGE_ACTIVITY_FUNCTION,
)


def causal_context_result(
    goal: FormGoal,
    ctx: CompileContext,
    *,
    seconds: int,
    limitation: str,
    requirement: str,
) -> OperatorResult:
    """Read current state, state-transition change points, and full activity context."""

    for name in CAUSAL_CONTEXT_FUNCTIONS:
        if not function_declared(ctx, name):
            return OperatorResult(unsupported=(f"function_unavailable:{name}",))
    anchor = anchor_node(f"{goal.id}-anchor", goal.subject, ctx, FUNCTION_ANCHOR_LIMIT)
    if isinstance(anchor, OperatorResult):
        return anchor
    reads = tuple(
        OntologyQueryNode(
            node_id=f"{goal.id}-{suffix}",
            kind=QueryNodeKind.FUNCTION,
            depends_on=(anchor.node_id,),
            arguments_json=canonical_json(
                {
                    "function_name": name,
                    "arguments": arguments,
                    "dependency_arguments": {anchor.node_id: "query_result"},
                }
            ),
            output_kind="query.table",
        )
        for suffix, name, arguments in (
            ("state", CURRENT_STATE_FUNCTION, {}),
            (
                "transitions",
                RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
                state_transition_arguments(ctx.evaluation_time, seconds),
            ),
            ("activity", CHANGE_ACTIVITY_FUNCTION, {"lookback_seconds": seconds}),
        )
    )
    spec = plan_spec(
        goal,
        (anchor, *reads),
        tuple(node.node_id for node in reads),
        ctx,
        subjects=(RESOURCE_OBJECT_TYPE,),
        output_shape=CAUSE_CONTEXT_SHAPE,
        measure_concepts=declared_measures(ctx, CURRENT_STATE_FUNCTION),
        evidence_requirements=(CAUSE_NOT_ESTABLISHED, requirement),
    )
    return OperatorResult(specs=(spec,), limitations=("cause_not_established", limitation))


__all__ = [
    "CAUSE_CONTEXT_SHAPE",
    "CAUSE_NOT_ESTABLISHED",
    "CHANGE_ACTIVITY_FUNCTION",
    "CURRENT_STATE_FUNCTION",
    "causal_context_result",
]
