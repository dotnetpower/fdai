"""UID-grounded init-container dependency wait candidates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")


def init_dependency_wait_findings(
    resources: Sequence[Mapping[str, Any]],
    service_receipts: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Join one running init dependency to an exact targeted absence receipt."""

    if not evidence_complete:
        return ()
    index = _index(resources)
    receipts = _receipt_index(service_receipts)
    findings: list[dict[str, Any]] = []
    for pod in sorted(resources, key=_identity):
        if pod.get("kind") != "Pod" or pod.get("init_status_projection_complete") is not True:
            continue
        running = [
            item
            for item in _mappings(pod.get("init_containers"))
            if item.get("state") == "running" and isinstance(item.get("name"), str)
        ]
        if len(running) != 1:
            continue
        chain = _chain(pod, index)
        if chain is None:
            continue
        replica, workload = chain
        candidates = [
            _dependency_container(resource, running[0]["name"])
            for resource in (pod, replica, workload)
        ]
        if any(candidate is None for candidate in candidates):
            continue
        exact = [candidate for candidate in candidates if candidate is not None]
        if any(candidate != exact[0] for candidate in exact[1:]):
            continue
        container = exact[0]
        dependency = container["dependency"]
        identity = (dependency["namespace"], dependency["name"])
        matches = receipts.get(identity, ())
        if len(matches) != 1 or matches[0].get("status") != "confirmed_absent":
            continue
        findings.append(
            {
                "reason": "workload_init_container_missing_service_candidate",
                "resource": _finding_identity(_identity(workload)),
                "affected_pod": _finding_identity(_identity(pod)),
                "init_container": container["name"],
                "dependency": {"kind": "Service", **dependency},
                "source_paths": ["/spec/template/spec/initContainers/command"],
                "evidence_strength": "exact_uid_chain_command_fingerprint_and_targeted_absence",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings[:32])


def _dependency_container(resource: Mapping[str, Any], name: object) -> dict[str, Any] | None:
    template_key = "pod_spec" if resource.get("kind") == "Pod" else "pod_template"
    template = resource.get(template_key)
    if not isinstance(template, Mapping) or template.get("projection_complete") is not True:
        return None
    matches = [
        item for item in _mappings(template.get("init_containers")) if item.get("name") == name
    ]
    if len(matches) != 1:
        return None
    container = matches[0]
    digest = container.get("command_sha256")
    dependencies = _mappings(container.get("service_dependencies"))
    if (
        not isinstance(digest, str)
        or _SHA256.fullmatch(digest) is None
        or container.get("wait_loop") is not True
        or len(dependencies) != 1
    ):
        return None
    namespace = dependencies[0].get("namespace")
    service = dependencies[0].get("service")
    if (
        not isinstance(namespace, str)
        or not namespace
        or not isinstance(service, str)
        or not service
    ):
        return None
    return {
        "name": str(name)[:253],
        "command_sha256": digest,
        "dependency": {"namespace": namespace[:253], "name": service[:253]},
    }


def _chain(
    pod: Mapping[str, Any],
    index: Mapping[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]],
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    replica = _owner(pod, index, "ReplicaSet")
    if replica is None:
        return None
    workload = _owner(replica, index, "Deployment")
    return (replica, workload) if workload is not None else None


def _owner(
    resource: Mapping[str, Any],
    index: Mapping[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]],
    kind: str,
) -> Mapping[str, Any] | None:
    if resource.get("owner_reference_projection_complete") is not True:
        return None
    owners = [
        item
        for item in _mappings(resource.get("owner_references"))
        if item.get("controller") is True
    ]
    if len(owners) != 1 or owners[0].get("kind") != kind:
        return None
    identity = (
        kind,
        str(resource.get("namespace") or ""),
        str(owners[0].get("name") or ""),
        str(owners[0].get("uid") or ""),
    )
    matches = index.get(identity, ())
    return matches[0] if len(matches) == 1 else None


def _index(
    resources: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for resource in resources:
        identity = _identity(resource)
        if all(identity):
            grouped.setdefault(identity, []).append(resource)
    return {key: tuple(value) for key, value in grouped.items()}


def _receipt_index(
    receipts: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for receipt in receipts:
        identity = (str(receipt.get("namespace") or ""), str(receipt.get("name") or ""))
        if all(identity):
            grouped.setdefault(identity, []).append(receipt)
    return {key: tuple(value) for key, value in grouped.items()}


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(value.get("kind") or ""),
        str(value.get("namespace") or ""),
        str(value.get("name") or ""),
        str(value.get("uid") or ""),
    )


def _finding_identity(identity: tuple[str, str, str, str]) -> dict[str, str]:
    return {"kind": identity[0], "namespace": identity[1], "name": identity[2], "uid": identity[3]}


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["init_dependency_wait_findings"]
