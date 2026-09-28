"""Derive the anchored relation a goal reads, from closed form fields only.

The anchor's meaning-level role maps to a stored LinkType end through the
reviewed sense-role convention. When the relation names its anchor, a distinct
goal subject names the requested results and becomes the endpoint restriction.
"""

from __future__ import annotations

from dataclasses import dataclass

from .semantic_reasoning_form import (
    FormGoal,
    GoalOperation,
    MentionDomain,
    MentionForm,
    RelationReach,
    RelationScope,
    RelationSense,
    SubjectPosition,
)
from .semantic_reasoning_nodes import (
    RESOURCE_TYPE_DOMAINS,
    CompileContext,
    OperatorResult,
    concept_values,
)

_ANCHOR_FORMS = frozenset({MentionForm.IDENTIFIER, MentionForm.NAME})


@dataclass(frozen=True, slots=True)
class AnchoredRelation:
    anchor: str
    position: SubjectPosition
    sense: RelationSense | None
    scope: RelationScope
    reach: RelationReach
    subject_types: tuple[str, ...] = ()
    endpoint_object_type: str | None = None
    implied: bool = False


def anchored_relation(goal: FormGoal, ctx: CompileContext) -> AnchoredRelation | OperatorResult:
    """Return the anchor, its stored end, and endpoint restrictions for one goal."""

    relation = goal.relation
    if goal.effective_operation is GoalOperation.IMPACT:
        # Impact has one reviewed meaning: resources that depend on the anchor, one hop.
        # A model-stated relation cannot redirect it, so a reversed reading cannot compile.
        anchor = relation.anchor if relation is not None and relation.anchor else goal.subject
        if not _is_anchor(anchor, ctx) or anchor is None:
            return OperatorResult(unsupported=("relation_anchor_missing",))
        return AnchoredRelation(
            anchor=anchor,
            position=SubjectPosition.TARGET,
            sense=RelationSense.DEPENDENCY,
            scope=RelationScope.ONE_SENSE,
            reach=RelationReach.ONE_HOP,
            implied=True,
        )
    if relation is None:
        return OperatorResult(unsupported=("relation_required",))
    position = relation.anchor_position
    if position is None or not relation.roles_consistent:
        return OperatorResult(unsupported=("relation_role_mismatch",))
    anchor = relation.anchor or goal.subject
    if not _is_anchor(anchor, ctx) or anchor is None:
        return OperatorResult(unsupported=("relation_anchor_missing",))
    sense = relation.sense if relation.scope is RelationScope.ONE_SENSE else None
    subject_types: tuple[str, ...] = ()
    endpoint_object_type: str | None = None
    results = goal.subject if goal.subject not in {None, anchor} else None
    if results is not None and not goal.restated_subject:
        domain = ctx.mention(results).domain
        values, failure = concept_values(results, ctx)
        if failure is not None:
            return failure
        if domain in RESOURCE_TYPE_DOMAINS:
            subject_types = values
        elif domain is MentionDomain.OBJECT_TYPE and len(values) == 1:
            endpoint_object_type = values[0]
        else:
            return OperatorResult(unsupported=(f"subject_unsupported:{domain.value}",))
    return AnchoredRelation(
        anchor=anchor,
        position=position,
        sense=sense,
        scope=relation.scope,
        reach=relation.reach,
        subject_types=subject_types,
        endpoint_object_type=endpoint_object_type,
    )


def _is_anchor(mention_id: str | None, ctx: CompileContext) -> bool:
    if mention_id is None:
        return False
    mention = ctx.mention(mention_id)
    return mention.domain is MentionDomain.INSTANCE and mention.form in _ANCHOR_FORMS


__all__ = ["AnchoredRelation", "anchored_relation"]
