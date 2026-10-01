"""Compile and verify nearest-container lineage count reads."""

from __future__ import annotations

from collections.abc import Sequence

from fdai_service_contracts.ontology_query import OntologyQueryPlan, QueryNodeKind

from .semantic_reasoning_form import FormGoal
from .semantic_reasoning_nodes import (
    COLLECTION_LIMIT,
    RESOURCE_OBJECT_TYPE,
    CompileContext,
    OperatorResult,
    containment_side,
    count_node,
    object_set_node,
    plan_spec,
    readable,
    traversal_node,
)


def lineage_count_goal(
    goal: FormGoal,
    ctx: CompileContext,
    selector: str,
    predicates: list[dict[str, object]],
    group: list[str],
) -> OperatorResult:
    """Compile a per-container count over lineage rows."""

    if selector != RESOURCE_OBJECT_TYPE:
        return OperatorResult(unsupported=("lineage_group_requires_resource_members",))
    side = containment_side(ctx)
    if side is None or side.endpoint_type != RESOURCE_OBJECT_TYPE:
        return OperatorResult(unsupported=("lineage_containment_unavailable",))
    container_kind = group[0].split(":", 1)[1]
    container_predicates = (
        []
        if container_kind == RESOURCE_OBJECT_TYPE
        else [{"property": "type", "operator": "equals", "equals": container_kind}]
    )
    if not readable(ctx, RESOURCE_OBJECT_TYPE, container_predicates):
        return OperatorResult(unsupported=("lineage_container_kind_unreadable",))
    prefix = goal.id
    containers = object_set_node(
        f"{prefix}-containers",
        RESOURCE_OBJECT_TYPE,
        container_predicates,
        ctx,
        limit=COLLECTION_LIMIT,
    )
    lineage = traversal_node(
        f"{prefix}-lineage",
        containers.node_id,
        side,
        predicates,
        ctx,
        emit_lineage=True,
    )
    count = count_node(f"{prefix}-count", lineage.node_id, group)
    return OperatorResult(
        specs=(
            plan_spec(
                goal,
                (containers, lineage, count),
                (count.node_id,),
                ctx,
                subjects=(RESOURCE_OBJECT_TYPE,),
            ),
        )
    )


def lineage_traversal_violations(
    *, lineage_group: bool, plans: Sequence[OntologyQueryPlan]
) -> tuple[str, ...]:
    """Return a V-SEM violation when a named container count lacks lineage rows."""

    if not lineage_group:
        return ()
    if any(
        node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL
        and node.arguments.get("emit_lineage") is True
        for plan in plans
        for node in plan.nodes
    ):
        return ()
    return ("sem_lineage_traversal_missing",)


__all__ = ["lineage_count_goal", "lineage_traversal_violations"]
