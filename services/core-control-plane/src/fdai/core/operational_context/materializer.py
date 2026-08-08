"""Read-only operating-context materialization over the ontology graph."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
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
        clock_identity: str = "system-utc",
        max_clock_skew_seconds: int = 30,
    ) -> None:
        if not clock_identity.strip():
            raise ValueError("clock_identity MUST be non-empty")
        if isinstance(max_clock_skew_seconds, bool) or not isinstance(max_clock_skew_seconds, int):
            raise ValueError("max_clock_skew_seconds MUST be an integer")
        if max_clock_skew_seconds < 0:
            raise ValueError("max_clock_skew_seconds MUST be >= 0")
        self._store = store
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._clock_identity = clock_identity
        self._max_clock_skew_seconds = max_clock_skew_seconds

    async def materialize(
        self,
        *,
        target_resource_id: str,
        cutoff: datetime,
        catalog_versions: Mapping[str, str],
        source_freshness: Sequence[SourceFreshness] = (),
        require_verified_links: bool = False,
    ) -> OperationalContextSnapshot:
        if not target_resource_id.strip():
            raise ValueError("target_resource_id MUST be non-empty")
        if cutoff.tzinfo is None:
            raise ValueError("cutoff MUST be timezone-aware")
        cutoff = cutoff.astimezone(UTC)
        recorded_at = self._clock()
        if recorded_at.tzinfo is None:
            raise RuntimeError("operational context clock MUST be timezone-aware")
        recorded_at = recorded_at.astimezone(UTC)
        trusted_latest = recorded_at + timedelta(seconds=self._max_clock_skew_seconds)

        target = await self._store.get_object(target_resource_id)
        conflicts: list[str] = []
        if cutoff > trusted_latest:
            conflicts.append("context_cutoff_after_trusted_now")
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

        all_evidence_links = _evidence_links(links)
        all_evidence_paths = _evidence_paths(
            target_resource_id=target_resource_id,
            objects=objects,
            links=all_evidence_links,
        )
        temporal_exclusions = tuple(
            item for item in all_evidence_paths if not _is_effective_at(item, cutoff=cutoff)
        )
        if temporal_exclusions:
            conflicts.append("context_temporal_exclusion")
        excluded_ids = {item.object_id for item in temporal_exclusions}
        objects = tuple(item for item in objects if item.id not in excluded_ids)
        links = tuple(
            item
            for item in links
            if item.from_id not in excluded_ids and item.to_id not in excluded_ids
        )
        evidence_links = _evidence_links(links)
        evidence_paths = _evidence_paths(
            target_resource_id=target_resource_id,
            objects=objects,
            links=evidence_links,
        )
        if len(evidence_paths) != len(objects):
            conflicts.append("context_evidence_path_missing")
        reachable_ids = {item.object_id for item in evidence_paths}
        objects = tuple(item for item in objects if item.id in reachable_ids)
        evidence_links = tuple(
            item
            for item in evidence_links
            if item.from_id in reachable_ids and item.to_id in reachable_ids
        )
        link_conflicts, link_stale_sources = _link_evidence_constraints(
            evidence_links,
            cutoff=cutoff,
            trusted_latest=trusted_latest,
            require_verified=require_verified_links,
        )
        conflicts.extend(link_conflicts)

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
                (
                    SourceFreshness(
                        source=item.source,
                        observed_at=item.observed_at.astimezone(UTC),
                        max_age_seconds=item.max_age_seconds,
                    )
                    for item in source_freshness
                ),
                key=lambda item: (
                    item.source,
                    item.observed_at.astimezone(UTC),
                    item.max_age_seconds,
                ),
            )
        )
        stale_sources = list(link_stale_sources)
        freshness_sources = {item.source for item in canonical_freshness}
        for required_source in _required_freshness_sources(objects):
            if required_source not in freshness_sources:
                conflicts.append(f"source_freshness_missing:{required_source}")
        for freshness in canonical_freshness:
            if freshness.observed_at > trusted_latest:
                conflicts.append(f"source_after_trusted_now:{freshness.source}")
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
            recorded_at=recorded_at,
            clock_identity=self._clock_identity,
            require_verified_links=require_verified_links,
            catalog_versions=canonical_versions,
            evidence_links=evidence_links,
            evidence_paths=evidence_paths,
            temporal_exclusions=temporal_exclusions,
            source_freshness=canonical_freshness,
            stale_sources=normalized_stale,
            conflicts=normalized_conflicts,
        )
        return OperationalContextSnapshot(
            snapshot_id=identity,
            target_resource_id=target_resource_id,
            cutoff=cutoff,
            recorded_at=recorded_at,
            clock_identity=self._clock_identity,
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
            temporal_exclusions=temporal_exclusions,
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
            observation_metadata=_link_observation_metadata(link),
        )
        for link in sorted(links, key=lambda item: (item.link_type, item.from_id, item.to_id))
    )


def _link_observation_metadata(link: OntologyLinkRecord) -> LinkObservationMetadata | None:
    raw = link.properties.get(LINK_OBSERVATION_METADATA_PROPERTY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"{link.link_type}.{LINK_OBSERVATION_METADATA_PROPERTY} MUST be an object")
    return LinkObservationMetadata.from_mapping(raw)


def _link_evidence_constraints(
    links: Sequence[OperationalContextEvidenceLink],
    *,
    cutoff: datetime,
    trusted_latest: datetime,
    require_verified: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return never-raising context constraints from typed link evidence."""

    conflicts: set[str] = set()
    stale_sources: set[str] = set()
    for link in links:
        metadata = link.observation_metadata
        identity = f"{link.link_type}:{link.from_id}:{link.to_id}"
        if metadata is None:
            if require_verified:
                conflicts.add(f"link_evidence_missing:{identity}")
            continue
        fact = metadata.state_fact
        if (
            fact.recorded_at > trusted_latest
            or fact.evidence_cutoff > trusted_latest
            or fact.effective_at > trusted_latest
        ):
            conflicts.add(f"link_evidence_after_trusted_now:{identity}")
        if fact.recorded_at > cutoff or fact.evidence_cutoff > cutoff or fact.effective_at > cutoff:
            conflicts.add(f"link_evidence_after_cutoff:{identity}")
            continue
        if (cutoff - fact.effective_at).total_seconds() > fact.freshness_ceiling_seconds:
            conflicts.add(f"link_evidence_stale:{identity}")
            stale_sources.add(fact.source_identity)
        if fact.completeness < 1.0:
            conflicts.add(f"link_evidence_incomplete:{identity}")
        if fact.conflicts:
            conflicts.add(f"link_evidence_conflicting:{identity}")
        if fact.synthetic:
            conflicts.add(f"link_evidence_synthetic:{identity}")
        if not metadata.verified:
            conflicts.add(f"link_evidence_unverified:{identity}")
    return tuple(sorted(conflicts)), tuple(sorted(stale_sources))


