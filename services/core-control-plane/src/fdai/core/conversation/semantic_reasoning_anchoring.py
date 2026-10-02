"""Derive the anchored relation a goal reads, from closed form fields only.

The anchor's meaning-level role maps to a stored LinkType end through the
reviewed sense-role convention. When the relation names its anchor, a distinct
goal subject names the requested results and becomes the endpoint restriction.
"""

from __future__ import annotations

from dataclasses import dataclass

from .semantic_reasoning_admission import relation_reach
from .semantic_reasoning_form import (
    FormGoal,
    FormRelation,
    GoalOperation,
    MentionDomain,
    MentionForm,
    RelationReach,
    RelationScope,
    RelationSense,
    SubjectPosition,
    SubjectRole,
    SubjectScope,
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
    impact = goal.effective_operation is GoalOperation.IMPACT
    if impact and relation is not None and not _reviewed_impact(relation):
        # Impact has one reviewed reading; another stated relation is not substituted.
        return OperatorResult(unsupported=("impact_relation_unsupported",))
    if relation is None and not impact:
        return OperatorResult(unsupported=("relation_required",))
    if relation is not None and (relation.anchor_position is None or not relation.roles_consistent):
        return OperatorResult(unsupported=("relation_role_mismatch",))
    anchor = relation.anchor if relation is not None and relation.anchor else goal.subject
    if anchor is None or not _is_anchor(anchor, ctx):
        return OperatorResult(unsupported=("relation_anchor_missing",))
    restriction = _result_restriction(goal, anchor, ctx)
    if isinstance(restriction, OperatorResult):
        return restriction
    subject_types, endpoint_object_type = restriction
    if (
        relation is not None
        and goal.subject_scope is SubjectScope.COLLECTION
        and relation.sense is RelationSense.TRAFFIC
        and not subject_types
        and endpoint_object_type is None
    ):
        return OperatorResult(unsupported=("relation_collection_anchor_unsupported",))
    if relation is None or impact:
        return AnchoredRelation(
            anchor=anchor,
            position=SubjectPosition.TARGET,
            sense=RelationSense.DEPENDENCY,
            scope=RelationScope.ONE_SENSE,
            reach=RelationReach.ONE_HOP,
            subject_types=subject_types,
            endpoint_object_type=endpoint_object_type,
            implied=True,
        )
    position = relation.anchor_position
    if position is None:
        return OperatorResult(unsupported=("relation_role_mismatch",))
    if relation.scope is RelationScope.ALL_KINDS and relation.reach is RelationReach.TRANSITIVE:
        return OperatorResult(unsupported=("all_kinds_transitive_unsupported",))
    return AnchoredRelation(
        anchor=anchor,
        position=position,
        sense=relation.sense if relation.scope is RelationScope.ONE_SENSE else None,
        scope=relation.scope,
        reach=relation_reach(goal),
        subject_types=subject_types,
        endpoint_object_type=endpoint_object_type,
    )


def _reviewed_impact(relation: FormRelation) -> bool:
    return (
        relation.sense is RelationSense.DEPENDENCY
        and relation.scope is RelationScope.ONE_SENSE
        and relation.anchor_role is SubjectRole.DEPENDENCY
        and relation.result_role is SubjectRole.DEPENDENT
        and relation.reach is RelationReach.ONE_HOP
    )


def _result_restriction(
    goal: FormGoal, anchor: str, ctx: CompileContext
) -> tuple[tuple[str, ...], str | None] | OperatorResult:
    """Return the kind restriction a distinct goal subject places on the results."""

    results = goal.subject if goal.subject not in {None, anchor} else None
    if results is None or goal.restated_subject:
        return (), None
    domain = ctx.mention(results).domain
    if domain is MentionDomain.INSTANCE:
        # Rows an earlier answer showed restrict the results by identity, not by kind.
        if ctx.prior_rows(goal) is not None:
            return (), None
        return OperatorResult(unsupported=("result_instance_unsupported",))
    values, failure = concept_values(results, ctx)
    if failure is not None:
        return failure
    if domain in RESOURCE_TYPE_DOMAINS:
        return values, None
    if domain is MentionDomain.OBJECT_TYPE and len(values) == 1:
        return (), values[0]
    return OperatorResult(unsupported=(f"subject_unsupported:{domain.value}",))


def _is_anchor(mention_id: str | None, ctx: CompileContext) -> bool:
    if mention_id is None:
        return False
    mention = ctx.mention(mention_id)
    if mention.domain is not MentionDomain.INSTANCE:
        return False
    # A reference bound to one row of an earlier answer anchors like a name.
    return mention.form in _ANCHOR_FORMS or (
        mention.form in {MentionForm.ORDINAL, MentionForm.ANAPHOR}
        and ctx.anchors.binding(mention_id) is not None
    )


__all__ = ["AnchoredRelation", "anchored_relation"]
