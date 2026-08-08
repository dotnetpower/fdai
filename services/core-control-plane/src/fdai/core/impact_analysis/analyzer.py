"""Bounded ontology traversal for intervention impact."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass

from fdai.core.impact_analysis.models import AffectedSet
from fdai.shared.providers.ontology_instance import OntologyInstanceStore

IMPACT_LINKS = (
    "contains",
    "attached_to",
    "depends_on",
    "implemented_by",
    "workload_runs_on",
    "workload_depends_on",
    "service_has_service_objective",
    "service_has_recovery_objective",
)


@dataclass(frozen=True, slots=True)
class ImpactTraversalBounds:
    max_depth: int = 2
    max_nodes: int = 500
    max_edges: int = 2000
    max_bytes: int = 4 * 1024 * 1024
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_depth <= 5:
            raise ValueError("max_depth MUST be in [1, 5]")
        if not 1 <= self.max_nodes <= 1000:
            raise ValueError("max_nodes MUST be in [1, 1000]")
        if self.max_edges < 1 or self.max_bytes < 1 or self.timeout_seconds <= 0:
            raise ValueError("edge, byte, and timeout bounds MUST be positive")


class ImpactAnalyzer:
    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def analyze(
        self,
        *,
        direct_target_ids: tuple[str, ...],
        bounds: ImpactTraversalBounds | None = None,
        graph_fresh: bool = True,
        unresolved_conflicts: tuple[str, ...] = (),
    ) -> AffectedSet:
        if not direct_target_ids or any(not item.strip() for item in direct_target_ids):
            raise ValueError("direct_target_ids MUST be non-empty")
        active = bounds or ImpactTraversalBounds()
        try:
            graph = await asyncio.wait_for(
                self._store.traverse(
                    root_ids=direct_target_ids,
                    link_types=IMPACT_LINKS,
                    direction="both",
                    max_depth=active.max_depth,
                    limit=active.max_nodes,
                ),
                timeout=active.timeout_seconds,
            )
        except TimeoutError as exc:
            raise TimeoutError("impact traversal exceeded its deadline") from exc

        by_type: dict[str, list[str]] = {}
        control_dependencies: list[str] = []
        for item in graph.objects:
            by_type.setdefault(item.object_type, []).append(item.id)
            if item.object_type == "Resource" and item.properties.get("control_dependency") is True:
                control_dependencies.append(item.id)
        direct = tuple(dict.fromkeys(direct_target_ids))
        direct_set = set(direct)
        dependents = tuple(
            sorted(
                item.id
                for item in graph.objects
                if item.object_type in {"Resource", "Workload"} and item.id not in direct_set
            )
        )
        services = tuple(sorted(by_type.get("BusinessService", ())))
        objectives = tuple(
            sorted(
                (
                    *by_type.get("ServiceObjective", ()),
                    *by_type.get("RecoveryObjective", ()),
                )
            )
        )
        reasons = list(unresolved_conflicts)
        if not graph_fresh:
            reasons.append("graph_stale")
        if not direct_set <= {item.id for item in graph.objects}:
            reasons.append("direct_target_missing")
        object_rows = sorted((item.id, item.object_type, item.revision) for item in graph.objects)
        link_rows = sorted((item.link_type, item.from_id, item.to_id) for item in graph.links)
        encoded = json.dumps(
            {"objects": object_rows, "links": link_rows},
            separators=(",", ":"),
        ).encode()
        edge_overflow = len(graph.links) > active.max_edges
        byte_overflow = len(encoded) > active.max_bytes
        if edge_overflow:
            reasons.append("edge_cap_exceeded")
        if byte_overflow:
            reasons.append("byte_cap_exceeded")
        return AffectedSet(
            direct_targets=direct,
            runtime_dependents=dependents,
            protected_services=services,
            protected_objectives=objectives,
            control_dependencies=tuple(sorted(set(control_dependencies))),
            graph_revision=hashlib.sha256(encoded).hexdigest(),
            truncated=graph.truncated or edge_overflow or byte_overflow,
            incomplete_reasons=tuple(sorted(set(reasons))),
        )


__all__ = ["IMPACT_LINKS", "ImpactAnalyzer", "ImpactTraversalBounds"]
