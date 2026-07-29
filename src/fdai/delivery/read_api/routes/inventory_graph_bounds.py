"""Pure bounded-neighborhood projection for in-memory inventory providers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.shared.providers.inventory import InventoryGraphViewNotFoundError

_MAX_EDGE_MULTIPLIER = 8
_MIN_EDGE_CAP = 64


def project_bounded_inventory_neighborhood(
    *,
    resources: Sequence[Mapping[str, Any]],
    links: Sequence[Mapping[str, Any]],
    root: str,
    depth: int,
    link_types: Sequence[str],
    limit: int,
) -> dict[str, Any]:
    """Select one deterministic bidirectional neighborhood from an in-memory graph."""
    by_id = {str(resource["id"]): resource for resource in resources}
    if root not in by_id:
        raise InventoryGraphViewNotFoundError(f"inventory resource not found: {root}")
    allowed_links = [link for link in links if str(link.get("type")) in link_types]
    adjacency: dict[str, set[str]] = defaultdict(set)
    for link in allowed_links:
        source = str(link["source"])
        target = str(link["target"])
        adjacency[source].add(target)
        adjacency[target].add(source)

    selected = {root}
    selected_order = [root]
    frontier = [root]
    truncated = False
    truncation_reasons: set[str] = set()
    for _ in range(depth):
        next_frontier: list[str] = []
        candidates = {
            resource_id: sorted(adjacency.get(resource_id, set()) - selected)
            for resource_id in sorted(frontier)
        }
        candidate_depth = max((len(neighbors) for neighbors in candidates.values()), default=0)
        for neighbor_index in range(candidate_depth):
            for resource_id in sorted(frontier):
                neighbors = candidates[resource_id]
                if neighbor_index >= len(neighbors):
                    continue
                neighbor = neighbors[neighbor_index]
                if neighbor in selected or neighbor not in by_id:
                    continue
                if len(selected_order) >= limit:
                    truncated = True
                    truncation_reasons.add("resource_limit")
                    continue
                selected.add(neighbor)
                selected_order.append(neighbor)
                next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    internal_links = sorted(
        (
            dict(link)
            for link in allowed_links
            if str(link["source"]) in selected and str(link["target"]) in selected
        ),
        key=lambda link: (str(link["source"]), str(link["type"]), str(link["target"])),
    )
    edge_cap = max(_MIN_EDGE_CAP, limit * _MAX_EDGE_MULTIPLIER)
    if len(internal_links) > edge_cap:
        truncated = True
        truncation_reasons.add("internal_edge_limit")
        internal_links = internal_links[:edge_cap]

    return {
        "resources": [dict(by_id[resource_id]) for resource_id in selected_order],
        "links": internal_links,
        "truncated": truncated,
        "truncation_reasons": sorted(truncation_reasons),
    }


__all__ = ["project_bounded_inventory_neighborhood"]
