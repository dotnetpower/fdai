"""Render focused AKS scheduled-job values for standalone deployment."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_AKS_RESOURCE_ID = re.compile(
    r"/subscriptions/[^/]+/resourcegroups/[^/]+/providers/"
    r"microsoft\.containerservice/managedclusters/[^/]+",
    re.IGNORECASE,
)
_SERVICE_ACCOUNT_ROOT = "/var/run/secrets/kubernetes.io/serviceaccount"


def build_aks_scheduled_job(
    refs: dict[str, Any],
    identity: dict[str, Any],
    command: list[str],
    schedule: str,
    environment: Mapping[str, object],
    secret_environment: Mapping[str, str],
    *,
    component: str,
    deadline_seconds: int,
    retry_limit: int = 1,
    suspend: bool = False,
) -> dict[str, object]:
    """Build one runtime-neutral scheduled or suspended AKS job value."""

    image = refs.get("core-control-plane")
    if not isinstance(image, str):
        raise TypeError("AKS scheduled job image is unavailable")
    return {
        "component": component,
        "image": image,
        "identity_resource_id": identity["resource_id"],
        "identity_client_id": identity["client_id"],
        "command": command,
        "args": [],
        "schedule": schedule,
        "suspend": suspend,
        "deadline_seconds": deadline_seconds,
        "retry_limit": retry_limit,
        "cpu": "500m",
        "memory": "1Gi",
        "environment": {name: str(value) for name, value in environment.items()},
        "secret_environment": secret_environment,
    }


def aks_inventory_binding_environment(cluster_id: str) -> dict[str, str]:
    """Bind inventory to its in-cluster read-only ServiceAccount projection."""

    normalized_cluster_id = cluster_id.strip()
    if _AKS_RESOURCE_ID.fullmatch(normalized_cluster_id) is None:
        raise ValueError("AKS runtime cluster id is invalid")
    return {
        "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.default.svc",
        "FDAI_KUBERNETES_CLUSTER_REF": normalized_cluster_id,
        "FDAI_KUBERNETES_AUTH_MODE": "service-account",
        "FDAI_KUBERNETES_CA_PATH": f"{_SERVICE_ACCOUNT_ROOT}/ca.crt",
        "FDAI_KUBERNETES_TOKEN_PATH": f"{_SERVICE_ACCOUNT_ROOT}/token",
    }


def aks_kubernetes_direct_api_environment(
    cluster_id: str,
    *,
    namespace: str,
) -> dict[str, str]:
    """Bind namespace-limited Kubernetes effects to the isolated Executor."""

    normalized_cluster_id = cluster_id.strip()
    if _AKS_RESOURCE_ID.fullmatch(normalized_cluster_id) is None:
        raise ValueError("AKS runtime cluster id is invalid")
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace):
        raise ValueError("AKS runtime namespace is invalid")
    return {
        "FDAI_KUBERNETES_DIRECT_API_JSON": json.dumps(
            {
                "allowed_namespaces": [namespace],
                "api_server": "https://kubernetes.default.svc",
                "ca_path": f"{_SERVICE_ACCOUNT_ROOT}/ca.crt",
                "cluster_ref": normalized_cluster_id,
                "token_path": f"{_SERVICE_ACCOUNT_ROOT}/token",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    }


__all__ = [
    "aks_inventory_binding_environment",
    "aks_kubernetes_direct_api_environment",
    "build_aks_scheduled_job",
]
