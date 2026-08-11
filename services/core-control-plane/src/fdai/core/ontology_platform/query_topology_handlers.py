"""Verified query handlers for retained bitemporal topology history."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind

from .query_execution import QueryNodeResult
from .topology_history import (
    TopologyGraphAt,
    TopologyHistoryReader,
    graph_at,
    topology_diff,
)

TOPOLOGY_ARGUMENT_SCHEMAS: Mapping[QueryNodeKind, Mapping[str, object]] = {
    QueryNodeKind.TOPOLOGY_AT: {
        "type": "object",
        "additionalProperties": False,
        "required": ["as_of", "known_at"],
        "properties": {
            "as_of": {"type": "string", "format": "date-time"},
            "known_at": {"type": "string", "format": "date-time"},
        },
    },
    QueryNodeKind.TOPOLOGY_DIFF: {
        "type": "object",
        "additionalProperties": False,
    },
}


class TopologyAtNodeHandler:
    """Materialize one historical graph at pinned event and record cutoffs."""

    def __init__(self, reader: TopologyHistoryReader) -> None:
        self._reader = reader

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if node.kind is not QueryNodeKind.TOPOLOGY_AT or dependencies:
            raise ValueError("topology_at node MUST be a dependency-free topology source")
        if set(node.arguments) != {"as_of", "known_at"}:
            raise ValueError("topology_at arguments MUST contain as_of and known_at")
        as_of = _timestamp(node.arguments["as_of"], "as_of")
        known_at = _timestamp(node.arguments["known_at"], "known_at")
        batches = await self._reader.read(as_of=as_of, known_at=known_at)
        result = graph_at(batches, as_of=as_of, known_at=known_at)
        return QueryNodeResult(
            value=result,
            evidence_refs=result.evidence_refs + (f"topology-graph:{result.digest}",),
        )


class TopologyDiffNodeHandler:
    """Compute one deterministic diff over two completed topology_at dependencies."""

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if node.kind is not QueryNodeKind.TOPOLOGY_DIFF or node.arguments:
            raise ValueError("topology_diff node does not accept arguments")
        if len(node.depends_on) != 2 or set(dependencies) != set(node.depends_on):
            raise ValueError("topology_diff node requires exactly two dependencies")
        before = dependencies[node.depends_on[0]].value
        after = dependencies[node.depends_on[1]].value
        if not isinstance(before, TopologyGraphAt) or not isinstance(after, TopologyGraphAt):
            raise TypeError("topology_diff dependencies MUST be TopologyGraphAt values")
        result = topology_diff(before, after)
        return QueryNodeResult(
            value=result,
            evidence_refs=result.evidence_refs + (f"topology-diff:{result.digest}",),
        )


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"topology {name} MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"topology {name} MUST be an RFC 3339 string") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"topology {name} MUST be timezone-aware")
    return parsed


__all__ = [
    "TOPOLOGY_ARGUMENT_SCHEMAS",
    "TopologyAtNodeHandler",
    "TopologyDiffNodeHandler",
]
