"""Read-only operating-context materialization over the ontology graph."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

from .models import (
    OperationalContextEvidenceLink,
    OperationalContextEvidencePath,
    OperationalContextSnapshot,
    SourceFreshness,
)

_CONTEXT_LINKS = (
    "implemented_by",
    "workload_runs_on",
    "workload_depends_on",
    "service_has_service_objective",
    "service_has_recovery_objective",
    "service_has_cost_objective",
    "service_has_architecture_constraint",
    "service_owned_by",
    "workload_owned_by",
    "objective_owned_by",
)
_OBJECTIVE_TYPES = frozenset({"ServiceObjective", "RecoveryObjective", "CostObjective"})


class OperationalContextMaterializer:
    """Fold a bounded ontology neighborhood into one immutable snapshot."""

    def __init__(
        self,
        *,
        store: OntologyInstanceStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def materialize(
        self,
        *,
        target_resource_id: str,
        cutoff: datetime,
        catalog_versions: Mapping[str, str],
        source_freshness: Sequence[SourceFreshness] = (),
    ) -> OperationalContextSnapshot:
        if not target_resource_id.strip():
            raise ValueError("target_resource_id MUST be non-empty")
        if cutoff.tzinfo is None:
            raise ValueError("cutoff MUST be timezone-aware")
        recorded_at = self._clock()
        if recorded_at.tzinfo is None:
            raise RuntimeError("operational context clock MUST be timezone-aware")

        target = await self._store.get_object(target_resource_id)
        conflicts: list[str] = []
        objects: tuple[OntologyObjectRecord, ...]
        links: tuple[OntologyLinkRecord, ...]
        if target is None or target.object_type != "Resource":
            conflicts.append("target_resource_missing")
            objects = ()
            links = ()
        else:
            graph = await self._store.traverse(
                root_ids=(target_resource_id,),
                link_types=_CONTEXT_LINKS,
                direction="both",
                max_depth=3,
            )
            objects = graph.objects
            links = graph.links
            if graph.truncated:
                conflicts.append("context_graph_truncated")

        evidence_links = _evidence_links(links)
        evidence_paths = _evidence_paths(
            target_resource_id=target_resource_id,
            objects=objects,
            links=evidence_links,
        )
        if len(evidence_paths) != len(objects):
            conflicts.append("context_evidence_path_missing")

        by_type: dict[str, list[str]] = {}
        for item in objects:
            by_type.setdefault(item.object_type, []).append(item.id)
        service_ids = _ids(by_type, "BusinessService")
        workload_ids = _ids(by_type, "Workload")
        ownership_ids = _ids(by_type, "Ownership")
        if not service_ids:
            conflicts.append("service_mapping_missing")
        elif len(service_ids) > 1:
            conflicts.append("service_mapping_conflict")
        if len(ownership_ids) > 1:
            conflicts.append("ownership_conflict")

        canonical_freshness = tuple(
            sorted(
                source_freshness,
                key=lambda item: (
                    item.source,
                    item.observed_at.astimezone(UTC),
                    item.max_age_seconds,
                ),
            )
        )
        stale_sources: list[str] = []
        for freshness in canonical_freshness:
            if freshness.observed_at > cutoff:
                conflicts.append(f"source_after_cutoff:{freshness.source}")
            elif (cutoff - freshness.observed_at).total_seconds() > freshness.max_age_seconds:
                stale_sources.append(freshness.source)

        service_objective_ids = _ids(by_type, "ServiceObjective")
        recovery_objective_ids = _ids(by_type, "RecoveryObjective")
        cost_objective_ids = _ids(by_type, "CostObjective")
        objective_ids = tuple(
            sorted((*service_objective_ids, *recovery_objective_ids, *cost_objective_ids))
        )
        constraint_ids = _ids(by_type, "ArchitectureConstraint")
        dependency_ids = tuple(
            sorted(
                item.id
                for item in objects
                if item.object_type in {"Resource", "Workload"} and item.id != target_resource_id
            )
        )
        canonical_versions = tuple(sorted((str(k), str(v)) for k, v in catalog_versions.items()))
        normalized_conflicts = tuple(sorted(set(conflicts)))
        normalized_stale = tuple(sorted(set(stale_sources)))
        ceiling = (
            Autonomy.SHADOW_ONLY
            if normalized_conflicts or normalized_stale
            else Autonomy.ENFORCE_AUTO
        )
        identity = _snapshot_identity(
            target_resource_id=target_resource_id,
            cutoff=cutoff,
            catalog_versions=canonical_versions,
            evidence_links=evidence_links,
            evidence_paths=evidence_paths,
            source_freshness=canonical_freshness,
            stale_sources=normalized_stale,
            conflicts=normalized_conflicts,
        )
        return OperationalContextSnapshot(
            snapshot_id=identity,
            target_resource_id=target_resource_id,
            cutoff=cutoff,
            recorded_at=recorded_at,
            catalog_versions=canonical_versions,
            service_ids=service_ids,
            workload_ids=workload_ids,
            objective_ids=objective_ids,
            service_objective_ids=service_objective_ids,
            recovery_objective_ids=recovery_objective_ids,
            cost_objective_ids=cost_objective_ids,
            constraint_ids=constraint_ids,
            ownership_ids=ownership_ids,
            dependency_ids=dependency_ids,
            source_freshness=canonical_freshness,
            evidence_links=evidence_links,
            evidence_paths=evidence_paths,
            stale_sources=normalized_stale,
            conflicts=normalized_conflicts,
            autonomy_ceiling=ceiling,
        )


def _ids(by_type: Mapping[str, list[str]], object_type: str) -> tuple[str, ...]:
    return tuple(sorted(by_type.get(object_type, ())))


def _evidence_links(
    links: Sequence[OntologyLinkRecord],
) -> tuple[OperationalContextEvidenceLink, ...]:
    return tuple(
        OperationalContextEvidenceLink(
            link_type=link.link_type,
            from_id=link.from_id,
            to_id=link.to_id,
        )
        for link in sorted(links, key=lambda item: (item.link_type, item.from_id, item.to_id))
    )


def _evidence_paths(
    *,
    target_resource_id: str,
    objects: Sequence[OntologyObjectRecord],
    links: Sequence[OperationalContextEvidenceLink],
) -> tuple[OperationalContextEvidencePath, ...]:
    objects_by_id = {item.id: item for item in objects}
    if target_resource_id not in objects_by_id:
        return ()

    adjacency: dict[str, list[tuple[str, OperationalContextEvidenceLink]]] = {}
    for link in links:
        adjacency.setdefault(link.from_id, []).append((link.to_id, link))
        adjacency.setdefault(link.to_id, []).append((link.from_id, link))

    paths: dict[str, tuple[OperationalContextEvidenceLink, ...]] = {target_resource_id: ()}
    queue = deque((target_resource_id,))
    while queue:
        current = queue.popleft()
        neighbors = sorted(
            adjacency.get(current, ()),
            key=lambda item: (item[0], item[1].link_type, item[1].from_id, item[1].to_id),
        )
        for neighbor, link in neighbors:
            if neighbor in paths or neighbor not in objects_by_id:
                continue
            paths[neighbor] = (*paths[current], link)
            queue.append(neighbor)

    return tuple(
        OperationalContextEvidencePath(
            object_id=item.id,
            object_type=item.object_type,
            revision=item.revision,
            links=paths[item.id],
        )
        for item in sorted(objects, key=lambda value: value.id)
        if item.id in paths
    )


def _snapshot_identity(
    *,
    target_resource_id: str,
    cutoff: datetime,
    catalog_versions: tuple[tuple[str, str], ...],
    evidence_links: tuple[OperationalContextEvidenceLink, ...],
    evidence_paths: tuple[OperationalContextEvidencePath, ...],
    source_freshness: tuple[SourceFreshness, ...],
    stale_sources: tuple[str, ...],
    conflicts: tuple[str, ...],
) -> str:
    payload = {
        "catalog_versions": catalog_versions,
        "conflicts": conflicts,
        "cutoff": cutoff.isoformat(),
        "evidence_links": tuple(
            (item.link_type, item.from_id, item.to_id) for item in evidence_links
        ),
        "evidence_paths": tuple(
            (
                item.object_id,
                item.object_type,
                item.revision,
                tuple((link.link_type, link.from_id, link.to_id) for link in item.links),
            )
            for item in evidence_paths
        ),
        "source_freshness": tuple(
            (
                item.source,
                item.observed_at.astimezone(UTC).isoformat(),
                item.max_age_seconds,
            )
            for item in source_freshness
        ),
        "stale_sources": stale_sources,
        "target_resource_id": target_resource_id,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


__all__ = ["OperationalContextMaterializer"]
