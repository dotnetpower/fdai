"""Compile instance-level question-form goals into verified read-plan specs.

A goal atom that no reviewed builder can express returns a typed unsupported
reason instead of a broader or substitute read.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import Any

from fdai_service_contracts.ontology_query import (
    MAX_INTENT_GRAPH_GOALS,
    OntologyQueryNode,
    QueryNodeKind,
    canonical_json,
)

from fdai.core.ontology_platform.resource_event_queries import RESOURCE_EVENT_MEASURE_CONCEPTS
from fdai.core.ontology_platform.resource_state_queries import RESOURCE_STATE_FUNCTION_NAME

from .semantic_planning_models import SemanticOutputShape
from .semantic_reasoning_admission import restated_relation, restates_filter
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
from .semantic_reasoning_handles import (
    MAX_REFERENCE_BYTES,
    reference_bytes,
    reference_mention,
    starts_from_reference,
)
from .semantic_reasoning_nodes import (
    COLLECTION_LIMIT,
    FUNCTION_ANCHOR_LIMIT,
    RESOURCE_OBJECT_TYPE,
    RESOURCE_TYPE_DOMAINS,
    TRAVERSAL_ANCHOR_LIMIT,
    CompileContext,
    OperatorResult,
    PlanSpec,
    anchor_node,
    concept_values,
    containment_side,
    count_node,
    declared_maximum,
    declared_measures,
    endpoint_predicates,
    function_declared,
    group_by,
    has_type_predicate,
    object_set_node,
    plan_spec,
    readable,
    state_filter_node,
    subject_selection,
    traversal_node,
    union_tree,
)
from .semantic_reasoning_relations import RelationSide, select_relation_sides
from .semantic_reasoning_schema import schema_goal

MAX_SIDES_PER_BATCH = 3
# Compiler-only output shapes, rendered as verified evidence tables with reviewed notices.
CAUSE_CONTEXT_SHAPE = "cause_context"
CHANGE_ACTIVITY_SHAPE = "change_activity"
CAUSE_NOT_ESTABLISHED = "cause.not_established"
IMPACT_POSSIBLE_ONLY = "impact.possible_not_observed"
CURRENT_STATE_FUNCTION = "query.resource_current_state"
CHANGE_ACTIVITY_FUNCTION = "query.resource_change_activity"
RECENT_CHANGES_FUNCTION = "query.recent_resource_changes"
EVENT_HISTORY_FUNCTION = "query.resource_event_history"
# Every reviewed event family; the form has no narrower event kind to state.
EVENT_FAMILIES = tuple(sorted(RESOURCE_EVENT_MEASURE_CONCEPTS))
_WINDOW_LIMITATIONS = {
    "default": "default_window_applied",
    "applied": "time_window_applied",
    "model_judged": "time_window_model_judged",
}
# An anchor read, one traversal per side, their union tree, and the aggregate fit one intent
# graph of 16 goals: eleven sides need two union parts and a root union.
MAX_COUNT_SIDES = 11
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

    if goal.subject_scope is SubjectScope.GOAL_OUTPUT:
        return OperatorResult(
            unsupported=(f"subject_scope_unavailable:{goal.subject_scope.value}",)
        )
    # A cause is read only as causal context of one explain_cause goal, never as a fact.
    if goal.want is Want.VERIFICATION or (
        goal.want is Want.CAUSE and goal.effective_operation is not GoalOperation.EXPLAIN_CAUSE
    ):
        return OperatorResult(unsupported=(f"want_unsupported:{goal.want.value}",))
    compiled = _SCHEMA_OPERATIONS if goal.level is GoalLevel.SCHEMA else _INSTANCE_OPERATIONS
    if goal.effective_operation not in compiled:
        return OperatorResult(
            unsupported=(f"operation_unsupported:{goal.effective_operation.value}",)
        )
    unread = _unread_atom(goal, ctx)
    if unread is not None:
        return OperatorResult(unsupported=(unread,))
    # A reference clarifies only after every check a new handle could not change.
    if goal.subject_scope is SubjectScope.PRIOR_RESULT:
        failure = _prior_result_failure(goal, ctx)
        if failure is not None:
            return failure
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
    if goal.effective_operation is GoalOperation.EXPLAIN_CAUSE:
        return _cause_goal(goal, ctx)
    return OperatorResult(unsupported=(f"operation_unsupported:{goal.effective_operation.value}",))


def _prior_result_failure(goal: FormGoal, ctx: CompileContext) -> OperatorResult | None:
    """Return why a goal over an earlier answer's rows cannot compile, if it cannot.

    A reference that binds no rows clarifies with its typed reason. An anaphor over
    several rows cannot anchor one traversal, so a goal that starts from them is
    unsupported rather than silently reduced to one row.
    """

    mention_id = reference_mention(ctx.admission, goal.id)
    binding = ctx.references.binding(mention_id)
    if binding is None:
        return OperatorResult(clarify=("prior_result_unavailable",))
    if not binding.bound:
        return OperatorResult(clarify=(f"prior_result_{binding.outcome.value}",))
    if starts_from_reference(goal, mention_id) and len(binding.row_ids) != 1:
        return OperatorResult(unsupported=("prior_result_multiple_anchors_unsupported",))
    if reference_bytes(binding.row_ids) > MAX_REFERENCE_BYTES:
        return OperatorResult(unsupported=("prior_result_too_large",))
    return None


_INSTANCE_OPERATIONS = frozenset(
    {
        GoalOperation.SELECT,
        GoalOperation.COUNT,
        GoalOperation.TRAVERSE,
        GoalOperation.IMPACT,
        GoalOperation.LOOKUP,
        GoalOperation.HISTORY,
        GoalOperation.EXPLAIN_CAUSE,
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
    GoalOperation.HISTORY: frozenset({MeasureKind.CHANGE, MeasureKind.EVENT}),
    GoalOperation.EXPLAIN_CAUSE: frozenset({MeasureKind.STATE, MeasureKind.CHANGE}),
    GoalOperation.SELECT: frozenset(),
    GoalOperation.TRAVERSE: frozenset(),
    # An impact goal reads what could be affected if its anchor fails; a stated failure
    # state or health only restates that premise.
    GoalOperation.IMPACT: frozenset({MeasureKind.STATE, MeasureKind.HEALTH}),
    GoalOperation.DESCRIBE_SCHEMA: frozenset(),
}


def _unread_atom(goal: FormGoal, ctx: CompileContext) -> str | None:
    """Return the first stated atom no reviewed builder reads, so it is never ignored."""

    operation = goal.effective_operation
    cited = [goal.subject, *(item.mention for item in goal.filters)]
    if goal.measure is not None:
        cited.append(goal.measure.mention)
    if goal.relation is not None and not restated_relation(goal):
        cited.append(goal.relation.anchor)
        if goal.relation.counterpart is not None:
            return "counterpart_unsupported"
        if operation in {GoalOperation.LOOKUP, GoalOperation.HISTORY}:
            return f"relation_unsupported_for_operation:{operation.value}"
    if any(item is not None and _unread_qualifier(goal, item, ctx) for item in cited):
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


def _unread_qualifier(goal: FormGoal, mention_id: str, ctx: CompileContext) -> bool:
    """Return whether a cited mention's qualifier states an atom no builder reads.

    A qualifier on the subject that names one of the goal's own filters only restates
    that filter, which the goal already reads.
    """

    qualifier = ctx.mention(mention_id).qualifier
    return qualifier is not None and not restates_filter((goal,), mention_id, qualifier.mention)


def _restates_measure(goal: FormGoal, measure: FormMeasure, ctx: CompileContext) -> bool:
    """Return whether a measure mention only names what the goal already reads.

    It may restate the goal subject, as in counting ObjectTypes, or the type filter of a
    goal without a subject, or name the measure itself, as a state mention names a state
    lookup. Any other measure mention would be a restriction that no builder reads, so it
    is not accepted.
    """

    if measure.mention == goal.subject:
        return True
    # With no subject, the kind the goal reads is its type filter, as VMs in how many VMs.
    if goal.subject is None and any(
        item.role is FilterRole.TYPE and item.mention == measure.mention for item in goal.filters
    ):
        return True
    domain = ctx.mention(str(measure.mention)).domain
    return domain.value == measure.kind.value and domain in _MEASURE_DOMAINS


def _collection_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    if goal.time.kind not in _CURRENT_TIMES:
        return OperatorResult(unsupported=(f"time_unsupported:{goal.time.kind.value}",))
    states = _stated_states(goal, ctx)
    if isinstance(states, OperatorResult):
        return states
    selector, predicates, failure = subject_selection(goal, ctx, state_stage=bool(states))
    if failure is not None:
        return failure
    if states and selector != RESOURCE_OBJECT_TYPE:
        return OperatorResult(unsupported=("state_filter_requires_resource",))
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
    if states:
        state = state_filter_node(f"{prefix}-state", output, states)
        nodes.append(state)
        output = state.node_id
    if goal.effective_operation is GoalOperation.COUNT:
        count = count_node(f"{prefix}-count", output, group)
        nodes.append(count)
        output = count.node_id
    listed_states = states and goal.effective_operation is not GoalOperation.COUNT
    return OperatorResult(
        specs=(
            plan_spec(
                goal,
                tuple(nodes),
                (output,),
                ctx,
                subjects=(selector,),
                output_shape=SemanticOutputShape.RESOURCE_STATE_LIST if listed_states else None,
                measure_concepts=states if listed_states else (),
            ),
        )
    )


def _stated_states(goal: FormGoal, ctx: CompileContext) -> tuple[str, ...] | OperatorResult:
    """Return the reviewed state concepts every state filter binds, in stable order."""

    concepts: list[str] = []
    stated = [item for item in goal.filters if item.role is FilterRole.STATE]
    if stated and goal.subject is not None:
        # Reviewed states describe Resources; another ObjectType's lifecycle has no reader here.
        subject = ctx.mention(goal.subject)
        values, _failure = concept_values(goal.subject, ctx)
        if subject.domain is MentionDomain.OBJECT_TYPE and values != (RESOURCE_OBJECT_TYPE,):
            return OperatorResult(unsupported=("filter_unsupported:state",))
    for item in stated:
        if ctx.mention(item.mention).domain is not MentionDomain.STATE:
            return OperatorResult(unsupported=("state_filter_domain_unsupported",))
        values, failure = concept_values(item.mention, ctx)
        if failure is not None:
            return failure
        concepts.extend(values)
    if concepts and not function_declared(ctx, RESOURCE_STATE_FUNCTION_NAME):
        return OperatorResult(unsupported=(f"function_unavailable:{RESOURCE_STATE_FUNCTION_NAME}",))
    return tuple(sorted(set(concepts)))


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
                evidence_requirements=(
                    (IMPACT_POSSIBLE_ONLY,)
                    if goal.effective_operation is GoalOperation.IMPACT
                    else ()
                ),
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
        unions = union_tree(f"{goal.id}-union", [node.node_id for node in traversals])
        nodes.extend(unions)
        source = unions[-1].node_id
    count = count_node(f"{goal.id}-count", source, group)
    nodes.append(count)
    if len(nodes) > MAX_INTENT_GRAPH_GOALS:
        return OperatorResult(
            unsupported=("count_side_budget_exceeded",), limitations=tuple(limitations)
        )
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
    """Read what happened in a window: one anchor's operations or events, or the newest
    provider-observed change of every Resource when the subject is a collection."""

    # What changed, with no kind stated, ranges over Resources in general.
    if goal.subject is None and goal.subject_scope is not SubjectScope.COLLECTION:
        return OperatorResult(unsupported=("anchor_missing",))
    if goal.filters:
        return OperatorResult(unsupported=("filter_unsupported_for_operation:history",))
    kind = goal.measure.kind if goal.measure is not None else MeasureKind.CHANGE
    window = _stated_window(goal, ctx)
    if isinstance(window, str):
        return OperatorResult(unsupported=(window,))
    seconds, limitation, requirement = window
    if goal.subject_scope is SubjectScope.COLLECTION:
        if kind is not MeasureKind.CHANGE:
            return OperatorResult(unsupported=(f"collection_history_unsupported:{kind.value}",))
        result = _recent_changes(goal, ctx, seconds, requirement)
    elif kind is MeasureKind.EVENT:
        maximum = declared_maximum(ctx, EVENT_HISTORY_FUNCTION, "lookback_seconds")
        if maximum is not None and seconds > maximum:
            return OperatorResult(unsupported=("event_window_unsupported",))
        result = _anchored_function(
            goal,
            ctx,
            function_name=EVENT_HISTORY_FUNCTION,
            arguments={"event_families": list(EVENT_FAMILIES), "lookback_seconds": seconds},
            output_shape=SemanticOutputShape.RESOURCE_EVENT_HISTORY,
            evidence_requirements=(requirement,),
        )
    else:
        result = _anchored_function(
            goal,
            ctx,
            function_name=CHANGE_ACTIVITY_FUNCTION,
            arguments={"lookback_seconds": seconds},
            output_shape=CHANGE_ACTIVITY_SHAPE,
            evidence_requirements=(requirement,),
        )
    # Every applied window is restated by the notice its frame requirement names.
    return OperatorResult(specs=result.specs, limitations=(limitation,)) if result.specs else result


def _recent_changes(
    goal: FormGoal, ctx: CompileContext, seconds: int, requirement: str
) -> OperatorResult:
    """Read the newest provider-observed change of each Resource in the window.

    The reader has no kind restriction, so only Resources in general are read; a stated
    kind is unsupported rather than silently widened. The reader's declared row bound
    applies, and a window with more changed Resources stays marked incomplete.
    """

    if goal.subject is not None:
        values, failure = concept_values(goal.subject, ctx)
        if failure is not None:
            return failure
        domain = ctx.mention(goal.subject).domain
        general = (domain in RESOURCE_TYPE_DOMAINS and not values) or (
            domain is MentionDomain.OBJECT_TYPE and values == (RESOURCE_OBJECT_TYPE,)
        )
        if not general:
            return OperatorResult(unsupported=("recent_change_kind_unsupported",))
    limit = declared_maximum(ctx, RECENT_CHANGES_FUNCTION, "limit")
    if limit is None:
        return OperatorResult(unsupported=(f"function_unavailable:{RECENT_CHANGES_FUNCTION}",))
    end = ctx.evaluation_time.astimezone(UTC)
    node = OntologyQueryNode(
        node_id=f"{goal.id}-changes",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {
                "function_name": RECENT_CHANGES_FUNCTION,
                "arguments": {
                    "start_at": (end - timedelta(seconds=seconds)).isoformat(),
                    "end_at": end.isoformat(),
                    "known_at": end.isoformat(),
                    "limit": limit,
                },
                "dependency_arguments": {},
            }
        ),
        output_kind="query.table",
    )
    spec = plan_spec(
        goal,
        (node,),
        (node.node_id,),
        ctx,
        subjects=(RESOURCE_OBJECT_TYPE,),
        output_shape=SemanticOutputShape.RESOURCE_CHANGES,
        evidence_requirements=(requirement,),
    )
    return OperatorResult(specs=(spec,))


def _cause_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    """Read causal context for one anchor: its current state and the operations before it.

    The current-state reader reports when a state was observed, not when it changed, so
    no recorded operation can be ranked as a cause. The answer states that the cause is
    not established and shows both verified reads.
    """

    if goal.want is not Want.CAUSE:
        return OperatorResult(unsupported=("cause_want_required",))
    if goal.subject is None or goal.subject_scope is not SubjectScope.ANCHOR:
        return OperatorResult(unsupported=("anchor_missing",))
    if goal.filters or (goal.relation is not None and not restated_relation(goal)):
        return OperatorResult(unsupported=("cause_context_atom_unsupported",))
    window = _stated_window(goal, ctx)
    if isinstance(window, str):
        return OperatorResult(unsupported=(window,))
    seconds, limitation, requirement = window
    for name in (CURRENT_STATE_FUNCTION, CHANGE_ACTIVITY_FUNCTION):
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
        # The state reader's declared fields lead the answer table, before its receipt fields.
        measure_concepts=declared_measures(ctx, CURRENT_STATE_FUNCTION),
        evidence_requirements=(CAUSE_NOT_ESTABLISHED, requirement),
    )
    return OperatorResult(specs=(spec,), limitations=("cause_not_established", limitation))


def _stated_window(goal: FormGoal, ctx: CompileContext) -> tuple[int, str, str] | str:
    """Return the trusted lookback, its limitation, and the notice requirement that states it."""

    lookback = history_lookback_seconds(goal, default_seconds=ctx.default_lookback_seconds)
    if isinstance(lookback, str):
        return lookback
    seconds, defaulted = lookback
    if defaulted:
        kind = "default"
    else:
        # One window read from words without digits is the model's reading, stated as such.
        kind = "model_judged" if goal.id in ctx.admission.judged_times else "applied"
    code = _WINDOW_LIMITATIONS[kind]
    return seconds, f"{code}:{seconds}", f"window.{kind}.{seconds}"


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
    output_shape: SemanticOutputShape | str,
    evidence_requirements: tuple[str, ...] = (),
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
                evidence_requirements=evidence_requirements,
            ),
        )
    )


__all__ = [
    "CAUSE_CONTEXT_SHAPE",
    "CAUSE_NOT_ESTABLISHED",
    "CHANGE_ACTIVITY_SHAPE",
    "EVENT_FAMILIES",
    "MAX_COUNT_SIDES",
    "MAX_LOOKBACK_SECONDS",
    "MAX_SIDES_PER_BATCH",
    "MIN_LOOKBACK_SECONDS",
    "compile_goal",
    "history_lookback_seconds",
]
