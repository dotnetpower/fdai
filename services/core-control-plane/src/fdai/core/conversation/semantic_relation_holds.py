"""Fail-closed guards for relation answer execution."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import QueryNodeKind

from fdai.core.conversation.semantic_planning_models import SemanticPlanningOutcome
from fdai.core.ontology_platform.query_execution import QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryTable


def relation_output_empty(
    planning: SemanticPlanningOutcome,
    execution: QueryPlanExecution,
) -> bool:
    """Return whether a relation traversal completed with no independently confirmed rows."""

    plan = planning.plan
    if plan is None or not any(
        node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL for node in plan.nodes
    ):
        return False
    return any(
        isinstance(result.value, QueryTable) and result.value.complete and not result.value.rows
        for node_id in plan.output_node_ids
        if (result := execution.results.get(node_id)) is not None
    )


__all__ = ["relation_output_empty"]
