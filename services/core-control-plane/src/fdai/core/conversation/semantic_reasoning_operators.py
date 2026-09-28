"""Compile instance-level question-form goals into verified read-plan specs.

A goal atom that no reviewed builder can express returns a typed unsupported
reason instead of a broader or substitute read.
"""

from __future__ import annotations

from typing import Any

from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json

from .semantic_planning_models import SemanticOutputShape
from .semantic_reasoning_anchoring import anchored_relation
from .semantic_reasoning_form import (
    DurationUnit,
    FilterRole,
    FormGoal,
    GoalLevel,
    GoalOperation,
    MeasureKind,
    RelationSense,
    SubjectPosition,
    SubjectScope,
    TimeKind,
    Want,
)
from .semantic_reasoning_nodes import (
    COLLECTION_LIMIT,
    FUNCTION_ANCHOR_LIMIT,
    RESOURCE_OBJECT_TYPE,
    TRAVERSAL_ANCHOR_LIMIT,
    CompileContext,
    OperatorResult,
    PlanSpec,
    anchor_node,
    containment_side,
    count_node,
    endpoint_predicates,
    function_declared,
    group_by,
    is_restrictive,
    object_set_node,
    plan_spec,
    subject_selection,
    traversal_node,
)
from .semantic_reasoning_relations import RelationSide, select_relation_sides
from .semantic_reasoning_schema import schema_goal

MAX_SIDES_PER_BATCH = 3
MAX_COUNT_SIDES = 8
MIN_LOOKBACK_SECONDS = 60
MAX_LOOKBACK_SECONDS = 604_800
_UNIT_SECONDS = {
    DurationUnit.MINUTE: 60,
    DurationUnit.HOUR: 3_600,
    DurationUnit.DAY: 86_400,
    DurationUnit.WEEK: 604_800,
}
_CURRENT_TIMES = frozenset({TimeKind.CURRENT, TimeKind.UNSPECIFIED})
_RELATION_READS = frozenset(
    {GoalOperation.SELECT, GoalOperation.TRAVERSE, GoalOperation.IMPACT, GoalOperation.COUNT}
)


def compile_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    """Return plan specs for one goal or the exact reason it cannot compile."""

    if goal.subject_scope in {SubjectScope.PRIOR_RESULT, SubjectScope.GOAL_OUTPUT}:
        return OperatorResult(
            unsupported=(f"subject_scope_unavailable:{goal.subject_scope.value}",)
        )
    if goal.want in {Want.CAUSE, Want.VERIFICATION}:
        return OperatorResult(unsupported=(f"want_unsupported:{goal.want.value}",))
    if goal.level is GoalLevel.SCHEMA:
        return schema_goal(goal, ctx)
    if (
        goal.effective_operation in {GoalOperation.SELECT, GoalOperation.COUNT}
        and goal.relation is None
    ):
        return _collection_goal(goal, ctx)
    # Listing the related resources of one anchor is the same read as traversing from it.
    if goal.effective_operation in _RELATION_READS:
        return _relation_goal(goal, ctx)
    if goal.effective_operation is GoalOperation.LOOKUP:
        return _lookup_goal(goal, ctx)
    if goal.effective_operation is GoalOperation.HISTORY:
        return _history_goal(goal, ctx)
    return OperatorResult(unsupported=(f"operation_unsupported:{goal.effective_operation.value}",))


def _collection_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    if goal.time.kind not in _CURRENT_TIMES:
        return OperatorResult(unsupported=(f"time_unsupported:{goal.time.kind.value}",))
    selector, predicates, failure = subject_selection(goal, ctx)
    if failure is not None:
        return failure
    scopes = [item for item in goal.filters if item.role is FilterRole.SCOPE]
    if len(scopes) > 1:
        return OperatorResult(unsupported=("multiple_scopes_unsupported",))
    group = group_by(goal)
    if isinstance(group, OperatorResult):
        return group
    prefix = goal.id
    if not scopes:
        node = object_set_node(
            f"{prefix}-collection", selector, predicates, ctx, limit=COLLECTION_LIMIT
        )
        nodes = [node]
        output = node.node_id
    else:
        anchor = anchor_node(f"{prefix}-scope", scopes[0].mention, ctx, TRAVERSAL_ANCHOR_LIMIT)
        if isinstance(anchor, OperatorResult):
            return anchor
        side = containment_side(ctx)
        if side is None or side.endpoint_type != selector:
            return OperatorResult(unsupported=("scope_containment_unavailable",))
        member = traversal_node(f"{prefix}-members", anchor.node_id, side, predicates, ctx)
        nodes = [anchor, member]
        output = member.node_id
    if goal.effective_operation is GoalOperation.COUNT:
        count = count_node(f"{prefix}-count", output, group)
        nodes.append(count)
        output = count.node_id
    return OperatorResult(
        specs=(
            plan_spec(
                goal,
                tuple(nodes),
                (output,),
                ctx,
                subjects=(selector,),
            ),
        )
    )


