"""Verified query handlers for retained bitemporal topology history."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime

from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    QueryNodeKind,
    content_digest,
)

from fdai.shared.contracts.models import OntologyObjectType
from fdai.shared.ontology.acl import ProjectionRequest, project_graph_snapshot
from fdai.shared.providers.ontology_instance import normalize_json_value

from .query_execution import QueryNodeHeldError, QueryNodeResult
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

    def __init__(
        self,
        reader: TopologyHistoryReader,
        *,
        expected_release_digest: str | None = None,
        object_types: Mapping[str, OntologyObjectType] | None = None,
        projection_request: ProjectionRequest | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._reader = reader
        self._expected_release = expected_release_digest
        self._object_types = object_types
        self._projection_request = projection_request
        self._now = now or (lambda: datetime.now(UTC))

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if node.kind is not QueryNodeKind.TOPOLOGY_AT or dependencies:
            raise ValueError("topology_at node MUST be a dependency-free topology source")
        if set(node.arguments) != {"as_of", "known_at"}:
            raise ValueError("topology_at arguments MUST contain as_of and known_at")
        if (
            self._expected_release is None
            or self._object_types is None
            or self._projection_request is None
        ):
            raise PermissionError("historical topology requires an authorized projection")
        as_of = _timestamp(node.arguments["as_of"], "as_of")
        known_at = _timestamp(node.arguments["known_at"], "known_at")
        if as_of > known_at or known_at > self._now():
            raise ValueError("historical query cutoffs MUST be ordered and not in the future")
        batches = await self._reader.read(as_of=as_of, known_at=known_at)
        result = graph_at(batches, as_of=as_of, known_at=known_at)
        if result.revision_ids and (
            result.ontology_release_digests != (self._expected_release,)
            or any(
                batch.ontology_release_digest != self._expected_release
                for batch in batches
                if batch.revision_id in result.revision_ids
            )
        ):
            raise QueryNodeHeldError("topology_release_unavailable")
        projected = project_graph_snapshot(
            result.graph, object_types=self._object_types, request=self._projection_request
        )
        result = replace(
            result,
            graph=projected,
            digest=content_digest(
                {
                    "source_digest": result.digest,
                    "role": self._projection_request.caller_role.value,
                    "purposes": sorted(self._projection_request.declared_purposes),
                    "principal_scope": self._projection_request.principal_scope_digest,
                    "objects": [
                        {"id": record.id, "properties": normalize_json_value(record.properties)}
                        for record in projected.objects
                    ],
                    "links": [
                        (link.from_id, link.link_type, link.to_id) for link in projected.links
                    ],
                }
            ),
        )
        return QueryNodeResult(
            value=result,
            evidence_refs=result.evidence_refs + (f"topology-graph:{result.digest}",),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
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
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
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
