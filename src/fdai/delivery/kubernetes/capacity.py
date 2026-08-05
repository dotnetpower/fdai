"""Deterministic Kubernetes request-versus-capacity evidence semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from fdai.delivery.kubernetes.quantity import parse_quantity

_RESOURCE_NAMES = ("cpu", "memory")


def project_pod_resource_requests(spec: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project aggregate Pod requests without retaining unrelated container data."""

    containers = _mappings(spec.get("containers"))
    init_containers = _mappings(spec.get("initContainers"))
    if not containers and not init_containers:
        return None
    projected: dict[str, Any] = {"projection_complete": True, "source_paths": {}}
    for resource_name in _RESOURCE_NAMES:
        request = _pod_resource_request(
            containers=containers,
            init_containers=init_containers,
            resource_name=resource_name,
        )
        if request is None:
            projected["projection_complete"] = False
            continue
        value, paths = request
        if value > 0:
            projected[f"{resource_name}_base_units"] = str(value)
            projected["source_paths"][resource_name] = paths
    return projected


def capacity_exceeds_ceiling_findings(
    resources: Sequence[Mapping[str, Any]],
    *,
    events: Sequence[Mapping[str, Any]],
    nodes: Sequence[Mapping[str, Any]],
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Return hold-only structural findings for requests above every eligible Node."""

    if not evidence_complete:
        return ()
    eligible_nodes = [
        node
        for node in nodes
        if node.get("ready") is True and node.get("unschedulable") is not True
    ]
    if not eligible_nodes or any(
        node.get("allocatable_projection_complete") is not True for node in eligible_nodes
    ):
        return ()
    pods_by_identity: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for resource in resources:
        if resource.get("kind") == "Pod":
            pods_by_identity.setdefault(_identity(resource), []).append(resource)

    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in sorted(events, key=lambda item: str(item.get("last_seen") or "")):
        if event.get("reason") != "FailedScheduling":
            continue
        regarding = event.get("regarding")
        if not isinstance(regarding, Mapping):
            continue
        identity = _identity(regarding)
        matching_pods = pods_by_identity.get(identity, ())
        if len(matching_pods) != 1 or identity in seen:
            continue
        pod = matching_pods[0]
        event_uid = regarding.get("uid")
        if not isinstance(event_uid, str) or not event_uid or event_uid != pod.get("uid"):
            continue
        requests = pod.get("resource_requests")
        if not isinstance(requests, Mapping) or requests.get("projection_complete") is not True:
            continue
        source_paths = requests.get("source_paths")
        if not isinstance(source_paths, Mapping):
            continue
        exceeded: list[dict[str, str]] = []
        finding_paths: list[str] = []
        for resource_name in _RESOURCE_NAMES:
            requested = _decimal(requests.get(f"{resource_name}_base_units"))
            capacities = _node_capacities(eligible_nodes, resource_name)
            if requested is None or capacities is None or requested <= max(capacities):
                continue
            paths = source_paths.get(resource_name)
            if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                return ()
            exceeded.append(
                {
                    "resource": resource_name,
                    "requested_base_units": str(requested),
                    "largest_node_base_units": str(max(capacities)),
                }
            )
            finding_paths.extend(paths)
        if not exceeded:
            continue
        seen.add(identity)
        findings.append(
            {
                "reason": "pod_resource_request_exceeds_node_capacity",
                "resource": {
                    "kind": "Pod",
                    "name": identity[2],
                    "namespace": identity[1],
                },
                "source_paths": sorted(finding_paths),
                "exceeded_resources": exceeded,
                "eligible_node_count": len(eligible_nodes),
                "event_reason": "FailedScheduling",
                "decision": "hold",
            }
        )
    return tuple(findings)


def _pod_resource_request(
    *,
    containers: Sequence[Mapping[str, Any]],
    init_containers: Sequence[Mapping[str, Any]],
    resource_name: str,
) -> tuple[Decimal, list[str]] | None:
    regular_total = Decimal(0)
    init_maximum = Decimal(0)
    paths: list[str] = []
    for group, source_group, projected_containers in (
        ("containers", "containers", containers),
        ("init_containers", "initContainers", init_containers),
    ):
        for index, container in enumerate(projected_containers):
            resources = container.get("resources")
            requests = resources.get("requests") if isinstance(resources, Mapping) else None
            raw_value = requests.get(resource_name) if isinstance(requests, Mapping) else None
            if raw_value is None:
                continue
            if not isinstance(raw_value, str) or (value := parse_quantity(raw_value)) is None:
                return None
            if value < 0:
                return None
            paths.append(f"/spec/{source_group}/{index}/resources/requests/{resource_name}")
            if group == "containers":
                regular_total += value
            else:
                init_maximum = max(init_maximum, value)
    return max(regular_total, init_maximum), paths


def _node_capacities(
    nodes: Sequence[Mapping[str, Any]],
    resource_name: str,
) -> list[Decimal] | None:
    capacities: list[Decimal] = []
    for node in nodes:
        allocatable = node.get("allocatable")
        raw_value = allocatable.get(resource_name) if isinstance(allocatable, Mapping) else None
        if not isinstance(raw_value, str) or (value := parse_quantity(raw_value)) is None:
            return None
        if value < 0:
            return None
        capacities.append(value)
    return capacities or None


def _decimal(value: object) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = Decimal(value)
    except ArithmeticError:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _identity(resource: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(resource.get("kind") or ""),
        str(resource.get("namespace") or ""),
        str(resource.get("name") or ""),
    )


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["capacity_exceeds_ceiling_findings", "project_pod_resource_requests"]
