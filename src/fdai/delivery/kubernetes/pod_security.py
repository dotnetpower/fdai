"""UID-grounded Kubernetes Pod Security admission candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

_VIOLATIONS: Final = frozenset(
    {"allow_privilege_escalation", "capabilities_drop_all", "run_as_non_root", "seccomp_profile"}
)


def pod_security_mismatch_findings(
    resources: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
    evidence_cutoff: datetime,
    window: timedelta = timedelta(minutes=5),
) -> tuple[dict[str, Any], ...]:
    """Join recent restricted-profile rejections to one exact Deployment owner."""

    if not evidence_complete or evidence_cutoff.tzinfo is None or window <= timedelta(0):
        return ()
    lower_bound = evidence_cutoff - window
    index = _index(resources)
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for event in events:
        regarding = event.get("regarding")
        violations = event.get("pod_security_violations")
        observed_at = _timestamp(event.get("last_seen"))
        if (
            event.get("code") != "pod_security_admission_rejected"
            or event.get("pod_security_profile") != "restricted"
            or not isinstance(regarding, Mapping)
            or regarding.get("kind") != "ReplicaSet"
            or not isinstance(violations, list)
            or not violations
            or any(item not in _VIOLATIONS for item in violations)
            or observed_at is None
            or observed_at < lower_bound
            or observed_at > evidence_cutoff
        ):
            continue
        replica_identity = (
            "ReplicaSet",
            str(event.get("namespace") or ""),
            str(regarding.get("name") or ""),
            str(regarding.get("uid") or ""),
        )
        replicas = index.get(replica_identity, ())
        if len(replicas) != 1:
            continue
        replica = replicas[0]
        if replica.get("owner_reference_projection_complete") is not True:
            continue
        owners = [
            item
            for item in _mappings(replica.get("owner_references"))
            if item.get("controller") is True and item.get("kind") == "Deployment"
        ]
        if len(owners) != 1:
            continue
        owner = owners[0]
        deployment_identity = (
            "Deployment",
            replica_identity[1],
            str(owner.get("name") or ""),
            str(owner.get("uid") or ""),
        )
        deployments = index.get(deployment_identity, ())
        if len(deployments) != 1 or deployment_identity in seen:
            continue
        deployment = deployments[0]
        desired = deployment.get("desired")
        ready = deployment.get("ready")
        if (
            not isinstance(desired, int)
            or isinstance(desired, bool)
            or not isinstance(ready, int)
            or isinstance(ready, bool)
            or desired <= ready
        ):
            continue
        seen.add(deployment_identity)
        findings.append(
            {
                "reason": "pod_security_restricted_workload_mismatch_candidate",
                "resource": _finding_identity(deployment_identity),
                "affected_resource": _finding_identity(replica_identity),
                "pod_security_profile": "restricted",
                "pod_security_version": str(event.get("pod_security_version") or "")[:32],
                "pod_security_violations": sorted(set(violations)),
                "source_paths": ["/spec/template/spec"],
                "last_seen": observed_at.isoformat(),
                "evidence_strength": "recent_rejection_and_exact_uid_owner_chain",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings[:32])


def _index(
    resources: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for resource in resources:
        identity = (
            str(resource.get("kind") or ""),
            str(resource.get("namespace") or ""),
            str(resource.get("name") or ""),
            str(resource.get("uid") or ""),
        )
        if all(identity):
            grouped.setdefault(identity, []).append(resource)
    return {key: tuple(values) for key, values in grouped.items()}


def _finding_identity(identity: tuple[str, str, str, str]) -> dict[str, str]:
    return {"kind": identity[0], "namespace": identity[1], "name": identity[2], "uid": identity[3]}


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["pod_security_mismatch_findings"]
