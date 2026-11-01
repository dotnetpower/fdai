"""Filters that only restate the Resource a lookup already names.

A lookup reads one named Resource. The kind word beside its name and the state its measure
asks about narrow nothing, so a plan needs no restriction for them. The kind must still
match the Resource the name bound to, which the compiler checks before it plans the read.
"""

from __future__ import annotations

from .semantic_reasoning_form import (
    FilterRole,
    FormFilter,
    FormGoal,
    GoalOperation,
    MeasureKind,
)
from .semantic_reasoning_nodes import (
    RESOURCE_TYPE_DOMAINS,
    CompileContext,
    OperatorResult,
    concept_values,
)

_UNSUPPORTED = "filter_unsupported_for_operation:lookup"


def restates_lookup_subject(goal: FormGoal, item: FormFilter) -> bool:
    """Return whether ``item`` only restates the named Resource of a lookup goal."""

    if goal.effective_operation is not GoalOperation.LOOKUP:
        return False
    if item.role is FilterRole.TYPE:
        return True
    measure = goal.measure
    return (
        item.role is FilterRole.STATE
        and measure is not None
        and measure.kind is MeasureKind.STATE
        and measure.mention is not None
        and item.mention == measure.mention
    )


def lookup_filter_failure(goal: FormGoal, ctx: CompileContext) -> OperatorResult | None:
    """Return the reason a lookup's filters cannot be accepted, or none when they all restate."""

    anchor = ctx.anchors.binding(goal.subject) if goal.subject is not None else None
    for item in goal.filters:
        if not restates_lookup_subject(goal, item):
            return OperatorResult(unsupported=(_UNSUPPORTED,))
        if item.role is not FilterRole.TYPE:
            continue
        values, failure = concept_values(item.mention, ctx)
        if failure is not None:
            return failure
        if ctx.mention(item.mention).domain not in RESOURCE_TYPE_DOMAINS or not values:
            return OperatorResult(unsupported=(_UNSUPPORTED,))
        if anchor is None or anchor.resource_type is None or not anchor.resource_type.strip():
            return OperatorResult(unsupported=("lookup_type_unverified",))
        if anchor.resource_type.strip() not in values:
            return OperatorResult(clarify=("anchor_type_mismatch",))
    return None
