"""Compile a relation anchored on every member of a kind (E12).

A question such as which VM each network interface is attached to relates every member of
one kind to another. The plan reads the anchor kind as one object set and walks one reviewed
LinkType side from every member with lineage rows, so each related pair names its anchor and
each anchor without a related member stays visible in the anchor table.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import OntologyQueryPlan, QueryNodeKind

from .semantic_reasoning_form import (
    FormGoal,
    GoalOperation,
    RelationAnchorScope,
    RelationReach,
    RelationScope,
)
from .semantic_reasoning_nodes import (
    COLLECTION_LIMIT,
    RESOURCE_OBJECT_TYPE,
    RESOURCE_TYPE_DOMAINS,
    CompileContext,
    OperatorResult,
    concept_values,
    object_set_node,
    plan_spec,
    readable,
    subject_selection,
    traversal_node,
)
from .semantic_reasoning_relations import RelationSide, select_relation_sides

ANCHORS_SUFFIX = "-anchors"
RELATED_SUFFIX = "-related"


def collection_anchored(goal: FormGoal) -> bool:
    return (
        goal.relation is not None and goal.relation.anchor_scope is RelationAnchorScope.COLLECTION
    )


def collection_relation_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    """Compile one sense and one hop from every member of the anchor kind."""

    relation = goal.relation
    if relation is None or relation.anchor is None:
        return OperatorResult(unsupported=("collection_anchor_kind_required",))
    if goal.effective_operation is not GoalOperation.SELECT:
        operation = goal.effective_operation.value
        return OperatorResult(unsupported=(f"collection_anchor_operation_unsupported:{operation}",))
    if relation.scope is not RelationScope.ONE_SENSE or relation.reach is not RelationReach.ONE_HOP:
        return OperatorResult(unsupported=("collection_anchor_reach_unsupported",))
    position = relation.anchor_position
    if position is None or not relation.roles_consistent:
        return OperatorResult(unsupported=("relation_role_mismatch",))
    anchor_predicates = _anchor_predicates(relation.anchor, ctx)
    if isinstance(anchor_predicates, OperatorResult):
        return anchor_predicates
    selector, predicates, failure = subject_selection(goal, ctx)
    if failure is not None:
        return failure
    if selector != RESOURCE_OBJECT_TYPE:
        return OperatorResult(unsupported=("collection_anchor_result_requires_resource",))
    selection = select_relation_sides(
        ctx.manifest.descriptors,
        anchor_type=RESOURCE_OBJECT_TYPE,
        sense=relation.sense,
        scope=RelationScope.ONE_SENSE,
        position=position,
        reach=RelationReach.ONE_HOP,
    )
    limitations = tuple(f"link_sense_unmapped:{name}" for name in selection.unmapped_link_types)
    sides = tuple(
        side
        for side in selection.sides
        if side.endpoint_type == RESOURCE_OBJECT_TYPE
        and readable(ctx, side.endpoint_type, predicates)
    )
    if len(sides) != 1:
        # One reviewed LinkType side keeps every pair attributable to one stored relation.
        reason = (
            f"relation_sense_unmapped:{relation.sense.value}"
            if not sides
            else "collection_anchor_sides_unsupported"
        )
        return OperatorResult(unsupported=(reason,), limitations=limitations)
    anchors = object_set_node(
        f"{goal.id}{ANCHORS_SUFFIX}",
        RESOURCE_OBJECT_TYPE,
        anchor_predicates,
        ctx,
        limit=COLLECTION_LIMIT,
    )
    related = traversal_node(
        f"{goal.id}{RELATED_SUFFIX}",
        anchors.node_id,
        sides[0],
        predicates,
        ctx,
        emit_lineage=True,
    )
    return OperatorResult(
        specs=(
            plan_spec(
                goal,
                (anchors, related),
                (anchors.node_id, related.node_id),
                ctx,
                subjects=(RESOURCE_OBJECT_TYPE,),
            ),
        ),
        limitations=limitations,
    )


def collection_anchor_types(goal: FormGoal, ctx: CompileContext) -> tuple[str, ...] | None:
    """Return the anchor kind's reviewed type values, from the goal alone."""

    relation = goal.relation
    if relation is None or relation.anchor is None:
        return None
    if ctx.mention(relation.anchor).domain not in RESOURCE_TYPE_DOMAINS:
        return None
    values, failure = concept_values(relation.anchor, ctx)
    if failure is not None or not values:
        return None
    return tuple(sorted(values))


def collection_anchor_violations(
    goal: FormGoal,
    plans: Sequence[OntologyQueryPlan],
    *,
    expected_types: tuple[str, ...] | None,
    expected_side: RelationSide | None,
) -> list[str]:
    """V-SEM: every traversal starts from exactly the anchor kind's object set."""

    if expected_types is None:
        return ["sem_collection_anchor_kind_missing"]
    violations: list[str] = []
    for plan in plans:
        by_id = {node.node_id: node for node in plan.nodes}
        traversals = [
            node for node in plan.nodes if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL
        ]
        if len(traversals) != 1 or traversals[0].arguments.get("emit_lineage") is not True:
            violations.append("sem_collection_anchor_lineage_missing")
            continue
        traversal = traversals[0]
        source = by_id.get(traversal.depends_on[0]) if traversal.depends_on else None
        definition: Mapping[str, Any] = (
            source.arguments.get("definition") or {}
            if source is not None and source.kind is QueryNodeKind.OBJECT_SET
            else {}
        )
        if _stated_types(definition.get("predicates") or ()) != expected_types:
            violations.append("sem_collection_anchor_differs")
        if source is None or source.node_id not in plan.output_node_ids:
            # Every anchor stays visible, so one without a related member is never dropped.
            violations.append("sem_collection_anchor_unlisted")
        if expected_side is not None and (
            traversal.arguments.get("link_types") != [expected_side.link_type]
            or traversal.arguments.get("direction") != expected_side.direction
            or traversal.arguments.get("max_depth") != 1
        ):
            violations.append("sem_relation_sides_differ")
    return violations


def _anchor_predicates(
    mention_id: str, ctx: CompileContext
) -> list[dict[str, Any]] | OperatorResult:
    if ctx.mention(mention_id).domain not in RESOURCE_TYPE_DOMAINS:
        return OperatorResult(unsupported=("collection_anchor_kind_required",))
    values, failure = concept_values(mention_id, ctx)
    if failure is not None:
        return failure
    if not values:
        return OperatorResult(unsupported=("collection_anchor_kind_required",))
    ordered = sorted(values)
    predicate: dict[str, Any] = (
        {"property": "type", "operator": "equals", "equals": ordered[0]}
        if len(ordered) == 1
        else {"property": "type", "operator": "in", "values": ordered}
    )
    if not readable(ctx, RESOURCE_OBJECT_TYPE, [predicate]):
        return OperatorResult(unsupported=("predicate_property_unreadable",))
    return [predicate]


def _stated_types(predicates: Sequence[Mapping[str, Any]]) -> tuple[str, ...] | None:
    for item in predicates:
        if item.get("property") != "type":
            continue
        if item.get("operator") == "equals":
            return (str(item.get("equals")),)
        if item.get("operator") == "in":
            return tuple(sorted(str(value) for value in item.get("values") or ()))
    return None


__all__ = [
    "collection_anchor_types",
    "collection_anchor_violations",
    "collection_anchored",
    "collection_relation_goal",
]
