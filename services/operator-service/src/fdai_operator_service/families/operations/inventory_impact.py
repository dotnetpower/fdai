"""Build one bounded no-authority impact projection over active inventory links."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypedDict

from fdai_operator_service.families.operations.contracts import (
    InventoryImpactEdge,
    InventoryImpactReader,
    ProjectionNotFoundError,
    ProjectionQuery,
    ProjectionUnavailableError,
)

MAX_IMPACT_DEPTH = 5
MAX_IMPACT_EDGES = 1_000
MAX_IMPACT_LINK_TYPES = 16


@dataclass(frozen=True, slots=True)
class _ImpactRequest:
    target: str
    depth: int
    link_types: tuple[str, ...]


class _ReachedNode(TypedDict):
    resource_id: str
    depth: int
    via_link_type: str | None


async def project_inventory_impact(
    *,
    query: ProjectionQuery,
    reader: InventoryImpactReader,
    ontology_projection: Mapping[str, object],
) -> dict[str, object]:
    """Traverse stored-direction links with explicit release, cutoff, and truncation state."""

    release_digest, declared_links = _ontology_identity(ontology_projection)
    request = _impact_request(query.params, declared_links=declared_links)
    context = await reader.read_inventory_impact_context()
    if context is None:
        raise ProjectionUnavailableError("active inventory snapshot is unavailable")
    if not await reader.inventory_resource_exists(
        snapshot_id=context.snapshot_id,
        resource_id=request.target,
    ):
        raise ProjectionNotFoundError(request.target)

    reached: dict[str, _ReachedNode] = {
        request.target: {
            "resource_id": request.target,
            "depth": 0,
            "via_link_type": None,
        }
    }
    traversed: list[dict[str, object]] = []
    frontier: tuple[str, ...] = (request.target,)
    edge_limit_reached = False
    depth_limit_reached = False

    for depth in range(1, request.depth + 1):
        if not frontier:
            break
        remaining = MAX_IMPACT_EDGES - len(traversed)
        if remaining < 1:
            edge_limit_reached = True
            break
        page = await reader.read_inventory_outgoing_links(
            snapshot_id=context.snapshot_id,
            source_ids=frontier,
            link_types=request.link_types,
            limit=remaining,
        )
        ordered = _ordered_edges(
            page.edges,
            source_ids=frontier,
            link_types=request.link_types,
        )
        next_frontier: set[str] = set()
        for edge in ordered:
            traversed.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "link_type": edge.link_type,
                    "depth": depth,
                    "verification_status": "unverified",
                }
            )
            if edge.target not in reached:
                reached[edge.target] = {
                    "resource_id": edge.target,
                    "depth": depth,
                    "via_link_type": edge.link_type,
                }
                next_frontier.add(edge.target)
        if page.truncated:
            edge_limit_reached = True
            break
        frontier = tuple(sorted(next_frontier))

    if not edge_limit_reached and frontier:
        probe = await reader.read_inventory_outgoing_links(
            snapshot_id=context.snapshot_id,
            source_ids=frontier,
            link_types=request.link_types,
            limit=1,
        )
        depth_limit_reached = any(edge.target not in reached for edge in probe.edges)

    truncation_reasons = [
        reason
        for reason, active in (
            ("edge_limit", edge_limit_reached),
            ("depth_limit", depth_limit_reached),
        )
        if active
    ]
    return {
        "schema_version": "1.0.0",
        "ontology_release_digest": release_digest,
        "source_generation": context.snapshot_id,
        "source_cutoff": context.observed_at.isoformat(),
        "target": request.target,
        "traversal_depth": request.depth,
        "traversal_links": list(request.link_types),
        "reached": sorted(
            reached.values(),
            key=lambda item: (item["depth"], item["resource_id"]),
        ),
        "edges": traversed,
        "affected_count": len(reached) - 1,
        "complete": not truncation_reasons,
        "truncated_at_depth": depth_limit_reached,
        "truncation_reasons": truncation_reasons,
        "execution_authority": False,
        "mutation_authority": False,
    }


def _impact_request(
    params: Mapping[str, tuple[str, ...]],
    *,
    declared_links: frozenset[str],
) -> _ImpactRequest:
    target_values = params.get("target", ())
    if len(target_values) != 1 or not target_values[0].strip():
        raise ValueError("impact target MUST be supplied exactly once")
    target = target_values[0].strip()

    depth_values = params.get("depth", ("2",))
    if len(depth_values) != 1:
        raise ValueError("impact depth MUST be supplied at most once")
    try:
        depth = int(depth_values[0])
    except ValueError as exc:
        raise ValueError("impact depth MUST be an integer") from exc
    if not 1 <= depth <= MAX_IMPACT_DEPTH:
        raise ValueError(f"impact depth MUST be in [1, {MAX_IMPACT_DEPTH}]")

    requested = [*params.get("link", ())]
    for value in params.get("links", ()):
        if value == "none":
            continue
        requested.extend(value.split(","))
    link_types = tuple(dict.fromkeys(value.strip() for value in requested if value.strip()))
    if not link_types:
        raise ValueError("impact link types MUST NOT be empty")
    if len(link_types) > MAX_IMPACT_LINK_TYPES:
        raise ValueError(f"impact link types MUST contain at most {MAX_IMPACT_LINK_TYPES} values")
    unknown = sorted(set(link_types) - declared_links)
    if unknown:
        raise ValueError(f"impact link type is not declared: {unknown[0]}")
    return _ImpactRequest(target=target, depth=depth, link_types=link_types)


def _ontology_identity(
    projection: Mapping[str, object],
) -> tuple[str, frozenset[str]]:
    if projection.get("mutation_authority") is not False:
        raise ProjectionUnavailableError("ontology registry authority boundary is invalid")
    release_digest = projection.get("ontology_release_digest")
    link_types = projection.get("link_types")
    if not isinstance(release_digest, str) or not release_digest.startswith("sha256:"):
        raise ProjectionUnavailableError("ontology registry release identity is unavailable")
    if not isinstance(link_types, list) or any(
        not isinstance(item, str) or not item for item in link_types
    ):
        raise ProjectionUnavailableError("ontology registry LinkTypes are malformed")
    return release_digest, frozenset(link_types)


def _ordered_edges(
    edges: tuple[InventoryImpactEdge, ...],
    *,
    source_ids: tuple[str, ...],
    link_types: tuple[str, ...],
) -> tuple[InventoryImpactEdge, ...]:
    source_order = {value: index for index, value in enumerate(source_ids)}
    link_order = {value: index for index, value in enumerate(link_types)}
    return tuple(
        sorted(
            edges,
            key=lambda edge: (
                source_order.get(edge.source, len(source_order)),
                link_order.get(edge.link_type, len(link_order)),
                edge.target,
            ),
        )
    )


__all__ = ["project_inventory_impact"]
