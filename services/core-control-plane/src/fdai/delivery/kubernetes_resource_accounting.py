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


@dataclass(frozen=True, slots=True)
class PodResourceRequests:
    cpu_millicores: int
    memory_bytes: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.cpu_millicores, bool)
            or isinstance(self.memory_bytes, bool)
            or not 0 <= self.cpu_millicores <= MAX_RESOURCE_QUANTITY
            or not 0 <= self.memory_bytes <= MAX_RESOURCE_QUANTITY
        ):
            raise KubernetesResourceAccountingError(
                "PodResourceRequests cpu_millicores and memory_bytes "
                "MUST be bounded non-negative integers"
            )


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
    if "resources" in spec or "resize" in status:
        raise KubernetesResourceAccountingError("Pod-level or resize accounting is unsupported")
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
    # Newer clusters report allocated resources and a Pod-level status for every running Pod.
    # Without a resize in progress they equal the declared requests, so a difference is refused.
    _verify_reported_resources(status.get("containerStatuses", []), containers, app_requests)
    _verify_reported_resources(
        status.get("initContainerStatuses", []), init_containers, init_requests
    )
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


def _verify_reported_resources(
    statuses: object, containers: list[Any], requests: list[PodResourceRequests]
) -> None:
    declared = {
        _mapping(container).get("name"): request
        for container, request in zip(containers, requests, strict=True)
    }
    for raw_status in _items(statuses):
        status = _mapping(raw_status)
        if "allocatedResourcesStatus" in status:
            raise KubernetesResourceAccountingError("Container resize accounting is unsupported")
        reported = []
        if "allocatedResources" in status:
            reported.append(_quantities(status["allocatedResources"]))
        if "resources" in status:
            reported.append(_quantities(_mapping(status["resources"]).get("requests", {})))
        if not reported:
            continue
        expected = declared.get(status.get("name"))
        if expected is None or any(
            quantities.get("cpu", 0) != expected.cpu_millicores
            or quantities.get("memory", 0) != expected.memory_bytes
            for quantities in reported
        ):
            raise KubernetesResourceAccountingError("Container resize accounting is unsupported")


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
