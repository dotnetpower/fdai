"""Content-free shape of one question form for development decision traces.

The shape names each mention and goal only by its form-local id and closed values, so a
trace shows how a question was read, such as a kind stated as a qualifier or a count that
cites a measure mention, without any quoted text or bound identity.
"""

from __future__ import annotations

from .semantic_reasoning_form import (
    FilterRole,
    GoalLevel,
    GoalOperation,
    GroupBy,
    MeasureKind,
    RelationAnchorScope,
    RelationReach,
    RelationScope,
    RelationSense,
    SemanticQuestionForm,
    SubjectRole,
    SubjectScope,
    TimeKind,
    Want,
)

MAX_SHAPE_TOKENS = 24
LIST_READING = "reading:list"
BEYOND_LIST_READING = "reading:beyond_list"
_LIST_FILTERS = frozenset({FilterRole.TYPE, FilterRole.NAME_FRAGMENT, FilterRole.SCOPE})
_LIST_TIMES = frozenset({TimeKind.CURRENT, TimeKind.UNSPECIFIED})


def reads_beyond_list(form: SemanticQuestionForm) -> bool:
    """Return whether a reading asks more than one filtered Resource list answers.

    Such a list reads a kind, a name part, and a containing scope, and its row count
    answers an ungrouped count. A state, region, grouping, relation, time, schema level,
    second goal, or competing reading asks for something that list never reads.
    """

    if (
        len(form.goals) != 1
        or form.alternatives
        or form.unsupported_constraints
        or form.remaining_goals
    ):
        return True
    goal = form.goals[0]
    if (
        goal.level is not GoalLevel.INSTANCE
        or goal.subject_scope is not SubjectScope.COLLECTION
        or goal.effective_operation not in {GoalOperation.SELECT, GoalOperation.COUNT}
        or goal.time.kind not in _LIST_TIMES
        or goal.want is not Want.FACT
        or any(item.role not in _LIST_FILTERS for item in goal.filters)
    ):
        return True
    measure = goal.measure
    if measure is not None and (
        measure.kind is not MeasureKind.COUNT or measure.group_by is not GroupBy.NONE
    ):
        return True
    relation = goal.relation
    if relation is not None and relation.anchor_scope is RelationAnchorScope.COLLECTION:
        # Each anchor's own related members are a pairing, never one flat list.
        return True
    # A containment read from a named container to its members only restates a scope.
    return relation is not None and not (
        relation.sense is RelationSense.CONTAINMENT
        and relation.scope is RelationScope.ONE_SENSE
        and relation.reach is RelationReach.ONE_HOP
        and relation.anchor_role is SubjectRole.CONTAINER
        and relation.result_role is SubjectRole.MEMBER
    )


def form_shape(form: SemanticQuestionForm) -> tuple[str, ...]:
    """Return closed tokens describing the mentions and goals of one form.

    The first token states whether the reading asks more than one filtered list, so a
    bounded shape never truncates it.
    """

    tokens: list[str] = [BEYOND_LIST_READING if reads_beyond_list(form) else LIST_READING]
    for mention in form.mentions:
        tokens.append(f"{mention.id}:{mention.domain.value}:{mention.form.value}")
        if mention.qualifier is not None:
            qualifier = mention.qualifier
            tokens.append(f"qualifier:{mention.id}:{qualifier.mention}:{qualifier.sense.value}")
    for goal in form.goals:
        operation = goal.operation.value
        tokens.append(f"{goal.id}:{goal.level.value}:{operation}:{goal.subject_scope.value}")
        if goal.subject is not None:
            tokens.append(f"subject:{goal.id}:{goal.subject}")
        tokens.extend(f"filter:{goal.id}:{item.role.value}:{item.mention}" for item in goal.filters)
        if goal.measure is not None:
            measure = goal.measure
            tokens.append(f"measure:{goal.id}:{measure.kind.value}:{measure.group_by.value}")
            if measure.mention is not None:
                tokens.append(f"measure_mention:{goal.id}:{measure.mention}")
        if goal.relation is not None:
            relation = goal.relation
            tokens.append(f"relation:{goal.id}:{relation.sense.value}:{relation.scope.value}")
            tokens.append(
                f"roles:{goal.id}:{relation.anchor_role.value}:{relation.result_role.value}"
            )
            if relation.anchor is not None:
                tokens.append(f"anchor:{goal.id}:{relation.anchor}")
        if goal.time.kind is not TimeKind.CURRENT:
            tokens.append(f"time:{goal.id}:{goal.time.kind.value}")
    if form.alternatives:
        tokens.append(f"alternatives:{len(form.alternatives)}")
    if form.unsupported_constraints:
        tokens.append(f"unsupported_constraints:{len(form.unsupported_constraints)}")
    return tuple(tokens[:MAX_SHAPE_TOKENS])


__all__ = [
    "BEYOND_LIST_READING",
    "LIST_READING",
    "MAX_SHAPE_TOKENS",
    "form_shape",
    "reads_beyond_list",
]
