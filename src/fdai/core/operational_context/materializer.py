"""Read-only operating-context materialization over the ontology graph."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.ontology_instance import OntologyInstanceStore, OntologyObjectRecord

from .models import OperationalContextSnapshot, SourceFreshness

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
        if target is None or target.object_type != "Resource":
            conflicts.append("target_resource_missing")
            objects = ()
        else:
            graph = await self._store.traverse(
                root_ids=(target_resource_id,),
                link_types=_CONTEXT_LINKS,
                direction="both",
                max_depth=3,
            )
            objects = graph.objects

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

        stale_sources: list[str] = []
        for freshness in source_freshness:
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
            object_ids=tuple(sorted(item.id for item in objects)),
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
            stale_sources=normalized_stale,
            conflicts=normalized_conflicts,
            autonomy_ceiling=ceiling,
        )


def _ids(by_type: Mapping[str, list[str]], object_type: str) -> tuple[str, ...]:
    return tuple(sorted(by_type.get(object_type, ())))


def _snapshot_identity(
    *,
    target_resource_id: str,
    cutoff: datetime,
    catalog_versions: tuple[tuple[str, str], ...],
    object_ids: tuple[str, ...],
    stale_sources: tuple[str, ...],
    conflicts: tuple[str, ...],
) -> str:
    payload = {
        "catalog_versions": catalog_versions,
        "conflicts": conflicts,
        "cutoff": cutoff.isoformat(),
        "object_ids": object_ids,
        "stale_sources": stale_sources,
        "target_resource_id": target_resource_id,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


__all__ = ["OperationalContextMaterializer"]
