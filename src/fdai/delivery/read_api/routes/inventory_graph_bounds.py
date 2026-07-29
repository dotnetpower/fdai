"""Pure bounded-neighborhood projection for in-memory inventory providers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.shared.providers.inventory import InventoryGraphViewNotFoundError


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
    adjacency: dict[str, list[str]] = defaultdict(list)
    for link in allowed_links:
        source = str(link["source"])
        target = str(link["target"])
        adjacency[source].append(target)
        adjacency[target].append(source)
    for neighbors in adjacency.values():
        neighbors.sort()

    selected = {root}
    selected_order = [root]
    frontier = [root]
    truncated = False
    for _ in range(depth):
        next_frontier: list[str] = []
        for resource_id in frontier:
            for neighbor in adjacency.get(resource_id, ()):
                if neighbor in selected or neighbor not in by_id:
                    continue
                if len(selected_order) >= limit:
                    truncated = True
                    continue
                selected.add(neighbor)
                selected_order.append(neighbor)
                next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    return {
        "resources": [dict(by_id[resource_id]) for resource_id in selected_order],
        "links": [
            dict(link)
            for link in allowed_links
            if str(link["source"]) in selected and str(link["target"]) in selected
        ],
        "truncated": truncated,
    }


__all__ = ["project_bounded_inventory_neighborhood"]
