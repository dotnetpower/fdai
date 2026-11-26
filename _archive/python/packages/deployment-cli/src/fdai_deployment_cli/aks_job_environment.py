"""Render protected AKS Job environment bindings without resolving runtime values."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


def protected_environment_sources(value: object) -> list[dict[str, Any]]:
    """Validate and detach envFrom bindings without changing their retained contract."""
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or any(not isinstance(key, str) for key in item)
        for item in value
    ):
        raise ValueError("protected AKS Job envFrom contract is invalid")
    return copy.deepcopy(value)


def protected_environment_entries(
    *,
    component: str,
    template_name: str,
    environment: Mapping[str, str],
    secret_environment: Mapping[str, str],
    field_environment: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Validate the canary field binding and render the same sorted template env contract."""
    if field_environment and (
        component != "canary"
        or field_environment
        != {"FDAI_CANARY_JOB_UID": "metadata.labels['batch.kubernetes.io/controller-uid']"}
        or set(field_environment) & (set(environment) | set(secret_environment))
    ):
        raise ValueError("protected AKS canary Job identity field reference is invalid")
    entries: list[dict[str, Any]] = [
        {"name": name, "value": environment[name]} for name in sorted(environment)
    ]
    entries.extend(
        {
            "name": name,
            "valueFrom": {
                "secretKeyRef": {
                    "name": f"{template_name}-job",
                    "key": name,
                }
            },
        }
        for name in sorted(secret_environment)
    )
    entries.extend(
        {
            "name": name,
            "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": field_environment[name]}},
        }
        for name in sorted(field_environment)
    )
    entries.sort(key=lambda entry: str(entry["name"]))
    return entries
