"""Kubernetes missing ConfigMap mount candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def missing_configmap_mount_findings(
    resources: Sequence[Mapping[str, Any]],
    configmap_receipts: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Join one mounted ConfigMap volume to an exact targeted absence receipt."""

    if not evidence_complete:
        return ()
    receipts = _receipts(configmap_receipts)
    findings: list[dict[str, Any]] = []
    for workload in sorted(resources, key=_identity):
        template = workload.get("pod_template")
        desired = workload.get("desired")
        ready = workload.get("ready")
        if (
            workload.get("kind") not in {"Deployment", "StatefulSet"}
            or not isinstance(desired, int)
            or isinstance(desired, bool)
            or not isinstance(ready, int)
            or isinstance(ready, bool)
            or ready >= desired
            or not isinstance(template, Mapping)
            or template.get("projection_complete") is not True
            or template.get("volume_projection_complete") is not True
        ):
            continue
        containers = _mappings(template.get("containers"))
        if any(item.get("volume_mount_projection_complete") is not True for item in containers):
            continue
        mounted = {
            str(mount.get("name") or "")
            for container in containers
            for mount in _mappings(container.get("volume_mounts"))
            if mount.get("name")
        }
        missing: list[tuple[int, str, str]] = []
        for index, volume in enumerate(_mappings(template.get("volumes"))):
            volume_name = volume.get("name")
            configmap_name = volume.get("configmap_name")
            identity = (str(workload.get("namespace") or ""), str(configmap_name or ""))
            matches = receipts.get(identity, ())
            if (
                volume_name in mounted
                and isinstance(configmap_name, str)
                and configmap_name
                and len(matches) == 1
                and matches[0].get("status") == "confirmed_absent"
            ):
                missing.append((index, str(volume_name), configmap_name))
        if len(missing) != 1:
            continue
        index, volume_name, configmap_name = missing[0]
        findings.append(
            {
                "reason": "workload_missing_configmap_mount_candidate",
                "resource": {
                    "kind": str(workload.get("kind") or "")[:128],
                    "namespace": str(workload.get("namespace") or "")[:253],
                    "name": str(workload.get("name") or "")[:253],
                },
                "volume": volume_name[:253],
                "configmap": {
                    "namespace": str(workload.get("namespace") or "")[:253],
                    "name": configmap_name[:253],
                },
                "desired": desired,
                "ready": ready,
                "source_paths": [f"/spec/template/spec/volumes/{index}/configMap/name"],
                "evidence_strength": "complete_mount_join_and_targeted_absence",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings[:32])


def _receipts(
    values: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for value in values:
        identity = (str(value.get("namespace") or ""), str(value.get("name") or ""))
        if all(identity):
            grouped.setdefault(identity, []).append(value)
    return {key: tuple(items) for key, items in grouped.items()}


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(value.get("kind") or ""),
        str(value.get("namespace") or ""),
        str(value.get("name") or ""),
    )


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["missing_configmap_mount_findings"]
