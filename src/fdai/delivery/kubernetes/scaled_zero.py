"""Kubernetes scaled-to-zero Service backend candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def scaled_zero_backend_findings(
    resources: Sequence[Mapping[str, Any]], *, evidence_complete: bool
) -> tuple[dict[str, Any], ...]:
    """Join an endpoint-empty Service to one exact zero-replica workload."""

    if not evidence_complete:
        return ()
    findings: list[dict[str, Any]] = []
    for service in sorted(resources, key=_identity):
        selector = service.get("selector")
        if (
            service.get("kind") != "Service"
            or service.get("service_type") == "ExternalName"
            or service.get("selector_projection_complete") is not True
            or service.get("endpoint_projection_complete") is not True
            or service.get("ready_endpoints") != 0
            or not isinstance(selector, Mapping)
            or not selector
        ):
            continue
        candidates = [
            workload
            for workload in resources
            if workload.get("kind") in {"Deployment", "StatefulSet"}
            and workload.get("namespace") == service.get("namespace")
            and workload.get("desired") == 0
            and isinstance((template := workload.get("pod_template")), Mapping)
            and template.get("label_projection_complete") is True
            and template.get("labels") == selector
        ]
        if len(candidates) != 1:
            continue
        workload = candidates[0]
        findings.append(
            {
                "reason": "service_backend_scaled_to_zero_candidate",
                "resource": {
                    "kind": str(workload.get("kind") or "")[:128],
                    "namespace": str(workload.get("namespace") or "")[:253],
                    "name": str(workload.get("name") or "")[:253],
                },
                "service": {
                    "namespace": str(service.get("namespace") or "")[:253],
                    "name": str(service.get("name") or "")[:253],
                },
                "desired": 0,
                "ready_endpoints": 0,
                "source_paths": ["/spec/replicas", "/service/spec/selector"],
                "evidence_strength": "complete_endpoint_and_exact_selector_join",
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


__all__ = ["scaled_zero_backend_findings"]