def _relation_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    if goal.time.kind not in _CURRENT_TIMES:
        return OperatorResult(unsupported=(f"time_unsupported:{goal.time.kind.value}",))
    anchored = anchored_relation(goal, ctx)
    if isinstance(anchored, OperatorResult):
        return anchored
    if any(
        item.role is FilterRole.SCOPE
        and not (
            item.mention == anchored.anchor
            and anchored.sense is RelationSense.CONTAINMENT
            and anchored.position is SubjectPosition.SOURCE
        )
        for item in goal.filters
    ):
        return OperatorResult(unsupported=("scope_filter_on_relation_unsupported",))
    predicates, failure = endpoint_predicates(goal, ctx, extra_types=anchored.subject_types)
    if failure is not None:
        return failure
    group = group_by(goal)
    if isinstance(group, OperatorResult):
        return group
    selection = select_relation_sides(
        ctx.manifest.descriptors,
        anchor_type=RESOURCE_OBJECT_TYPE,
        sense=anchored.sense,
        scope=anchored.scope,
        position=anchored.position,
        reach=anchored.reach,
    )
    limitations = [f"link_sense_unmapped:{name}" for name in selection.unmapped_link_types]
    if goal.effective_operation is GoalOperation.IMPACT:
        limitations.append("possible_impact_not_observed")
    # A restrictive endpoint filter reads only matching endpoint types; other endpoint types
    # cannot satisfy a Resource type or name predicate, so they are not silently widened.
    wanted = anchored.endpoint_object_type or (
        RESOURCE_OBJECT_TYPE if is_restrictive(predicates) else None
    )
    sides = tuple(
        side for side in selection.sides if wanted is None or side.endpoint_type == wanted
    )
    if not sides:
        reason = (
            "relation_not_transitive"
            if selection.intransitive_link_types
            else f"relation_sense_unmapped:{anchored.sense.value}"
            if anchored.sense is not None
            else "relation_sides_unavailable"
        )
        return OperatorResult(unsupported=(reason,), limitations=tuple(limitations))
    if goal.effective_operation is GoalOperation.COUNT:
        return _relation_count(goal, ctx, anchored.anchor, sides, predicates, group, limitations)
    specs: list[PlanSpec] = []
    for start in range(0, len(sides), MAX_SIDES_PER_BATCH):
        batch = sides[start : start + MAX_SIDES_PER_BATCH]
        anchor = anchor_node(f"{goal.id}-anchor", anchored.anchor, ctx, TRAVERSAL_ANCHOR_LIMIT)
        if isinstance(anchor, OperatorResult):
            return anchor
        traversals = tuple(
            traversal_node(
                f"{goal.id}-side-{start + offset + 1}",
                anchor.node_id,
                side,
                predicates if side.endpoint_type == RESOURCE_OBJECT_TYPE else [],
                ctx,
            )
            for offset, side in enumerate(batch)
        )
        specs.append(
            plan_spec(
                goal,
                (anchor, *traversals),
                tuple(node.node_id for node in traversals),
                ctx,
                subjects=(RESOURCE_OBJECT_TYPE, ctx.text(anchored.anchor)),
            )
        )
    return OperatorResult(specs=tuple(specs), limitations=tuple(limitations))


def _relation_count(
    goal: FormGoal,
    ctx: CompileContext,
    anchor_mention: str,
    sides: tuple[RelationSide, ...],
    predicates: list[dict[str, Any]],
    group: list[str],
    limitations: list[str],
) -> OperatorResult:
    if len(sides) > MAX_COUNT_SIDES:
        return OperatorResult(
            unsupported=("count_side_budget_exceeded",), limitations=tuple(limitations)
        )
    anchor = anchor_node(f"{goal.id}-anchor", anchor_mention, ctx, TRAVERSAL_ANCHOR_LIMIT)
    if isinstance(anchor, OperatorResult):
        return anchor
    traversals = [
        traversal_node(
            f"{goal.id}-side-{index}",
            anchor.node_id,
            side,
            predicates if side.endpoint_type == RESOURCE_OBJECT_TYPE else [],
            ctx,
        )
        for index, side in enumerate(sides, start=1)
    ]
    nodes: list[OntologyQueryNode] = [anchor, *traversals]
    source = traversals[0].node_id
    if len(traversals) > 1:
        union = OntologyQueryNode(
            node_id=f"{goal.id}-union",
            kind=QueryNodeKind.UNION,
            depends_on=tuple(node.node_id for node in traversals),
            output_kind="query.table",
        )
        nodes.append(union)
        source = union.node_id
    count = count_node(f"{goal.id}-count", source, group)
    nodes.append(count)
    return OperatorResult(
        specs=(
            plan_spec(
                goal,
                tuple(nodes),
                (count.node_id,),
                ctx,
                subjects=(RESOURCE_OBJECT_TYPE, ctx.text(anchor_mention)),
            ),
        ),
        limitations=tuple(limitations),
    )


