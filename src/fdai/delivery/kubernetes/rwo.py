"""Kubernetes ReadWriteOnce placement conflict candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def rwo_anti_affinity_findings(
    resources: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Correlate mounted RWO claims with required hostname anti-affinity."""

    if not evidence_complete:
        return ()
    claims: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for resource in resources:
        if resource.get("kind") == "PersistentVolumeClaim":
            claims.setdefault(
                (str(resource.get("namespace") or ""), str(resource.get("name") or "")),
                [],
            ).append(resource)
    findings: list[dict[str, Any]] = []
    for workload in sorted(resources, key=_identity):
        template = workload.get("pod_template")
        desired = workload.get("desired")
        ready = workload.get("ready")
        if (
            workload.get("kind") not in {"Deployment", "StatefulSet"}
            or not isinstance(desired, int)
            or isinstance(desired, bool)
            or desired <= 1
            or not isinstance(ready, int)
            or isinstance(ready, bool)
            or ready >= desired
            or not isinstance(template, Mapping)
            or template.get("projection_complete") is not True
            or template.get("volume_projection_complete") is not True
            or template.get("anti_affinity_projection_complete") is not True
        ):
            continue
        labels = template.get("labels")
        anti_affinity = [
            item
            for item in _mappings(template.get("required_pod_anti_affinity"))
            if item.get("topology_key") == "kubernetes.io/hostname"
            and item.get("selector_match_labels") == labels
        ]
        if len(anti_affinity) != 1:
            continue
        mounted = {
            str(item.get("name") or "")
            for container in _mappings(template.get("containers"))
            if container.get("volume_mount_projection_complete") is True
            for item in _mappings(container.get("volume_mounts"))
            if item.get("name")
        }
        if any(
            container.get("volume_mount_projection_complete") is not True
            for container in _mappings(template.get("containers"))
        ):
            continue
        for volume in _mappings(template.get("volumes")):
            claim_name = volume.get("claim_name")
            volume_name = volume.get("name")
            matching_claims = claims.get(
                (str(workload.get("namespace") or ""), str(claim_name or "")), ()
            )
            if (
                volume_name not in mounted
                or len(matching_claims) != 1
                or matching_claims[0].get("projection_complete") is not True
                or "ReadWriteOnce" not in _strings(matching_claims[0].get("access_modes"))
            ):
                continue
            findings.append(
                {
                    "reason": "workload_rwo_claim_anti_affinity_conflict_candidate",
                    "resource": {
                        "kind": str(workload.get("kind") or "")[:128],
                        "namespace": str(workload.get("namespace") or "")[:253],
                        "name": str(workload.get("name") or "")[:253],
                    },
                    "claim": {"name": str(claim_name)[:253], "access_mode": "ReadWriteOnce"},
                    "desired": desired,
                    "ready": ready,
                    "topology_key": "kubernetes.io/hostname",
                    "source_paths": [
                        "/spec/template/spec/affinity/podAntiAffinity/requiredDuringSchedulingIgnoredDuringExecution",
                        "/spec/template/spec/volumes",
                    ],
                    "evidence_strength": "complete_structural_constraint_join",
                    "causality": "candidate_only",
                    "decision": "hold",
                }
            )
    return tuple(findings[:32])


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(value.get("kind") or ""),
        str(value.get("namespace") or ""),
        str(value.get("name") or ""),
    )


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


__all__ = ["rwo_anti_affinity_findings"]
