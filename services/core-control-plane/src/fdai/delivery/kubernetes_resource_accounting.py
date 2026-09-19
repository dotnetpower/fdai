"""Conservative CPU/memory requests for the supported ordinary Pod resource profile."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.delivery.kubernetes_quantity import (
    MAX_RESOURCE_QUANTITY,
    cpu_millicores,
    storage_bytes,
)


class KubernetesResourceAccountingError(ValueError):
    """Pod resource evidence cannot be accounted for by the supported profile."""


@dataclass(frozen=True)
class PodResourceRequests:
    cpu_millicores: int
    memory_bytes: int


def pod_resource_requests(pod: Mapping[str, Any]) -> PodResourceRequests:
    """Sum app requests, take per-resource init maxima, then add Pod overhead.

    Inputs are complete API Pods or Pod templates, not normalized diagnostic summaries.
    Absent requests use declared limits, then zero; explicit malformed values never default.
    Each request rounds upward to integer units, so this can overcount fractional bytes.
    Resize declarations/status, restartable init, Pod-level and non-CPU/memory resources are
    unsupported and raise ValueError, as do malformed quantities and accounting overflow.
    The caller owns completeness, cluster identity, freshness, Pod lifecycle and scheduling
    decisions. This helper alone never establishes capacity, placement or authorization.
    """
    spec = _mapping(pod.get("spec"))
    status = _mapping(pod.get("status", {}))
    if "resources" in spec or "resize" in status or "resources" in status:
        raise KubernetesResourceAccountingError("Pod-level or resize accounting is unsupported")
    for field in ("containerStatuses", "initContainerStatuses"):
        for raw_status in _items(status.get(field, [])):
            container_status = _mapping(raw_status)
            if {
                "allocatedResources",
                "resources",
                "allocatedResourcesStatus",
            } & container_status.keys():
                raise KubernetesResourceAccountingError(
                    "Container resize accounting is unsupported"
                )
    for raw_condition in _items(status.get("conditions", [])):
        condition = _mapping(raw_condition)
        if not isinstance(condition.get("type"), str):
            raise KubernetesResourceAccountingError("Pod condition type must be text")
        if condition.get("type") in {"PodResizePending", "PodResizeInProgress"}:
            raise KubernetesResourceAccountingError(
                "Pod resize conditions require separate accounting"
            )

    containers = _items(spec.get("containers"))
    init_containers = _items(spec.get("initContainers", []))
    if not containers or len(containers) + len(init_containers) > 512:
        raise KubernetesResourceAccountingError(
            "Pod container count is invalid or exceeds its bound"
        )
    app_requests = [_container_requests(container) for container in containers]
    init_requests = [_container_requests(container) for container in init_containers]
    overhead = _quantities(spec.get("overhead", {}))
    cpu = max(
        sum(request.cpu_millicores for request in app_requests),
        max((request.cpu_millicores for request in init_requests), default=0),
    ) + overhead.get("cpu", 0)
    memory = max(
        sum(request.memory_bytes for request in app_requests),
        max((request.memory_bytes for request in init_requests), default=0),
    ) + overhead.get("memory", 0)
    if cpu > MAX_RESOURCE_QUANTITY or memory > MAX_RESOURCE_QUANTITY:
        raise KubernetesResourceAccountingError("Pod resource total exceeds the accounting bound")
    return PodResourceRequests(cpu_millicores=cpu, memory_bytes=memory)


def _container_requests(value: object) -> PodResourceRequests:
    container = _mapping(value)
    if {"restartPolicy", "restartPolicyRules", "resizePolicy"} & container.keys():
        raise KubernetesResourceAccountingError(
            "Container restart or resize accounting is unsupported"
        )
    resources = _mapping(container.get("resources", {}))
    if resources.keys() - {"requests", "limits"}:
        raise KubernetesResourceAccountingError("Container resource fields are unsupported")
    requests = _quantities(resources.get("requests", {}))
    limits = _quantities(resources.get("limits", {}))
    return PodResourceRequests(
        cpu_millicores=requests.get("cpu", limits.get("cpu", 0)),
        memory_bytes=requests.get("memory", limits.get("memory", 0)),
    )


def _quantities(value: object) -> dict[str, int]:
    quantities = _mapping(value)
    if quantities.keys() - {"cpu", "memory"}:
        raise KubernetesResourceAccountingError("Only CPU and memory accounting is supported")
    return {
        name: cpu_millicores(raw) if name == "cpu" else storage_bytes(raw)
        for name, raw in quantities.items()
    }


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KubernetesResourceAccountingError("Pod resource evidence requires an object")
    return value


def _items(value: object) -> list[Any]:
    if not isinstance(value, list) or len(value) > 512:
        raise KubernetesResourceAccountingError("Pod resource evidence requires a bounded array")
    return value
