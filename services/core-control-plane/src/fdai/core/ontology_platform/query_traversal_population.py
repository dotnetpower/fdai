"""Exact populations behind a relationship traversal cut at its result limit (P2).

A scoped collection, such as the VMs in one resource group, is the deduplicated set of
endpoints a traversal reaches, excluding its roots. When the page read stops at its limit,
the population is read again one hop at a time from frontier batches, each a secured read
of the same source generation, and counted under the same projection and endpoint
predicates as the page. Any cut, hidden, changed, or over-budget read states no count.
"""

from __future__ import annotations

from collections.abc import Sequence

from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.ontology_instance import MAX_ONTOLOGY_OBJECT_SCAN

from .models import ObjectSetDefinition, ObjectTraversal, RelationshipTraversalDefinition
from .object_sets import object_matches_predicates
from .query_gateway import SecuredObjectSetQueryGateway

# Frontier members per hop read, and the reads one population may spend.
POPULATION_FRONTIER_BATCH = 32
POPULATION_READ_BUDGET = 64


async def traversal_population_count(
    gateway: SecuredObjectSetQueryGateway,
    traversal: RelationshipTraversalDefinition,
    *,
    root_ids: Sequence[str],
    request: ProjectionRequest,
    expected_generation: str | None,
) -> int | None:
    """Return how many reached endpoints match the traversal, or ``None`` if not exact."""

    roots = sorted(set(root_ids))
    visited = set(roots)
    frontier = list(roots)
    matched: set[str] = set()
    reads = 0
    for _depth in range(traversal.max_depth):
        reached: dict[str, bool] = {}
        pending = [
            frontier[start : start + POPULATION_FRONTIER_BATCH]
            for start in range(0, len(frontier), POPULATION_FRONTIER_BATCH)
        ]
        while pending:
            batch = pending.pop(0)
            reads += 1
            if reads > POPULATION_READ_BUDGET:
                return None
            hop = await _hop(gateway, traversal, batch, request, expected_generation)
            if hop is None:
                return None
            if isinstance(hop, str):
                if len(batch) == 1:
                    return None
                middle = len(batch) // 2
                pending[:0] = [batch[:middle], batch[middle:]]
                continue
            for member_id, matches in hop.items():
                reached[member_id] = reached.get(member_id, False) or matches
        new = sorted(set(reached) - visited)
        visited.update(new)
        matched.update(member_id for member_id in new if reached[member_id])
        if len(visited) > MAX_ONTOLOGY_OBJECT_SCAN:
            return None
        frontier = new
        if not frontier:
            break
    return len(matched)


async def _hop(
    gateway: SecuredObjectSetQueryGateway,
    traversal: RelationshipTraversalDefinition,
    batch: list[str],
    request: ProjectionRequest,
    expected_generation: str | None,
) -> dict[str, bool] | str | None:
    """Return each endpoint one hop from ``batch`` and whether it matches, or a stop."""

    definition = ObjectSetDefinition(
        selector=traversal.selector,
        traversal=ObjectTraversal(
            link_types=traversal.link_types, direction=traversal.direction, max_depth=1
        ),
        root_ids=tuple(batch),
        as_of=traversal.as_of,
        purpose=traversal.purpose,
        limit=1000,
    )
    try:
        secured = await gateway.materialize(definition, projection_request=request)
    except (PermissionError, ValueError):
        return None
    receipt = secured.receipt
    if (
        not receipt.source_complete
        or receipt.source_generation != expected_generation
        or receipt.redactions.redacted_identity_count
    ):
        return None
    if receipt.truncated:
        return "cut"
    graph = secured.materialization.graph
    records = {record.id: record for record in graph.objects}
    sources = set(batch)
    endpoints: dict[str, bool] = {}
    link_type = traversal.link_types[0]
    for link in graph.links:
        if link.link_type != link_type:
            continue
        candidates = []
        if traversal.direction in {"outgoing", "both"} and link.from_id in sources:
            candidates.append(link.to_id)
        if traversal.direction in {"incoming", "both"} and link.to_id in sources:
            candidates.append(link.from_id)
        for member_id in candidates:
            record = records.get(member_id)
            if record is None:
                # A reached endpoint the projection does not return cannot be counted.
                return None
            endpoints[member_id] = record.object_type == traversal.selector.name and (
                object_matches_predicates(record.properties, traversal.endpoint_predicates)
            )
    return endpoints


__all__ = [
    "POPULATION_FRONTIER_BATCH",
    "POPULATION_READ_BUDGET",
    "traversal_population_count",
]
