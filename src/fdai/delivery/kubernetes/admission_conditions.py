"""Deterministic Kubernetes admission condition evidence semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def admission_condition_findings(
    resources: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Return direct admission condition findings without assigning causal authority."""

    if not evidence_complete:
        return ()
    findings: list[dict[str, Any]] = []
    for resource in sorted(resources, key=_identity):
        if resource.get("admission_condition_projection_complete") is not True:
            continue
        for condition in _mappings(resource.get("admission_conditions")):
            code = condition.get("code")
            source_index = condition.get("source_index")
            if not isinstance(code, str) or not isinstance(source_index, int):
                continue
            finding: dict[str, Any] = {
                "reason": f"kubernetes_condition_{code}",
                "resource": {
                    "kind": str(resource.get("kind") or "")[:128],
                    "name": str(resource.get("name") or "")[:253],
                    "namespace": str(resource.get("namespace") or "")[:253],
                },
                "source_paths": [f"/status/conditions/{source_index}"],
                "condition_type": str(condition.get("type") or "")[:128],
                "condition_reason": str(condition.get("reason") or "")[:256],
                "evidence_strength": "direct_resource_condition",
                "causality": "candidate_only",
                "decision": "hold",
            }
            for key in (
                "webhook_name",
                "pod_security_profile",
                "pod_security_version",
                "pod_security_violations",
            ):
                if value := condition.get(key):
                    finding[key] = value
            findings.append(finding)
    return tuple(findings[:32])


def _identity(resource: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(resource.get("kind") or ""),
        str(resource.get("namespace") or ""),
        str(resource.get("name") or ""),
    )


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["admission_condition_findings"]
