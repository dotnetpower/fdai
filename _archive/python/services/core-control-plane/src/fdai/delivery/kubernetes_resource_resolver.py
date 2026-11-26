"""Resolve one exact Kubernetes Resource from bounded inventory evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.shared.providers.inventory import ResourceRecord


class KubernetesResourceResolutionStatus(StrEnum):
    """Disposition of one exact Kubernetes Resource selector."""

    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class KubernetesResourceResolution:
    """Bounded resolution result that never substitutes a name for UID identity."""

    status: KubernetesResourceResolutionStatus
    resource: ResourceRecord | None
    candidate_count: int
    complete: bool
    reason: str | None

    def __post_init__(self) -> None:
        if isinstance(self.candidate_count, bool) or self.candidate_count < 0:
            raise ValueError("Kubernetes resolver candidate_count MUST be non-negative")
        if not isinstance(self.complete, bool):
            raise ValueError("Kubernetes resolver complete MUST be a boolean")
        if self.status is KubernetesResourceResolutionStatus.RESOLVED and (
            self.resource is None or self.candidate_count != 1 or not self.complete
        ):
            raise ValueError("resolved Kubernetes resource requires one complete candidate")


def resolve_kubernetes_resource(
    resources: tuple[ResourceRecord, ...],
    *,
    cluster_ref: str,
    resource_type: str,
    namespace: str | None,
    name: str,
    uid: str | None = None,
    resource_version: str | None = None,
    complete: bool,
) -> KubernetesResourceResolution:
    """Resolve one current or retained UID under an exact cluster and kind."""

    for field_name, value in (
        ("cluster_ref", cluster_ref),
        ("resource_type", resource_type),
        ("name", name),
    ):
        if not value.strip() or len(value) > 512:
            raise ValueError(f"Kubernetes resolver {field_name} MUST be bounded non-empty text")
    if namespace is not None and (not namespace.strip() or len(namespace) > 253):
        raise ValueError("Kubernetes resolver namespace MUST be bounded non-empty text or null")
    if uid is not None and (not uid.strip() or len(uid) > 512):
        raise ValueError("Kubernetes resolver uid MUST be bounded non-empty text or null")
    if resource_version is not None and (
        not resource_version.strip() or len(resource_version) > 512
    ):
        raise ValueError(
            "Kubernetes resolver resource_version MUST be bounded non-empty text or null"
        )
    if not complete:
        return KubernetesResourceResolution(
            status=KubernetesResourceResolutionStatus.UNAVAILABLE,
            resource=None,
            candidate_count=0,
            complete=False,
            reason="inventory_scope_incomplete",
        )

    candidates = tuple(
        resource
        for resource in resources
        if resource.type == resource_type
        and resource.props.get("cluster_ref") == cluster_ref
        and resource.props.get("namespace") == namespace
        and resource.props.get("name") == name
        and (uid is None or resource.props.get("uid") == uid)
        and (resource_version is None or resource.props.get("resource_version") == resource_version)
    )
    if not candidates:
        return KubernetesResourceResolution(
            status=KubernetesResourceResolutionStatus.NOT_FOUND,
            resource=None,
            candidate_count=0,
            complete=True,
            reason=None,
        )
    if len(candidates) > 1:
        return KubernetesResourceResolution(
            status=KubernetesResourceResolutionStatus.AMBIGUOUS,
            resource=None,
            candidate_count=len(candidates),
            complete=False,
            reason="selector_matches_multiple_uids",
        )
    return KubernetesResourceResolution(
        status=KubernetesResourceResolutionStatus.RESOLVED,
        resource=candidates[0],
        candidate_count=1,
        complete=True,
        reason=None,
    )


__all__ = [
    "KubernetesResourceResolution",
    "KubernetesResourceResolutionStatus",
    "resolve_kubernetes_resource",
]