def _lookup_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    if goal.measure is None or goal.subject is None:
        return OperatorResult(unsupported=("measure_required",))
    if goal.filters:
        return OperatorResult(unsupported=("filter_unsupported_for_operation:lookup",))
    if goal.time.kind not in _CURRENT_TIMES:
        return OperatorResult(unsupported=(f"time_unsupported:{goal.time.kind.value}",))
    if goal.measure.kind is not MeasureKind.STATE:
        return OperatorResult(unsupported=(f"measure_unsupported:{goal.measure.kind.value}",))
    return _anchored_function(
        goal,
        ctx,
        function_name="query.resource_current_state",
        arguments={},
        output_shape=SemanticOutputShape.TARGET_CURRENT_STATE,
    )


def _history_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    if goal.subject is None:
        return OperatorResult(unsupported=("anchor_missing",))
    if goal.filters:
        return OperatorResult(unsupported=("filter_unsupported_for_operation:history",))
    if goal.measure is not None and goal.measure.kind is not MeasureKind.CHANGE:
        return OperatorResult(unsupported=(f"measure_unsupported:{goal.measure.kind.value}",))
    lookback = history_lookback_seconds(goal, default_seconds=ctx.default_lookback_seconds)
    if isinstance(lookback, str):
        return OperatorResult(unsupported=(lookback,))
    seconds, defaulted = lookback
    result = _anchored_function(
        goal,
        ctx,
        function_name="query.resource_change_activity",
        arguments={"lookback_seconds": seconds},
        output_shape=SemanticOutputShape.RESOURCE_LIST,
    )
    if defaulted and result.specs:
        return OperatorResult(
            specs=result.specs, limitations=(f"default_window_applied:{seconds}",)
        )
    return result


def history_lookback_seconds(
    goal: FormGoal,
    *,
    default_seconds: int,
) -> tuple[int, bool] | str:
    """Return the trusted lookback for a history goal or the reason it is unusable."""

    kind = goal.time.kind
    if kind in _CURRENT_TIMES:
        return default_seconds, True
    if kind is not TimeKind.WINDOW or goal.time.value is None:
        return f"time_unsupported:{kind.value}"
    duration = goal.time.value.duration
    if duration is None:
        return "time_calendar_window_unsupported"
    seconds = duration.amount * _UNIT_SECONDS[duration.unit]
    if not MIN_LOOKBACK_SECONDS <= seconds <= MAX_LOOKBACK_SECONDS:
        return "time_window_out_of_bounds"
    return seconds, False


def _anchored_function(
    goal: FormGoal,
    ctx: CompileContext,
    *,
    function_name: str,
    arguments: dict[str, Any],
    output_shape: SemanticOutputShape,
) -> OperatorResult:
    if goal.subject is None:
        return OperatorResult(unsupported=("anchor_missing",))
    if not function_declared(ctx, function_name):
        return OperatorResult(unsupported=(f"function_unavailable:{function_name}",))
    anchor = anchor_node(f"{goal.id}-anchor", goal.subject, ctx, FUNCTION_ANCHOR_LIMIT)
    if isinstance(anchor, OperatorResult):
        return anchor
    function = OntologyQueryNode(
        node_id=f"{goal.id}-read",
        kind=QueryNodeKind.FUNCTION,
        depends_on=(anchor.node_id,),
        arguments_json=canonical_json(
            {
                "function_name": function_name,
                "arguments": arguments,
                "dependency_arguments": {anchor.node_id: "query_result"},
            }
        ),
        output_kind="query.table",
    )
    return OperatorResult(
        specs=(
            plan_spec(
                goal,
                (anchor, function),
                (function.node_id,),
                ctx,
                subjects=(RESOURCE_OBJECT_TYPE, ctx.text(goal.subject)),
                output_shape=output_shape,
            ),
        )
    )


__all__ = [
    "MAX_COUNT_SIDES",
    "MAX_LOOKBACK_SECONDS",
    "MAX_SIDES_PER_BATCH",
    "MIN_LOOKBACK_SECONDS",
    "compile_goal",
    "history_lookback_seconds",
]
