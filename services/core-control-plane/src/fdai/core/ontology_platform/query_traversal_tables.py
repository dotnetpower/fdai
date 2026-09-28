"""Secured traversal tables and filtered endpoint receipts for ontology query plans."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace

from fdai.shared.ontology.acl import ProjectionRequest

from .models import ObjectSetDefinition, RelationshipTraversalDefinition
from .object_sets import object_matches_predicates
from .query_execution import QueryNodeHeldError
from .query_gateway import SecuredObjectSetQueryGateway, SecuredObjectSetQueryResult
from .query_values import QueryRow, QueryTable, relationship_endpoint_table

IssueResult = Callable[[SecuredObjectSetQueryResult], Awaitable[None]]


def secured_query_table(secured: SecuredObjectSetQueryResult) -> QueryTable:
    limitation = (
        secured.receipt.truncation_reason.value
        if secured.receipt.truncation_reason is not None
        else None
        if secured.receipt.complete
        else secured.materialization.graph.source_incomplete_reason or "source_incomplete"
    )
    return QueryTable(
        rows=tuple(
            QueryRow.from_values(
                record.id,
                {
                    "id": record.id,
                    "object_type": record.object_type,
                    "properties": record.properties,
                },
            )
            for record in secured.materialization.graph.objects
        ),
        complete=secured.receipt.complete,
        truncation_reason=limitation,
        source_generation=secured.receipt.source_generation,
    )


def relationship_traversal_table(
    secured: SecuredObjectSetQueryResult,
    *,
    root_ids: tuple[str, ...],
    link_type: str,
    direction: str,
    max_depth: int = 1,
) -> QueryTable:
    """Return only endpoints reached from the dependency roots."""

    return relationship_endpoint_table(
        secured_query_table(secured),
        secured.materialization.graph,
        root_ids=root_ids,
        link_type=link_type,
        direction=direction,
        max_depth=max_depth,
    )


async def traversal_endpoints(
    table: QueryTable,
    traversal: RelationshipTraversalDefinition,
    secured: SecuredObjectSetQueryResult,
    *,
    gateway: SecuredObjectSetQueryGateway,
    request: ProjectionRequest,
    issue: IssueResult | None,
) -> tuple[QueryTable, tuple[str, ...]]:
    """Return reached endpoints and the output marker a consumer may read.

    Endpoint predicates filter only reached endpoints, so a transitive path through a
    filtered intermediate stays intact. A filtered table is re-read by exact identity
    and issued its own receipt; an incomplete filtered table carries no output marker,
    so a downstream ``query_result`` consumer fails closed instead of reading the
    unfiltered set.
    """

    if not traversal.endpoint_predicates:
        return table, (f"ontology-object-set-output:{secured.receipt.projected_result_digest}",)
    filtered = replace(
        table,
        rows=tuple(
            row
            for row in table.rows
            if object_matches_predicates(_row_properties(row), traversal.endpoint_predicates)
        ),
    )
    if issue is None or not filtered.complete:
        return filtered, ()
    endpoint_ids = tuple(row.row_id for row in filtered.rows)
    output = await gateway.materialize(
        ObjectSetDefinition(
            selector=traversal.selector,
            object_ids=endpoint_ids,
            as_of=traversal.as_of,
            purpose=traversal.purpose,
            limit=traversal.limit,
            include_relationships=False,
        ),
        projection_request=request,
    )
    if (
        filtered.source_generation is not None
        and output.receipt.source_generation != filtered.source_generation
    ):
        raise QueryNodeHeldError("query_source_generation_conflict")
    if not output.receipt.complete or {
        item.id for item in output.materialization.graph.objects
    } != set(endpoint_ids):
        raise QueryNodeHeldError("relationship_traversal_endpoint_projection_changed")
    await issue(output)
    return filtered, (f"ontology-object-set-output:{output.receipt.projected_result_digest}",)


def _row_properties(row: QueryRow) -> Mapping[str, object]:
    properties = row.values.get("properties")
    return properties if isinstance(properties, Mapping) else {}


__all__ = ["relationship_traversal_table", "secured_query_table", "traversal_endpoints"]
