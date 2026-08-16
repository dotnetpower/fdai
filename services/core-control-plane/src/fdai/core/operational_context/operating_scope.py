"""Project operating-scope service coverage without inventing a service identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai.shared.providers.ontology_instance import OntologyLinkRecord
from fdai.shared.providers.operating_model import OperatingModelSnapshot

UNMAPPED_SERVICE_REF = "unknown_service"

_SERVICE_TYPE = "BusinessService"
_WORKLOAD_TYPE = "Workload"
_RESOURCE_TYPE = "Resource"
_SERVICE_TO_WORKLOAD = "implemented_by"
_WORKLOAD_TO_RESOURCE = "workload_runs_on"


@dataclass(frozen=True, slots=True)
class ResourceScopeCoverage:
    """One observed resource and the reviewed services that actually reach it."""

    resource_id: str
    workload_ids: tuple[str, ...]
    service_ids: tuple[str, ...]
    service_ref: str

    @property
    def mapped(self) -> bool:
        return self.service_ref != UNMAPPED_SERVICE_REF

    @property
    def conflicting(self) -> bool:
        return len(self.service_ids) > 1


@dataclass(frozen=True, slots=True)
class OperatingScopeCoverage:
    """Complete, read-only scope coverage for one operating model snapshot."""

    source_revision: str
    resources: tuple[ResourceScopeCoverage, ...]

    @property
    def unmapped_resource_ids(self) -> tuple[str, ...]:
        return tuple(item.resource_id for item in self.resources if not item.mapped)

    @property
    def complete(self) -> bool:
        return not self.unmapped_resource_ids


def project_operating_scope(snapshot: OperatingModelSnapshot) -> OperatingScopeCoverage:
    """Report every resource's reviewed service, or the explicit unmapped marker.

    A resource that no reviewed service reaches keeps ``UNMAPPED_SERVICE_REF``. It is
    never dropped from the projection and never attached to a synthetic service.
    """

    by_type: dict[str, set[str]] = {}
    for item in snapshot.objects:
        if item.object_type in (_SERVICE_TYPE, _WORKLOAD_TYPE, _RESOURCE_TYPE):
            by_type.setdefault(item.object_type, set()).add(item.id)
    services = by_type.get(_SERVICE_TYPE, set())
    if UNMAPPED_SERVICE_REF in services:
        raise ValueError(
            f"{UNMAPPED_SERVICE_REF} is a reserved unmapped marker and MUST NOT be a service id"
        )
    workloads = by_type.get(_WORKLOAD_TYPE, set())
    resources = by_type.get(_RESOURCE_TYPE, set())

    services_by_workload = _adjacency(
        snapshot.links,
        link_type=_SERVICE_TO_WORKLOAD,
        from_ids=services,
        to_ids=workloads,
    )
    workloads_by_resource = _adjacency(
        snapshot.links,
        link_type=_WORKLOAD_TO_RESOURCE,
        from_ids=workloads,
        to_ids=resources,
    )

    coverage: list[ResourceScopeCoverage] = []
    for resource_id in sorted(resources):
        workload_ids = tuple(sorted(workloads_by_resource.get(resource_id, ())))
        service_ids = tuple(
            sorted(
                {service for item in workload_ids for service in services_by_workload.get(item, ())}
            )
        )
        coverage.append(
            ResourceScopeCoverage(
                resource_id=resource_id,
                workload_ids=workload_ids,
                service_ids=service_ids,
                service_ref=service_ids[0] if len(service_ids) == 1 else UNMAPPED_SERVICE_REF,
            )
        )
    return OperatingScopeCoverage(
        source_revision=snapshot.source_revision,
        resources=tuple(coverage),
    )


def _adjacency(
    links: Sequence[OntologyLinkRecord],
    *,
    link_type: str,
    from_ids: set[str],
    to_ids: set[str],
) -> Mapping[str, set[str]]:
    """Index declared endpoints only; an unknown or wrong-typed endpoint is ignored."""

    index: dict[str, set[str]] = {}
    for link in links:
        if link.link_type != link_type or link.from_id not in from_ids or link.to_id not in to_ids:
            continue
        index.setdefault(link.to_id, set()).add(link.from_id)
    return index


__all__ = [
    "UNMAPPED_SERVICE_REF",
    "OperatingScopeCoverage",
    "ResourceScopeCoverage",
    "project_operating_scope",
]
