"""Read-only point-in-time resource prerequisites, never scheduler or storage effects."""

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.delivery.kubernetes_quantity import MAX_RESOURCE_QUANTITY, parse_resource_quantity
from fdai.delivery.kubernetes_resource_accounting import PodResourceRequests, pod_resource_requests


def snapshot_has_capacity(
    nodes: Sequence[Mapping[str, Any]],
    pods: Sequence[Mapping[str, Any]],
    required: PodResourceRequests,
) -> bool:
    """Check complete bound snapshots for one ordinary Linux/amd64 Pod's resource requests.

    Pending unassigned work and unsupported accounting withhold a result via ValueError.
    Eligible nodes must be ready, schedulable, untainted and not deleting. Capacity rounds
    down while Pod requests round up. This does not reserve resources or simulate scheduling.
    """
    available: dict[str, tuple[int, int, int]] = {}
    names: set[str] = set()
    for node in nodes:
        metadata = mapping(node.get("metadata"))
        name = text(metadata.get("name"))
        if name in names:
            raise ValueError("Resource preflight found duplicate nodes")
        names.add(name)
        spec, status = mapping(node.get("spec")), mapping(node.get("status"))
        unschedulable = spec.get("unschedulable", False)
        taints = spec.get("taints", [])
        if type(unschedulable) is not bool or not isinstance(taints, list):
            raise ValueError("Resource preflight node scheduling evidence is malformed")
        conditions = status.get("conditions")
        if not isinstance(conditions, list):
            raise ValueError("Resource preflight node readiness is missing")
        ready = [
            mapping(item).get("status")
            for item in conditions
            if mapping(item).get("type") == "Ready"
        ]
        if len(ready) != 1 or ready[0] not in ("True", "False", "Unknown"):
            raise ValueError("Resource preflight node readiness is ambiguous")
        labels = mapping(metadata.get("labels", {}))
        if (
            unschedulable
            or taints
            or metadata.get("deletionTimestamp")
            or ready[0] != "True"
            or labels.get("kubernetes.io/os") != "linux"
            or labels.get("kubernetes.io/arch") != "amd64"
        ):
            continue
        allocatable = mapping(status.get("allocatable"))
        available[name] = (
            _floor_units(allocatable.get("cpu"), scale=1000),
            _floor_units(allocatable.get("memory")),
            _floor_units(allocatable.get("pods")),
        )
    consumed: dict[str, tuple[int, int, int]] = {}
    for pod in pods:
        phase = mapping(pod.get("status")).get("phase")
        if phase in ("Succeeded", "Failed"):
            continue
        if phase not in ("Pending", "Running"):
            raise ValueError("Resource preflight Pod lifecycle is unknown")
        node_name = text(mapping(pod.get("spec")).get("nodeName"))
        if node_name not in names:
            raise ValueError("Resource preflight Pod assignment is incomplete")
        requests = pod_resource_requests(pod)
        cpu, memory, slots = consumed.get(node_name, (0, 0, 0))
        consumed[node_name] = (
            cpu + requests.cpu_millicores,
            memory + requests.memory_bytes,
            slots + 1,
        )
    return any(
        cpu - consumed.get(name, (0, 0, 0))[0] >= required.cpu_millicores
        and memory - consumed.get(name, (0, 0, 0))[1] >= required.memory_bytes
        and slots - consumed.get(name, (0, 0, 0))[2] >= 1
        for name, (cpu, memory, slots) in available.items()
    )


def storage_is_bound(
    claim: Mapping[str, Any],
    volume: Mapping[str, Any],
    *,
    namespace: str,
    name: str,
    claim_uid: str,
    storage_class: str,
    required_bytes: int,
) -> bool:
    """Require exact reciprocal PVC/PV identity and existing filesystem capacity, not durability."""
    metadata, spec, status = (mapping(claim.get(field)) for field in ("metadata", "spec", "status"))
    if (
        metadata.get("uid") != claim_uid
        or metadata.get("name") != name
        or metadata.get("namespace") != namespace
    ):
        raise ValueError("Resource preflight claim identity changed")
    volume_meta, volume_spec, volume_status = (
        mapping(volume.get(field)) for field in ("metadata", "spec", "status")
    )
    text(volume_meta.get("uid"))
    reference = mapping(volume_spec.get("claimRef"))
    if (
        spec.get("volumeName") != volume_meta.get("name")
        or reference.get("uid") != claim_uid
        or reference.get("name") != name
        or reference.get("namespace") != namespace
        or reference.get("kind", "PersistentVolumeClaim") != "PersistentVolumeClaim"
        or reference.get("apiVersion", "v1") != "v1"
    ):
        raise ValueError("Resource preflight volume binding is inconsistent")
    for resource_spec in (spec, volume_spec):
        if (
            resource_spec.get("storageClassName") != storage_class
            or resource_spec.get("volumeMode", "Filesystem") != "Filesystem"
            or not isinstance(resource_spec.get("accessModes"), list)
            or "ReadWriteOnce" not in resource_spec["accessModes"]
        ):
            raise ValueError("Resource preflight volume profile is unsupported")
    if metadata.get("deletionTimestamp") or volume_meta.get("deletionTimestamp"):
        raise ValueError("Resource preflight volume is deleting")
    if status.get("phase") != "Bound" or volume_status.get("phase") != "Bound":
        raise ValueError("Resource preflight volume is not bound")
    if (
        status.get("conditions")
        or status.get("allocatedResourceStatuses")
        or status.get("allocatedResources")
    ):
        raise ValueError("Resource preflight volume resize state is unsupported")
    requested = mapping(mapping(spec.get("resources")).get("requests")).get("storage")
    capacities = [
        parse_resource_quantity(value)
        for value in (
            requested,
            mapping(status.get("capacity")).get("storage"),
            mapping(volume_spec.get("capacity")).get("storage"),
        )
    ]
    if capacities[0] > min(capacities[1:]):
        raise ValueError("Resource preflight volume capacity has not caught up with its request")
    return all(value >= required_bytes for value in capacities)


def mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Resource preflight requires structured evidence")
    return value


def text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("Resource preflight requires bounded identity text")
    return value


def _floor_units(value: object, *, scale: int = 1) -> int:
    numerator, denominator = parse_resource_quantity(value).as_integer_ratio()
    result = numerator * scale // denominator
    if result > MAX_RESOURCE_QUANTITY:
        raise ValueError("Resource preflight capacity exceeds its accounting bound")
    return result
