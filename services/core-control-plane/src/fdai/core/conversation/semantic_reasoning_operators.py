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
    FormMeasure,
    GoalLevel,
    GoalOperation,
    GroupBy,
    MeasureKind,
    MentionDomain,
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
    has_type_predicate,
    object_set_node,
    plan_spec,
    readable,
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
_MEASURE_DOMAINS = frozenset({MentionDomain.STATE, MentionDomain.HEALTH, MentionDomain.METRIC})
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
    compiled = _SCHEMA_OPERATIONS if goal.level is GoalLevel.SCHEMA else _INSTANCE_OPERATIONS
    if goal.effective_operation not in compiled:
        return OperatorResult(
            unsupported=(f"operation_unsupported:{goal.effective_operation.value}",)
        )
    unread = _unread_atom(goal, ctx)
    if unread is not None:
        return OperatorResult(unsupported=(unread,))
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


_INSTANCE_OPERATIONS = frozenset(
    {
        GoalOperation.SELECT,
        GoalOperation.COUNT,
        GoalOperation.TRAVERSE,
        GoalOperation.IMPACT,
        GoalOperation.LOOKUP,
        GoalOperation.HISTORY,
    }
)
_SCHEMA_OPERATIONS = frozenset(
    {
        GoalOperation.DESCRIBE_SCHEMA,
        GoalOperation.TRAVERSE,
        GoalOperation.SELECT,
        GoalOperation.COUNT,
    }
)
# Measure kinds each compiled operation reads; any other measure atom is not dropped silently.
_READ_MEASURES: dict[GoalOperation, frozenset[MeasureKind]] = {
    GoalOperation.COUNT: frozenset({MeasureKind.COUNT}),
    GoalOperation.LOOKUP: frozenset({MeasureKind.STATE}),
    GoalOperation.HISTORY: frozenset({MeasureKind.CHANGE}),
    GoalOperation.SELECT: frozenset(),
    GoalOperation.TRAVERSE: frozenset(),
    GoalOperation.IMPACT: frozenset(),
    GoalOperation.DESCRIBE_SCHEMA: frozenset(),
}


def _unread_atom(goal: FormGoal, ctx: CompileContext) -> str | None:
    """Return the first stated atom no reviewed builder reads, so it is never ignored."""

    operation = goal.effective_operation
    cited = [goal.subject, *(item.mention for item in goal.filters)]
    if goal.measure is not None:
        cited.append(goal.measure.mention)
    if goal.relation is not None:
        cited.append(goal.relation.anchor)
        if goal.relation.counterpart is not None:
            return "counterpart_unsupported"
        if operation in {GoalOperation.LOOKUP, GoalOperation.HISTORY}:
            return f"relation_unsupported_for_operation:{operation.value}"
    if any(item is not None and ctx.mention(item).qualifier is not None for item in cited):
        return "qualified_mention_unsupported"
    if goal.level is GoalLevel.SCHEMA and goal.time.kind not in _CURRENT_TIMES:
        return f"time_unsupported:{goal.time.kind.value}"
    measure = goal.measure
    if measure is None:
        return None
    if measure.mention is not None and not _restates_measure(goal, measure, ctx):
        return "measure_mention_unsupported"
    readable = _READ_MEASURES.get(operation)
    if readable is not None and measure.kind not in readable:
        return f"measure_unsupported:{measure.kind.value}"
    if measure.group_by is not GroupBy.NONE and operation is not GoalOperation.COUNT:
        return f"group_by_unsupported_for_operation:{operation.value}"
    return None


def _restates_measure(goal: FormGoal, measure: FormMeasure, ctx: CompileContext) -> bool:
    """Return whether a measure mention only names what the goal already reads.

    It may restate the goal subject, as in counting ObjectTypes, or name the measure
    itself, as a state mention names a state lookup. Any other measure mention would
    be a restriction that no builder reads, so it is not accepted.
    """

    if measure.mention == goal.subject:
        return True
    domain = ctx.mention(str(measure.mention)).domain
    return domain.value == measure.kind.value and domain in _MEASURE_DOMAINS


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
    if selection.intransitive_link_types:
        # A transitive request is never narrowed to the subset of links that compose.
        return OperatorResult(
            unsupported=("relation_not_transitive",), limitations=tuple(limitations)
        )
    restrictive = [item for item in predicates if item.get("operator") != "not_equals"]
    # A restrictive filter reads only endpoint types that can satisfy it, so other endpoint
    # types are never silently widened past the filter.
    wanted = anchored.endpoint_object_type or (
        RESOURCE_OBJECT_TYPE if has_type_predicate(restrictive) else None
    )
    sides = tuple(
        side
        for side in selection.sides
        if (wanted is None or side.endpoint_type == wanted)
        and (not restrictive or readable(ctx, side.endpoint_type, restrictive))
    )
    if not sides:
        reason = (
            "endpoint_filter_unreadable"
            if restrictive and selection.sides
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
                _side_predicates(side, predicates),
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
                subjects=(RESOURCE_OBJECT_TYPE,),
            )
        )
    return OperatorResult(specs=tuple(specs), limitations=tuple(limitations))


def _side_predicates(side: RelationSide, predicates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep every restriction; the Resource hidden-type policy applies to Resource ends only."""

    if side.endpoint_type == RESOURCE_OBJECT_TYPE:
        return predicates
    return [item for item in predicates if item.get("operator") != "not_equals"]


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
            _side_predicates(side, predicates),
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
                subjects=(RESOURCE_OBJECT_TYPE,),
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
    # Every applied window is restated; one read from words without digits is the model's.
    if result.specs:
        judged = goal.id in ctx.admission.judged_times
        code = "time_window_model_judged" if judged else "time_window_applied"
        return OperatorResult(specs=result.specs, limitations=(f"{code}:{seconds}",))
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
                subjects=(RESOURCE_OBJECT_TYPE,),
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
