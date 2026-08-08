"""Bounded rooted queries over the effective PostgreSQL inventory graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from fdai.shared.providers.inventory import InventoryGraphViewNotFoundError

_MAX_EDGE_MULTIPLIER: Final[int] = 8
_MIN_EDGE_CAP: Final[int] = 64

_EFFECTIVE_RESOURCES_CTE = (
    "WITH effective_resources AS ("
    "SELECT r.resource_id, r.resource_type, r.props, r.provider_ref, r.last_seen "
    "FROM inventory_snapshot_resource r WHERE r.snapshot_id=%s AND NOT EXISTS ("
    "SELECT 1 FROM inventory_realtime_resource d WHERE d.resource_id=r.resource_id) "
    "UNION ALL SELECT d.resource_id, d.resource_type, d.props, d.provider_ref, d.observed_at "
    "FROM inventory_realtime_resource d WHERE d.change_kind='upsert') "
)
_EFFECTIVE_LINKS_CTE = (
    "WITH effective_links AS ("
    "SELECT l.from_id, l.from_type, l.link_type, l.to_id, l.to_type, l.props "
    "FROM inventory_snapshot_link l WHERE l.snapshot_id=%s AND NOT EXISTS ("
    "SELECT 1 FROM inventory_realtime_link d WHERE d.from_id=l.from_id "
    "AND d.link_type=l.link_type AND d.to_id=l.to_id) "
    "UNION ALL SELECT d.from_id, d.from_type, d.link_type, d.to_id, d.to_type, d.props "
    "FROM inventory_realtime_link d WHERE d.change_kind='upsert') "
)
_SELECT_RESOURCES = (
    _EFFECTIVE_RESOURCES_CTE + "SELECT resource_id, resource_type, props, provider_ref, last_seen "
    "FROM effective_resources WHERE resource_id=ANY(%s::text[]) ORDER BY resource_id"
)
_SELECT_ADJACENT_LINKS = (
    _EFFECTIVE_LINKS_CTE  # noqa: S608 - static SQL fragments; all values are bound
    + ", incident_links AS ("
    "SELECT l.*, l.from_id AS frontier_id FROM effective_links l "
    "WHERE l.from_id=ANY(%s::text[]) AND NOT (l.to_id=ANY(%s::text[])) "
    "UNION ALL "
    "SELECT l.*, l.to_id AS frontier_id FROM effective_links l "
    "WHERE l.to_id=ANY(%s::text[]) AND NOT (l.from_id=ANY(%s::text[]))), "
    "ranked_links AS ("
    "SELECT from_id, from_type, link_type, to_id, to_type, props, frontier_id, "
    "ROW_NUMBER() OVER (PARTITION BY frontier_id ORDER BY LEAST(from_id, to_id), "
    "GREATEST(from_id, to_id), link_type, from_id, to_id) AS edge_rank "
    "FROM incident_links WHERE link_type=ANY(%s::text[])) "
    "SELECT from_id, from_type, link_type, to_id, to_type, props FROM ranked_links "
    "ORDER BY edge_rank, frontier_id, LEAST(from_id, to_id), GREATEST(from_id, to_id), "
    "link_type, from_id, to_id LIMIT %s"
)
_SELECT_INTERNAL_LINKS = (
    _EFFECTIVE_LINKS_CTE + "SELECT from_id, from_type, link_type, to_id, to_type, props "
    "FROM effective_links WHERE from_id=ANY(%s::text[]) AND to_id=ANY(%s::text[]) "
    "AND link_type=ANY(%s::text[]) ORDER BY from_id, link_type, to_id LIMIT %s"
)


@dataclass(frozen=True, slots=True)
class RootedInventoryGraph:
    resources: tuple[Mapping[str, Any], ...]
    links: tuple[Mapping[str, Any], ...]
    truncated: bool
    truncation_reasons: tuple[str, ...]


async def load_rooted_inventory_graph(
    connection: psycopg.AsyncConnection[Any],
    *,
    snapshot_id: str,
    root: str,
    depth: int,
    link_types: Sequence[str],
    limit: int,
) -> RootedInventoryGraph:
    """Return a deterministic, bidirectional neighborhood bounded by depth and rows."""
    root_rows = await _load_resources(connection, snapshot_id=snapshot_id, ids=(root,))
    if not root_rows:
        raise InventoryGraphViewNotFoundError(f"inventory resource not found: {root}")

    selected = {root}
    selected_order = [root]
    frontier = {root}
    truncated = False
    truncation_reasons: set[str] = set()
    edge_cap = max(_MIN_EDGE_CAP, limit * _MAX_EDGE_MULTIPLIER)

    for _ in range(depth):
        if not frontier:
            break
        cursor = await connection.execute(
            _SELECT_ADJACENT_LINKS,
            (
                snapshot_id,
                sorted(frontier),
                sorted(selected),
                sorted(frontier),
                sorted(selected),
                list(link_types),
                edge_cap + 1,
            ),
        )
        adjacent = await cursor.fetchall()
        if len(adjacent) > edge_cap:
            truncated = True
            truncation_reasons.add("adjacent_edge_limit")
            adjacent = adjacent[:edge_cap]
        next_frontier: set[str] = set()
        for link in adjacent:
            source = str(link["from_id"])
            target = str(link["to_id"])
            for endpoint in (source, target):
                if endpoint in selected:
                    continue
                if len(selected_order) >= limit:
                    truncated = True
                    truncation_reasons.add("resource_limit")
                    continue
                selected.add(endpoint)
                selected_order.append(endpoint)
                next_frontier.add(endpoint)
        frontier = next_frontier

    resources = await _load_resources(
        connection,
        snapshot_id=snapshot_id,
        ids=tuple(selected_order),
    )
    resources_by_id = {str(row["resource_id"]): row for row in resources}
    ordered_resources = tuple(
        resources_by_id[resource_id]
        for resource_id in selected_order
        if resource_id in resources_by_id
    )
    returned_ids = list(resources_by_id)
    link_cursor = await connection.execute(
        _SELECT_INTERNAL_LINKS,
        (
            snapshot_id,
            returned_ids,
            returned_ids,
            list(link_types),
            edge_cap + 1,
        ),
    )
    internal_links = await link_cursor.fetchall()
    if len(internal_links) > edge_cap:
        truncated = True
        truncation_reasons.add("internal_edge_limit")
        internal_links = internal_links[:edge_cap]
    return RootedInventoryGraph(
        resources=ordered_resources,
        links=tuple(internal_links),
        truncated=truncated,
        truncation_reasons=tuple(sorted(truncation_reasons)),
    )


async def _load_resources(
    connection: psycopg.AsyncConnection[Any],
    *,
    snapshot_id: str,
    ids: Sequence[str],
) -> tuple[Mapping[str, Any], ...]:
    cursor = await connection.execute(_SELECT_RESOURCES, (snapshot_id, list(ids)))
    return tuple(await cursor.fetchall())


__all__ = ["RootedInventoryGraph", "load_rooted_inventory_graph"]
