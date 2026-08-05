"""Deterministic Kubernetes custom owner relationship findings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_WORKLOAD_KINDS = frozenset({"DaemonSet", "Deployment", "ReplicaSet", "StatefulSet"})


def custom_owner_degradation_findings(
    resources: Sequence[Mapping[str, Any]],
    owners: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Report UID-grounded custom owners with degraded direct workload children."""

    if not evidence_complete:
        return ()
    owners_by_uid = {
        str(owner.get("uid")): owner
        for owner in owners
        if owner.get("custom_resource") is True and owner.get("uid")
    }
    degraded: dict[str, list[dict[str, Any]]] = {}
    for workload in resources:
        if (
            workload.get("kind") not in _WORKLOAD_KINDS
            or workload.get("owner_reference_projection_complete") is not True
            or _count(workload.get("desired")) <= _count(workload.get("ready"))
        ):
            continue
        controller_uids = {
            str(reference.get("uid"))
            for reference in _mappings(workload.get("owner_references"))
            if reference.get("controller") is True and reference.get("uid") in owners_by_uid
        }
        if len(controller_uids) != 1:
            continue
        owner_uid = controller_uids.pop()
        degraded.setdefault(owner_uid, []).append(
            {
                "kind": str(workload.get("kind") or "")[:128],
                "name": str(workload.get("name") or "")[:253],
                "namespace": str(workload.get("namespace") or "")[:253],
                "desired": _count(workload.get("desired")),
                "ready": _count(workload.get("ready")),
            }
        )
    findings: list[dict[str, Any]] = []
    for owner_uid, workloads in sorted(degraded.items()):
        owner = owners_by_uid[owner_uid]
        findings.append(
            {
                "reason": "custom_owner_has_degraded_workload",
                "resource": {
                    "kind": str(owner.get("kind") or "")[:128],
                    "name": str(owner.get("name") or "")[:253],
                    "namespace": str(owner.get("namespace") or "")[:253],
                    "uid": owner_uid[:128],
                },
                "degraded_workloads": sorted(
                    workloads,
                    key=lambda item: (item["kind"], item["namespace"], item["name"]),
                ),
                "evidence_strength": "direct_owner_reference",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings[:32])


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["custom_owner_degradation_findings"]
