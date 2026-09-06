"""PostgreSQL query helpers for the runtime ontology instance graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg import sql

from fdai.delivery.persistence.postgres_ontology_records import (
    _link_from_row,
    _next_endpoint,
    _object_from_row,
)
from fdai.delivery.persistence.postgres_ontology_source_coverage import (
    resource_graph_source_coverage,
)
from fdai.shared.contracts.models import OntologyLinkType, OntologyRelease
from fdai.shared.providers.ontology_instance import (
    OntologyDirection,
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
    can_repeat_link,
    canonical_json_mapping,
    normalize_json_value,
    ontology_link_sort_key,
)


async def _query_objects(
    connection: psycopg.AsyncConnection[Any],
    *,
    releases: Mapping[str, OntologyRelease],
    link_types: Mapping[str, OntologyLinkType],
    object_types: Sequence[str],
    object_ids: Sequence[str],
    property_equals: Mapping[str, Any] | None,
    limit: int,
    include_relationships: bool,
) -> OntologyGraphSnapshot:
    clauses: list[str] = []
    params: list[Any] = []
    if object_types:
        clauses.append("object_type = ANY(%s::text[])")
        params.append(list(object_types))
    if object_ids:
        clauses.append("id = ANY(%s::text[])")
        params.append(list(object_ids))
    if property_equals:
        normalized = normalize_json_value(property_equals, path="property_equals")
        params.append(canonical_json_mapping(normalized, path="property_equals")[1])
        clauses.append("properties @> %s::jsonb")
    where: sql.Composable
    if clauses:
        where = sql.SQL("WHERE ") + sql.SQL(" AND ").join(map(sql.SQL, clauses))
    else:
        where = sql.SQL("")
    params.append(limit + 1)
    cursor = await connection.execute(
        sql.SQL(
            "SELECT id, object_type, properties, revision, type_version, catalog_digest "
            "FROM ontology_resource {} ORDER BY id LIMIT %s"
        ).format(where),
        tuple(params),
    )
    rows = await cursor.fetchall()
    truncated = len(rows) > limit
    objects = tuple(_object_from_row(row, releases=releases) for row in rows[:limit])
    objects_by_id = {item.id: item for item in objects}
    raw_links = (
        await _links_within(connection, tuple(objects_by_id), releases=releases)
        if include_relationships
        else ()
    )
    links = tuple(
        sorted(
            raw_links,
            key=lambda link: ontology_link_sort_key(
                link,
                link_types=link_types,
                objects=objects_by_id,
            ),
        )
    )
    source_complete, source_generation = await resource_graph_source_coverage(
        connection,
        objects,
        requires_resource_coverage="Resource" in object_types,
        expresses_relationships=include_relationships and (bool(links) or len(objects) > 1),
    )
    return OntologyGraphSnapshot(
        objects=objects,
        links=links,
        truncated=truncated,
        source_complete=source_complete,
        source_generation=source_generation,
    )


async def _traverse(
    connection: psycopg.AsyncConnection[Any],
    *,
    releases: Mapping[str, OntologyRelease],
    declared_link_types: Mapping[str, OntologyLinkType],
    root_ids: Sequence[str],
    root_object_types: Sequence[str],
    link_types: Sequence[str],
    direction: OntologyDirection,
    max_depth: int,
    limit: int,
    initially_truncated: bool = False,
) -> OntologyGraphSnapshot:
    roots = await _load_objects(connection, identifiers=tuple(root_ids), releases=releases)
    allowed_root_types = set(root_object_types)
    ordered_root_ids = tuple(
        dict.fromkeys(
            root_id
            for root_id in root_ids
            if root_id in roots
            and (not allowed_root_types or roots[root_id].object_type in allowed_root_types)
        )
    )
    allowed_root_ids = ordered_root_ids[:limit]
    visited = set(allowed_root_ids)
    frontier: set[tuple[str, str | None]] = {(root_id, None) for root_id in allowed_root_ids}
    expanded: set[tuple[str, str | None]] = set()
    selected_links: dict[tuple[str, str, str], OntologyLinkRecord] = {}
    truncated = initially_truncated or len(ordered_root_ids) > limit
    for _ in range(max_depth):
        states = frontier - expanded
        if not states:
            break
        expanded.update(states)
        frontier_ids = {object_id for object_id, _ in states}
        edges = await _adjacent_links(
            connection,
            frontier=frontier_ids,
            link_types=link_types,
            direction=direction,
            limit=limit + 1,
            releases=releases,
        )
        next_states: set[tuple[str, str]] = set()
        for object_id, previous_link_type in sorted(states):
            for edge in edges:
                next_id = _next_endpoint(edge, object_id=object_id, direction=direction)
                if next_id is None:
                    continue
                declaration = declared_link_types[edge.link_type]
                if not can_repeat_link(previous_link_type, declaration):
                    continue
                selected_links[(edge.from_id, edge.link_type, edge.to_id)] = edge
                next_states.add((next_id, edge.link_type))
        room = limit - len(visited)
        new_ids = sorted({object_id for object_id, _ in next_states} - visited)
        allowed_new_ids = set(new_ids[:room])
        if len(new_ids) > room:
            truncated = True
        visited.update(allowed_new_ids)
        frontier = {
            state for state in next_states if state[0] in visited or state[0] in allowed_new_ids
        }
        if len(edges) > limit or truncated:
            truncated = True
            break
    objects_by_id = await _load_objects(
        connection,
        identifiers=tuple(sorted(visited)),
        releases=releases,
    )
    source_complete, source_generation = await resource_graph_source_coverage(
        connection,
        tuple(objects_by_id.values()),
        requires_resource_coverage="Resource" in root_object_types,
    )
    links = tuple(
        sorted(
            (
                edge
                for edge in selected_links.values()
                if edge.from_id in objects_by_id and edge.to_id in objects_by_id
            ),
            key=lambda link: ontology_link_sort_key(
                link,
                link_types=declared_link_types,
                objects=objects_by_id,
            ),
        )
    )
    return OntologyGraphSnapshot(
        objects=tuple(objects_by_id[key] for key in sorted(objects_by_id)),
        links=links,
        truncated=truncated,
        source_complete=source_complete,
        source_generation=source_generation,
    )


async def _load_objects(
    connection: psycopg.AsyncConnection[Any],
    *,
    identifiers: Sequence[str],
    releases: Mapping[str, OntologyRelease],
) -> dict[str, OntologyObjectRecord]:
    if not identifiers:
        return {}
    cursor = await connection.execute(
        "SELECT id, object_type, properties, revision, type_version, catalog_digest "
        "FROM ontology_resource WHERE id = ANY(%s::text[]) ORDER BY id",
        (list(identifiers),),
    )
    return {
        str(row["id"]): _object_from_row(row, releases=releases) for row in await cursor.fetchall()
    }


async def _links_within(
    connection: psycopg.AsyncConnection[Any],
    identifiers: Sequence[str],
    *,
    releases: Mapping[str, OntologyRelease],
) -> tuple[OntologyLinkRecord, ...]:
    if not identifiers:
        return ()
    cursor = await connection.execute(
        "SELECT link_type, from_id, to_id, properties, type_version, catalog_digest "
        "FROM ontology_link "
        "WHERE from_id = ANY(%s::text[]) AND to_id = ANY(%s::text[]) "
        "ORDER BY from_id, link_type, to_id",
        (list(identifiers), list(identifiers)),
    )
    return tuple(_link_from_row(row, releases=releases) for row in await cursor.fetchall())


async def _cardinality_links(
    connection: psycopg.AsyncConnection[Any],
    record: OntologyLinkRecord,
    *,
    releases: Mapping[str, OntologyRelease],
) -> tuple[OntologyLinkRecord, ...]:
    cursor = await connection.execute(
        "SELECT link_type, from_id, to_id, properties, type_version, catalog_digest "
        "FROM ontology_link "
        "WHERE link_type = %s AND (from_id = %s OR to_id = %s) "
        "ORDER BY from_id, to_id",
        (record.link_type, record.from_id, record.to_id),
    )
    return tuple(_link_from_row(row, releases=releases) for row in await cursor.fetchall())


async def _adjacent_links(
    connection: psycopg.AsyncConnection[Any],
    *,
    frontier: set[str],
    link_types: Sequence[str],
    direction: OntologyDirection,
    limit: int,
    releases: Mapping[str, OntologyRelease],
) -> tuple[OntologyLinkRecord, ...]:
    direction_clause = {
        "outgoing": sql.SQL("from_id = ANY(%s::text[])"),
        "incoming": sql.SQL("to_id = ANY(%s::text[])"),
        "both": sql.SQL("(from_id = ANY(%s::text[]) OR to_id = ANY(%s::text[]))"),
    }[direction]
    params: list[Any] = [list(frontier)]
    if direction == "both":
        params.append(list(frontier))
    type_clause = sql.SQL("")
    if link_types:
        type_clause = sql.SQL(" AND link_type = ANY(%s::text[])")
        params.append(list(link_types))
    params.append(limit)
    cursor = await connection.execute(
        sql.SQL(
            "SELECT link_type, from_id, to_id, properties, type_version, catalog_digest "
            "FROM ontology_link "
            "WHERE {}{} ORDER BY from_id, link_type, to_id LIMIT %s"
        ).format(direction_clause, type_clause),
        tuple(params),
    )
    return tuple(_link_from_row(row, releases=releases) for row in await cursor.fetchall())


__all__ = [
    "_cardinality_links",
    "_load_objects",
    "_query_objects",
    "_traverse",
]
