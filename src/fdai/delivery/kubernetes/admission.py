"""Deterministic Kubernetes admission mutation evidence semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from fdai.delivery.kubernetes.quantity import parse_quantity

_WORKLOAD_KINDS = frozenset({"DaemonSet", "Deployment", "StatefulSet"})


def mutating_webhook_resource_drift_findings(
    resources: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Attribute Pod resource drift only to one unscoped global Pod mutator."""

    if not evidence_complete:
        return ()
    pods_by_namespace: dict[str, list[Mapping[str, Any]]] = {}
    mutators: list[tuple[Mapping[str, Any], int, Mapping[str, Any]]] = []
    for resource in resources:
        if resource.get("kind") == "Pod":
            pods_by_namespace.setdefault(str(resource.get("namespace") or ""), []).append(resource)
        elif (
            resource.get("kind") == "MutatingWebhookConfiguration"
            and resource.get("projection_complete") is True
        ):
            for index, webhook in enumerate(_mappings(resource.get("webhooks"))):
                if _eligible_global_pod_mutator(webhook):
                    mutators.append((resource, index, webhook))
    if len(mutators) != 1:
        return ()

    configuration, webhook_index, webhook = mutators[0]
    drifts: list[dict[str, Any]] = []
    for workload in resources:
        if workload.get("kind") not in _WORKLOAD_KINDS:
            continue
        selector = workload.get("selector")
        template = workload.get("pod_template")
        if (
            not isinstance(selector, Mapping)
            or selector.get("projection_complete") is not True
            or not isinstance(template, Mapping)
            or template.get("projection_complete") is not True
        ):
            continue
        desired = _container_resources(template.get("containers"))
        if desired is None:
            continue
        for pod in pods_by_namespace.get(str(workload.get("namespace") or ""), []):
            labels = pod.get("labels")
            pod_spec = pod.get("pod_spec")
            if (
                not isinstance(labels, Mapping)
                or labels.get("projection_complete") is not True
                or not _selector_matches(selector, labels)
                or not isinstance(pod_spec, Mapping)
                or pod_spec.get("projection_complete") is not True
            ):
                continue
            actual = _container_resources(pod_spec.get("containers"))
            if actual is None:
                continue
            changed = sorted(
                name for name in desired.keys() & actual.keys() if desired[name] != actual[name]
            )
            if changed:
                drifts.append(
                    {
                        "workload": str(workload.get("name") or "")[:253],
                        "pod": str(pod.get("name") or "")[:253],
                        "containers": changed,
                    }
                )
    if not drifts:
        return ()
    return (
        {
            "reason": "mutating_webhook_rewrites_pod_resources",
            "resource": {
                "kind": "MutatingWebhookConfiguration",
                "name": str(configuration.get("name") or "")[:253],
                "namespace": "",
            },
            "source_paths": [f"/webhooks/{webhook_index}"],
            "webhook_name": str(webhook.get("name") or "")[:253],
            "drifts": drifts[:16],
            "decision": "hold",
        },
    )


def _eligible_global_pod_mutator(webhook: Mapping[str, Any]) -> bool:
    if webhook.get("projection_complete") is not True:
        return False
    if webhook.get("object_selector") or webhook.get("namespace_selector"):
        return False
    return any(
        "CREATE" in _strings(rule.get("operations"))
        and any(resource in {"pods", "pods/*"} for resource in _strings(rule.get("resources")))
        for rule in _mappings(webhook.get("rules"))
    )


def _container_resources(value: object) -> dict[str, tuple[tuple[str, str, str], ...]] | None:
    containers = _mappings(value)
    if not containers:
        return None
    projected: dict[str, tuple[tuple[str, str, str], ...]] = {}
    for container in containers:
        name = container.get("name")
        resources = container.get("resources")
        if not isinstance(name, str) or not isinstance(resources, Mapping):
            return None
        normalized = _normalized_resources(resources)
        if normalized is None or name in projected:
            return None
        projected[name] = normalized
    return projected


def _normalized_resources(
    resources: Mapping[str, Any],
) -> tuple[tuple[str, str, str], ...] | None:
    values: list[tuple[str, str, str]] = []
    for section in ("requests", "limits"):
        raw_section = resources.get(section)
        if raw_section is None:
            continue
        if not isinstance(raw_section, Mapping):
            return None
        for resource_name in ("cpu", "memory"):
            raw_value = raw_section.get(resource_name)
            if raw_value is None:
                continue
            if not isinstance(raw_value, str) or (quantity := parse_quantity(raw_value)) is None:
                return None
            if not isinstance(quantity, Decimal) or quantity < 0:
                return None
            values.append((section, resource_name, str(quantity)))
    return tuple(sorted(values))


def _selector_matches(selector: Mapping[str, Any], labels: Mapping[str, Any]) -> bool:
    match_labels = selector.get("match_labels")
    label_values = labels.get("values")
    if not isinstance(match_labels, Mapping) or not isinstance(label_values, Mapping):
        return False
    return all(label_values.get(key) == value for key, value in match_labels.items())


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["mutating_webhook_resource_drift_findings"]
