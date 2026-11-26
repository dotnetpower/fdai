"""Blast-radius simulator - pure graph BFS over the ontology.

Given a proposed action (target Resource id, traversal spec), computes
the depth-N neighborhood subgraph so a reviewer sees exactly which
resources would be touched **before** the action fires. Called by the
Operator API simulator endpoint and by the risk-gate `graph_derived` axis
whenever a live graph adapter is bound.

The module is dependency-free of ``delivery/`` and cloud SDKs: the
graph is an injected :class:`OntologyGraph` Protocol so the same
computation runs against an in-memory fixture (tests, dev) or a live
Postgres-backed projection (production).

Design invariants
-----------------
- **Pure BFS**: deterministic order, no I/O beyond the injected graph.
  Same input MUST produce the same output byte-for-byte.
- **Bounded**: ``traversal_depth`` is capped at 5 (matches the
  ActionType JSON Schema); a request that asks for more is a hard
  error, never a "clip silently".
- **Type-safe hops**: only the link types the caller names are
  traversed. A link the ontology has not declared is a
  :class:`UnknownLinkTypeError`.
- **Read-only**: never mutates the graph or the ontology.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

MAX_TRAVERSAL_DEPTH = 5
"""Hard cap - matches the ontology `action-type` JSON Schema."""


@runtime_checkable
class OntologyGraph(Protocol):
    """Read-only graph seam the simulator depends on.

    Implementations MUST return a stable iteration order for a given
    ``(source, link_type)`` pair so the BFS is reproducible.
    """

    def neighbors(self, source: str, link_type: str) -> Iterable[str]:
        """Return every target Resource id reachable via one hop of ``link_type``."""
        ...

    def has_link_type(self, link_type: str) -> bool:
        """Return True when the ontology declares this link type."""
        ...


class UnknownLinkTypeError(ValueError):
    """Raised when the caller asks to traverse a link type the graph rejects."""


class TraversalDepthExceededError(ValueError):
    """Raised when the requested depth exceeds :data:`MAX_TRAVERSAL_DEPTH`."""


@dataclass(frozen=True, slots=True)
class ReachedNode:
    """One node reached by the BFS.

    ``depth`` is 0 for the target itself, 1 for direct neighbors, and
    so on. ``via_link_type`` records which link type first surfaced
    this node; when multiple links reach the same node the earliest
    (breadth-first) hop wins.
    """

    resource_id: str
    depth: int
    via_link_type: str | None


@dataclass(frozen=True, slots=True)
class TraversedEdge:
    """One directed edge visited by the BFS."""

    source: str
    target: str
    link_type: str
    depth: int


@dataclass(frozen=True, slots=True)
class BlastRadiusReport:
    """Result of one simulation."""

    target: str
    traversal_depth: int
    traversal_links: tuple[str, ...]
    reached: tuple[ReachedNode, ...]
    edges: tuple[TraversedEdge, ...]
    truncated_at_depth: bool
    """True when at least one node at ``depth == traversal_depth`` still had unvisited neighbors."""

    def affected_count(self) -> int:
        """Number of distinct Resources affected, excluding the target itself."""
        return sum(1 for node in self.reached if node.resource_id != self.target)

    def as_json(self) -> dict[str, object]:
        """Client-safe dict for HTTP responses."""
        return {
            "target": self.target,
            "traversal_depth": self.traversal_depth,
            "traversal_links": list(self.traversal_links),
            "reached": [
                {
                    "resource_id": n.resource_id,
                    "depth": n.depth,
                    "via_link_type": n.via_link_type,
                }
                for n in self.reached
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "link_type": e.link_type,
                    "depth": e.depth,
                }
                for e in self.edges
            ],
            "affected_count": self.affected_count(),
            "truncated_at_depth": self.truncated_at_depth,
        }


@dataclass(frozen=True, slots=True)
class BlastRadiusRequest:
    """Input to :func:`simulate_blast_radius`."""

    target: str
    traversal_depth: int
    traversal_links: tuple[str, ...]


def simulate_blast_radius(graph: OntologyGraph, request: BlastRadiusRequest) -> BlastRadiusReport:
    """Compute the depth-N reachable set from ``request.target``.

    Deterministic BFS ordered by (depth, link-type order in
    ``traversal_links``, neighbor iteration order from the graph).
    """
    if request.traversal_depth < 1:
        raise ValueError("traversal_depth MUST be at least 1")
    if request.traversal_depth > MAX_TRAVERSAL_DEPTH:
        raise TraversalDepthExceededError(
            f"traversal_depth={request.traversal_depth} exceeds cap {MAX_TRAVERSAL_DEPTH}"
        )
    if not request.traversal_links:
        raise ValueError("traversal_links MUST NOT be empty")
    for link_type in request.traversal_links:
        if not graph.has_link_type(link_type):
            raise UnknownLinkTypeError(f"link type {link_type!r} not declared in the ontology")

    seen: dict[str, ReachedNode] = {
        request.target: ReachedNode(resource_id=request.target, depth=0, via_link_type=None)
    }
    edges: list[TraversedEdge] = []
    truncated = False

    # Queue holds (node, depth). Depth-0 is the target; expand up to
    # traversal_depth. When we reach traversal_depth we still visit the
    # edges for auditing purposes (so the report shows the frontier)
    # but do NOT add new nodes.
    queue: deque[tuple[str, int]] = deque()
    queue.append((request.target, 0))
    while queue:
        current, depth = queue.popleft()
        if depth >= request.traversal_depth:
            continue
        for link_type in request.traversal_links:
            for neighbor in graph.neighbors(current, link_type):
                edges.append(
                    TraversedEdge(
                        source=current,
                        target=neighbor,
                        link_type=link_type,
                        depth=depth + 1,
                    )
                )
                if neighbor not in seen:
                    seen[neighbor] = ReachedNode(
                        resource_id=neighbor,
                        depth=depth + 1,
                        via_link_type=link_type,
                    )
                    if depth + 1 < request.traversal_depth:
                        queue.append((neighbor, depth + 1))
                    else:
                        # Frontier node - track truncation so the caller
                        # knows the depth cap may be hiding more nodes.
                        truncated = (
                            _check_truncation(graph, neighbor, request.traversal_links, seen)
                            or truncated
                        )

    reached_sorted = tuple(sorted(seen.values(), key=lambda n: (n.depth, n.resource_id)))
    return BlastRadiusReport(
        target=request.target,
        traversal_depth=request.traversal_depth,
        traversal_links=request.traversal_links,
        reached=reached_sorted,
        edges=tuple(edges),
        truncated_at_depth=truncated,
    )


def _check_truncation(
    graph: OntologyGraph,
    node: str,
    link_types: Iterable[str],
    seen: dict[str, ReachedNode],
) -> bool:
    """Return True when ``node`` has at least one neighbor the BFS did not reach.

    Used only to set the ``truncated_at_depth`` flag; the neighbors
    themselves are not added to the report.
    """
    for link_type in link_types:
        for neighbor in graph.neighbors(node, link_type):
            if neighbor not in seen:
                return True
    return False


# ---------------------------------------------------------------------------
# In-memory test / dev graph
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InMemoryOntologyGraph:
    """Fixture graph used by tests and the local Operator API demo.

    ``edges`` maps ``(source, link_type) -> ordered tuple of targets``.
    ``link_types`` MUST include every link type the caller may name;
    unknown link types raise :class:`UnknownLinkTypeError`.
    """

    edges: dict[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    link_types: frozenset[str] = field(default_factory=frozenset)

    def neighbors(self, source: str, link_type: str) -> Iterable[str]:
        return self.edges.get((source, link_type), ())

    def has_link_type(self, link_type: str) -> bool:
        return link_type in self.link_types


__all__ = [
    "MAX_TRAVERSAL_DEPTH",
    "BlastRadiusReport",
    "BlastRadiusRequest",
    "InMemoryOntologyGraph",
    "OntologyGraph",
    "ReachedNode",
    "TraversalDepthExceededError",
    "TraversedEdge",
    "UnknownLinkTypeError",
    "simulate_blast_radius",
]
