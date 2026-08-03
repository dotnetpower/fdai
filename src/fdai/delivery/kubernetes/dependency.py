"""Deterministic Kubernetes endpoint dependency evidence semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_WORKLOAD_KINDS = frozenset({"DaemonSet", "Deployment", "StatefulSet"})


def missing_service_dependency_findings(
    resources: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Return hold-only findings for exact endpoint references to absent Services."""

    if not evidence_complete:
        return ()
    services = {
        (str(item.get("namespace") or ""), str(item.get("name") or ""))
        for item in resources
        if item.get("kind") == "Service"
    }
    backends: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for item in resources:
        if item.get("kind") in _WORKLOAD_KINDS:
            backends.setdefault(
                (str(item.get("namespace") or ""), str(item.get("name") or "")),
                [],
            ).append(item)

    findings: list[dict[str, Any]] = []
    for workload in sorted(resources, key=_identity):
        if workload.get("kind") not in _WORKLOAD_KINDS:
            continue
        namespace = str(workload.get("namespace") or "")
        template = workload.get("pod_template")
        if not isinstance(template, Mapping) or template.get("projection_complete") is not True:
            continue
        for container_index, container in enumerate(_mappings(template.get("containers"))):
            if container.get("env_projection_complete") is not True:
                continue
            for env_index, env in enumerate(_mappings(container.get("env"))):
                finding = _missing_service_finding(
                    workload=workload,
                    container=container,
                    container_index=container_index,
                    env=env,
                    env_index=env_index,
                    namespace=namespace,
                    services=services,
                    backends=backends,
                )
                if finding is not None:
                    findings.append(finding)
    return tuple(findings)


def _missing_service_finding(
    *,
    workload: Mapping[str, Any],
    container: Mapping[str, Any],
    container_index: int,
    env: Mapping[str, Any],
    env_index: int,
    namespace: str,
    services: set[tuple[str, str]],
    backends: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> dict[str, Any] | None:
    host = env.get("endpoint_host")
    port = env.get("endpoint_port")
    if (
        not isinstance(host, str)
        or "." in host
        or not isinstance(port, str)
        or not port.isdigit()
        or (namespace, host) in services
    ):
        return None
    matching_backends = backends.get((namespace, host), ())
    if len(matching_backends) != 1:
        return None
    backend = matching_backends[0]
    backend_template = backend.get("pod_template")
    if (
        not isinstance(backend_template, Mapping)
        or backend_template.get("projection_complete") is not True
        or _count(backend.get("desired")) < 1
        or _count(backend.get("ready")) < 1
    ):
        return None
    backend_containers = _mappings(backend_template.get("containers"))
    if not backend_containers or any(
        item.get("port_projection_complete") is not True for item in backend_containers
    ):
        return None
    endpoint_port = int(port)
    declared_ports = {
        projected_port.get("port")
        for backend_container in backend_containers
        for projected_port in _mappings(backend_container.get("ports"))
        if isinstance(projected_port.get("port"), int)
        and not isinstance(projected_port.get("port"), bool)
    }
    if endpoint_port not in declared_ports:
        return None
    source_path = f"/spec/template/spec/containers/{container_index}/env/{env_index}/value"
    return {
        "reason": "workload_endpoint_targets_missing_service",
        "resource": {"kind": "Service", "name": host, "namespace": namespace},
        "source_paths": [source_path],
        "referenced_by": {
            "kind": str(workload.get("kind") or "")[:128],
            "name": str(workload.get("name") or "")[:253],
            "container": str(container.get("name") or "")[:253],
            "env": str(env.get("name") or "")[:253],
        },
        "backend": {
            "kind": str(backend.get("kind") or "")[:128],
            "name": str(backend.get("name") or "")[:253],
            "desired": _count(backend.get("desired")),
            "ready": _count(backend.get("ready")),
            "declared_port": endpoint_port,
        },
        "decision": "hold",
    }


def _identity(resource: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(resource.get("kind") or ""),
        str(resource.get("namespace") or ""),
        str(resource.get("name") or ""),
    )


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


__all__ = ["missing_service_dependency_findings"]