def _required_freshness_sources(
    objects: Sequence[OntologyObjectRecord],
) -> tuple[str, ...]:
    """Return source ids for reachable objects that declare a freshness policy."""

    required: set[str] = set()
    for item in objects:
        ceiling = item.properties.get("freshness_seconds")
        if ceiling is None:
            continue
        if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling < 1:
            raise ValueError(f"{item.object_type}.freshness_seconds MUST be a positive integer")
        source = next(
            (
                value.strip()
                for name in ("measurement_source_ref", "source_ref")
                if isinstance((value := item.properties.get(name)), str) and value.strip()
            ),
            None,
        )
        if source is None:
            raise ValueError(
                f"{item.object_type} with freshness_seconds MUST identify its evidence source"
            )
        required.add(source)
    return tuple(sorted(required))


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
            effective_from=_datetime_property(item, "effective_from"),
            effective_to=_datetime_property(item, "effective_to"),
            provenance_refs=_provenance_refs(item),
            links=paths[item.id],
        )
        for item in sorted(objects, key=lambda value: value.id)
        if item.id in paths
    )


def _datetime_property(record: OntologyObjectRecord, name: str) -> datetime | None:
    value = record.properties.get(name)
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"{record.object_type}.{name} MUST be a timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{record.object_type}.{name} MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _provenance_refs(record: OntologyObjectRecord) -> tuple[str, ...]:
    values = {
        value
        for name in ("source_ref", "measurement_source_ref", "expression_ref")
        if isinstance((value := record.properties.get(name)), str) and value.strip()
    }
    return tuple(sorted(values))


def _is_effective_at(path: OperationalContextEvidencePath, *, cutoff: datetime) -> bool:
    if path.effective_from is not None and path.effective_from > cutoff:
        return False
    return path.effective_to is None or cutoff < path.effective_to


def _snapshot_identity(
    *,
    target_resource_id: str,
    cutoff: datetime,
    recorded_at: datetime,
    clock_identity: str,
    require_verified_links: bool,
    catalog_versions: tuple[tuple[str, str], ...],
    evidence_links: tuple[OperationalContextEvidenceLink, ...],
    evidence_paths: tuple[OperationalContextEvidencePath, ...],
    temporal_exclusions: tuple[OperationalContextEvidencePath, ...],
    source_freshness: tuple[SourceFreshness, ...],
    stale_sources: tuple[str, ...],
    conflicts: tuple[str, ...],
) -> str:
    payload = {
        "catalog_versions": catalog_versions,
        "conflicts": conflicts,
        "clock_identity": clock_identity,
        "cutoff": _utc_timestamp(cutoff),
        "evidence_links": tuple(_evidence_link_identity(item) for item in evidence_links),
        "evidence_paths": _path_identities(evidence_paths),
        "temporal_exclusions": _path_identities(temporal_exclusions),
        "source_freshness": tuple(
            (
                item.source,
                _utc_timestamp(item.observed_at),
                item.max_age_seconds,
            )
            for item in source_freshness
        ),
        "stale_sources": stale_sources,
        "target_resource_id": target_resource_id,
        "recorded_at": _utc_timestamp(recorded_at),
        "require_verified_links": require_verified_links,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _path_identities(
    paths: Sequence[OperationalContextEvidencePath],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            item.object_id,
            item.object_type,
            item.revision,
            _utc_timestamp(item.effective_from) if item.effective_from is not None else None,
            _utc_timestamp(item.effective_to) if item.effective_to is not None else None,
            item.provenance_refs,
            tuple(_evidence_link_identity(link) for link in item.links),
        )
        for item in paths
    )


def _evidence_link_identity(link: OperationalContextEvidenceLink) -> tuple[object, ...]:
    metadata = link.observation_metadata
    return (
        link.link_type,
        link.from_id,
        link.to_id,
        metadata.to_mapping() if metadata is not None else None,
    )


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["OperationalContextMaterializer"]
