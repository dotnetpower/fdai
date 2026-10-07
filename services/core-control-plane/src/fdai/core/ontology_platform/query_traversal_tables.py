"""Secured traversal tables and filtered endpoint receipts for ontology query plans."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace

from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .models import ObjectPredicate, ObjectSetDefinition, RelationshipTraversalDefinition
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
        total_rows=secured.receipt.population_count,
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


def relationship_lineage_table(
    secured: SecuredObjectSetQueryResult,
    *,
    root_ids: tuple[str, ...],
    link_type: str,
    direction: str,
    max_depth: int = 1,
    endpoint_predicates: tuple[ObjectPredicate, ...] = (),
) -> QueryTable:
    """Return lineage candidates reached from every root through one LinkType."""

    graph = secured.materialization.graph
    if secured.receipt.source_generation is None:
        raise QueryNodeHeldError("relationship_traversal_source_generation_missing")
    records = {record.id: record for record in graph.objects}
    rows: dict[tuple[str, str], tuple[int, tuple[str, ...]]] = {}
    for root_id in root_ids:
        frontier: dict[str, tuple[str, ...]] = {root_id: (root_id,)}
        reached: set[str] = {root_id}
        for depth in range(1, max_depth + 1):
            next_frontier: dict[str, tuple[str, ...]] = {}
            for link in graph.links:
                if link.link_type != link_type:
                    continue
                if direction in {"outgoing", "both"} and link.from_id in frontier:
                    _add_path(next_frontier, link.to_id, (*frontier[link.from_id], link.to_id))
                if direction in {"incoming", "both"} and link.to_id in frontier:
                    _add_path(next_frontier, link.from_id, (*frontier[link.to_id], link.from_id))
            frontier = {
                member_id: path
                for member_id, path in next_frontier.items()
                if member_id not in reached
            }
            reached.update(frontier)
            for member_id, path in sorted(frontier.items()):
                record = records.get(member_id)
                if record is None or not object_matches_predicates(
                    record.properties, endpoint_predicates
                ):
                    continue
                key = (member_id, root_id)
                current = rows.get(key)
                if current is None or (depth, path) < current:
                    rows[key] = (depth, path)
            if not frontier:
                break
    return replace(
        secured_query_table(secured),
        rows=tuple(
            QueryRow.from_values(
                f"lineage:{root_id}:{member_id}",
                {
                    "member_id": member_id,
                    "root_id": root_id,
                    # Projected display names, so each pair reads without its identifiers.
                    "member_name": _display_name(records.get(member_id)),
                    "root_name": _display_name(records.get(root_id)),
                    "depth": depth,
                    "path_evidence": json.dumps(
                        list(path),
                        allow_nan=False,
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ),
                    "source_generation": secured.receipt.source_generation,
                },
            )
            for (member_id, root_id), (depth, path) in sorted(rows.items())
        ),
    )


def _display_name(record: OntologyObjectRecord | None) -> str | None:
    name = record.properties.get("name") if record is not None else None
    return name if isinstance(name, str) and name else None


def _add_path(paths: dict[str, tuple[str, ...]], member_id: str, path: tuple[str, ...]) -> None:
    current = paths.get(member_id)
    if current is None or path < current:
        paths[member_id] = path


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
    filtered intermediate stays intact. The gateway re-reads every reached endpoint by
    exact identity under the same predicates, so its receipt observes the traversal's
    store generation even when the filter keeps nothing, and the result is issued its
    own receipt. An incomplete filtered table carries no output marker, so a downstream
    ``query_result`` consumer fails closed instead of reading the unfiltered set.
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
    reached_ids = tuple(row.row_id for row in table.rows)
    endpoint_ids = tuple(row.row_id for row in filtered.rows)
    output = await gateway.materialize(
        ObjectSetDefinition(
            selector=traversal.selector,
            object_ids=reached_ids,
            predicates=traversal.endpoint_predicates,
            as_of=traversal.as_of,
            purpose=traversal.purpose,
            limit=traversal.limit,
            include_relationships=False,
        ),
        projection_request=request,
    )
    # Only a traversal that reached nothing reads no snapshot; its empty result cannot drift.
    if reached_ids and output.receipt.source_generation != filtered.source_generation:
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


__all__ = [
    "relationship_lineage_table",
    "relationship_traversal_table",
    "secured_query_table",
    "traversal_endpoints",
]
