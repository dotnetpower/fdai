"""Kubernetes ineffective HPA metric candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from fdai.delivery.kubernetes.quantity import parse_quantity

_METRIC_FAILURES: Final = frozenset({"FailedGetResourceMetric", "FailedComputeMetricsReplicas"})


def hpa_missing_cpu_request_findings(
    resources: Sequence[Mapping[str, Any]], *, evidence_complete: bool
) -> tuple[dict[str, Any], ...]:
    """Join one inactive CPU-utilization HPA to missing workload CPU requests."""

    if not evidence_complete:
        return ()
    index = _index(resources)
    findings: list[dict[str, Any]] = []
    for hpa in sorted(resources, key=_identity):
        if (
            hpa.get("kind") != "HorizontalPodAutoscaler"
            or hpa.get("projection_complete") is not True
            or hpa.get("metrics_projection_complete") is not True
            or not any(
                metric.get("type") == "Resource"
                and metric.get("resource") == "cpu"
                and metric.get("target_type") == "Utilization"
                for metric in _mappings(hpa.get("metrics"))
            )
        ):
            continue
        conditions = [
            item
            for item in _mappings(hpa.get("conditions"))
            if item.get("type") == "ScalingActive"
            and item.get("status") == "False"
            and item.get("reason") in _METRIC_FAILURES
        ]
        target = hpa.get("scale_target")
        if len(conditions) != 1 or not isinstance(target, Mapping):
            continue
        identity = (
            str(target.get("kind") or ""),
            str(hpa.get("namespace") or ""),
            str(target.get("name") or ""),
        )
        workloads = index.get(identity, ())
        if len(workloads) != 1:
            continue
        workload = workloads[0]
        template = workload.get("pod_template")
        if not isinstance(template, Mapping) or template.get("projection_complete") is not True:
            continue
        missing: list[dict[str, str]] = []
        for container_index, container in enumerate(_mappings(template.get("containers"))):
            if container.get("resource_projection_complete") is not True:
                missing = []
                break
            requests = container.get("resources")
            request_values = requests.get("requests") if isinstance(requests, Mapping) else None
            raw_cpu = request_values.get("cpu") if isinstance(request_values, Mapping) else None
            quantity = parse_quantity(raw_cpu) if isinstance(raw_cpu, str) else None
            if quantity is not None and quantity > 0:
                continue
            path = f"/spec/template/spec/containers/{container_index}/resources/requests/cpu"
            missing.append(
                {"container": str(container.get("name") or "")[:253], "source_path": path}
            )
        if not missing:
            continue
        findings.append(
            {
                "reason": "hpa_cpu_utilization_missing_request_candidate",
                "resource": {"kind": identity[0], "namespace": identity[1], "name": identity[2]},
                "hpa": {
                    "namespace": str(hpa.get("namespace") or "")[:253],
                    "name": str(hpa.get("name") or "")[:253],
                    "condition_reason": str(conditions[0].get("reason") or "")[:256],
                    "metric": "cpu",
                    "target_type": "Utilization",
                },
                "missing_requests": missing,
                "source_paths": [item["source_path"] for item in missing],
                "evidence_strength": "inactive_metric_and_complete_target_template",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings[:32])


def _index(
    resources: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for resource in resources:
        grouped.setdefault(_identity(resource), []).append(resource)
    return {key: tuple(items) for key, items in grouped.items()}


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(value.get("kind") or ""),
        str(value.get("namespace") or ""),
        str(value.get("name") or ""),
    )


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["hpa_missing_cpu_request_findings"]
