"""Verify causal reachability within one secured historical topology view."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import datetime

from fdai.shared.providers.ontology_instance import (
    MAX_ONTOLOGY_QUERY_LINKS,
    OntologyLinkRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
)

from .topology_history import TopologyDiff, TopologyGraphAt

_DEPENDENCY_ENDPOINTS = {
    "depends_on": ("Resource", "Resource"),
    "workload_depends_on": ("Workload", "Workload"),
    "implemented_by": ("BusinessService", "Workload"),
    "workload_runs_on": ("Workload", "Resource"),
}
_MAX_VISITED = 1_000
_MAX_DEPTH = 4


def causal_topology_limitation(
    topology: TopologyDiff,
    *,
    cause_id: str,
    effect_id: str,
    cutoff: datetime,
    window_start: datetime,
) -> str | None:
    """Require an observed identity or effect-to-prerequisite path in one retained view.

    A diff alone proves only that something changed. Never combine edges from different
    views, infer the inverse of a dependency, or treat path absence as causal refutation.
    """

    if not cause_id.strip() or not effect_id.strip():
        raise ValueError("causal topology cause_id and effect_id MUST be non-empty")
    if cutoff.utcoffset() is None or window_start.utcoffset() is None:
        raise ValueError("causal topology cutoff and window_start MUST be timezone-aware")
    if topology.before is None or topology.after is None:
        return "topology_path_evidence_unavailable"
    if (
        topology.before.digest != topology.before_digest
        or topology.after.digest != topology.after_digest
    ):
        return "topology_view_digest_mismatch"
    limited = False
    for view in (topology.before, topology.after):
        if (
            not view.complete
            or not view.graph.source_complete
            or view.graph.truncated
            or view.as_of > cutoff
            or view.as_of < window_start
            or view.known_at < view.as_of
        ):
            continue
        if len(view.graph.links) > MAX_ONTOLOGY_QUERY_LINKS:
            limited = True
            continue
        types = {record.id: record.object_type for record in view.graph.objects}
        if cause_id not in types or effect_id not in types:
            continue
        if cause_id == effect_id:
            return None
        adjacency: dict[str, set[str]] = {}
        for link in view.graph.links:
            if _DEPENDENCY_ENDPOINTS.get(link.link_type) != (
                types.get(link.from_id),
                types.get(link.to_id),
            ):
                continue
            if _verified_at(link, view, effective_before=window_start):
                adjacency.setdefault(link.from_id, set()).add(link.to_id)
        pending = deque([(effect_id, 0)])
        visited = {effect_id}
        while pending:
            current, depth = pending.popleft()
            if depth == _MAX_DEPTH:
                limited = limited or bool(adjacency.get(current))
                continue
            for prerequisite in sorted(adjacency.get(current, ())):
                if prerequisite == cause_id:
                    return None
                if prerequisite in visited:
                    continue
                if len(visited) == _MAX_VISITED:
                    limited = True
                    continue
                visited.add(prerequisite)
                pending.append((prerequisite, depth + 1))
    return "topology_path_limit_exceeded" if limited else "causal_dependency_path_unproven"


def _verified_at(
    link: OntologyLinkRecord, view: TopologyGraphAt, *, effective_before: datetime
) -> bool:
    raw = link.properties.get(LINK_OBSERVATION_METADATA_PROPERTY)
    if not isinstance(raw, Mapping):
        return False
    try:
        metadata = LinkObservationMetadata.from_mapping(raw)
    except (TypeError, ValueError):
        return False
    fact = metadata.state_fact
    return (
        metadata.verified
        and not fact.synthetic
        and not fact.conflicts
        and fact.completeness == 1.0
        and fact.effective_at <= view.as_of
        and fact.effective_at <= effective_before
        and fact.evidence_cutoff <= view.as_of
        and fact.recorded_at <= view.known_at
        and (view.as_of - fact.evidence_cutoff).total_seconds() <= fact.freshness_ceiling_seconds
    )
