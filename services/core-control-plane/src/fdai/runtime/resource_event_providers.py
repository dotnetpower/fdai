"""Compose server-owned Azure and Kubernetes Resource event readers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai.core.ontology_platform.resource_event_queries import (
    KUBERNETES_EVENT_FAMILY,
    RESOURCE_HEALTH_EVENT_FAMILY,
    ResourceEventCollectionReader,
)
from fdai.delivery.azure.resource_event_history import (
    AzureResourceEventHistoryConfig,
    AzureResourceEventHistoryReader,
)
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiAuth,
    ServiceAccountTokenAuth,
    WorkloadIdentityKubernetesAuth,
)
from fdai.delivery.kubernetes_lifecycle_source import (
    KubernetesLifecycleSourceConfig,
    KubernetesLifecycleWatchSource,
)
from fdai.delivery.kubernetes_resource_event_history import (
    KubernetesResourceEventHistoryConfig,
    KubernetesResourceEventHistoryReader,
)
from fdai.delivery.resource_event_history import CompositeResourceEventHistoryReader

_KUBERNETES_BINDING_KEYS = (
    "FDAI_KUBERNETES_API_SERVER",
    "FDAI_KUBERNETES_CLUSTER_REF",
    "FDAI_KUBERNETES_TOKEN_PATH",
    "FDAI_KUBERNETES_CA_PATH",
    "FDAI_KUBERNETES_CA_PEM",
    "FDAI_KUBERNETES_AUTH_MODE",
    "FDAI_KUBERNETES_AUDIENCE",
)


@dataclass(frozen=True, slots=True)
class _KubernetesBinding:
    """One validated, credential-bound Kubernetes API endpoint identity."""

    auth: KubernetesApiAuth
    api_server: str
    cluster_ref: str
    ca_path: Path | None
    ca_pem: str | None


def _bind_kubernetes_api(
    *,
    environment: Mapping[str, str],
    identity: Any,
) -> _KubernetesBinding | None:
    """Parse and validate the shared Kubernetes binding env vars, or return `None`.

    Fails fast (raises) on partial configuration so a misconfigured deployment never
    silently falls back to an unauthenticated or wrongly scoped reader.
    """

    values = {key: environment.get(key, "").strip() for key in _KUBERNETES_BINDING_KEYS}
    if not any(values.values()):
        return None
    api_server = values["FDAI_KUBERNETES_API_SERVER"]
    cluster_ref = values["FDAI_KUBERNETES_CLUSTER_REF"]
    token_path = values["FDAI_KUBERNETES_TOKEN_PATH"]
    ca_path = values["FDAI_KUBERNETES_CA_PATH"]
    ca_pem = values["FDAI_KUBERNETES_CA_PEM"]
    auth_mode = values["FDAI_KUBERNETES_AUTH_MODE"] or ("service-account" if token_path else "")
    audience = values["FDAI_KUBERNETES_AUDIENCE"]
    if not api_server or not cluster_ref or not auth_mode or not (ca_path or ca_pem):
        raise RuntimeError(
            "Kubernetes event history requires API server, cluster ref, auth mode, and CA"
        )
    if ca_path and ca_pem:
        raise RuntimeError("Kubernetes event history accepts exactly one CA binding")
    auth: KubernetesApiAuth
    if auth_mode == "workload-identity":
        if identity is None or not audience or token_path:
            raise RuntimeError("Kubernetes event workload identity binding is incomplete")
        auth = WorkloadIdentityKubernetesAuth(identity=identity, audience=audience)
    elif auth_mode == "service-account":
        if not token_path or audience:
            raise RuntimeError("Kubernetes event service-account binding is incomplete")
        auth = ServiceAccountTokenAuth(Path(token_path))
    else:
        raise RuntimeError("FDAI_KUBERNETES_AUTH_MODE is invalid")
    return _KubernetesBinding(
        auth=auth,
        api_server=api_server,
        cluster_ref=cluster_ref,
        ca_path=Path(ca_path) if ca_path else None,
        ca_pem=ca_pem or None,
    )


def build_resource_event_history_reader(
    *,
    environment: Mapping[str, str],
    identity: Any = None,
    http_client: Any = None,
) -> ResourceEventCollectionReader | None:
    """Bind each available event family behind one scope-preserving reader."""

    readers: dict[str, ResourceEventCollectionReader] = {}
    subscription_id = environment.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if identity is not None and http_client is not None and subscription_id:
        readers[RESOURCE_HEALTH_EVENT_FAMILY] = AzureResourceEventHistoryReader(
            identity=identity,
            http_client=http_client,
            config=AzureResourceEventHistoryConfig(subscription_id=subscription_id),
        )
    kubernetes = build_kubernetes_resource_event_history_reader(
        environment=environment,
        identity=identity,
    )
    if kubernetes is not None:
        readers[KUBERNETES_EVENT_FAMILY] = kubernetes
    return CompositeResourceEventHistoryReader(readers=readers) if readers else None


def build_kubernetes_resource_event_history_reader(
    *,
    environment: Mapping[str, str],
    identity: Any = None,
) -> KubernetesResourceEventHistoryReader | None:
    """Bind one Kubernetes Event source or fail fast on partial configuration."""

    binding = _bind_kubernetes_api(environment=environment, identity=identity)
    if binding is None:
        return None
    return KubernetesResourceEventHistoryReader(
        auth=binding.auth,
        config=KubernetesResourceEventHistoryConfig(
            api_server=binding.api_server,
            cluster_ref=binding.cluster_ref,
            ca_path=binding.ca_path,
            ca_pem=binding.ca_pem,
        ),
    )


def build_kubernetes_lifecycle_source(
    *,
    environment: Mapping[str, str],
    identity: Any = None,
) -> KubernetesLifecycleWatchSource | None:
    """Bind one durable, resumable Kubernetes lifecycle Event source.

    Reuses the same `_KUBERNETES_BINDING_KEYS` env vars and credential validation as
    `build_kubernetes_resource_event_history_reader`, so a deployment configures
    Kubernetes API access once for both the on-demand Event reader and this bounded,
    cursor-resumable lifecycle collector source. Returns `None` when unconfigured, and
    fails fast (raises) on partial configuration, matching the sibling builder.
    """

    binding = _bind_kubernetes_api(environment=environment, identity=identity)
    if binding is None:
        return None
    return KubernetesLifecycleWatchSource(
        auth=binding.auth,
        config=KubernetesLifecycleSourceConfig(
            api_server=binding.api_server,
            cluster_ref=binding.cluster_ref,
            ca_path=binding.ca_path,
            ca_pem=binding.ca_pem,
        ),
    )


__all__ = [
    "build_kubernetes_lifecycle_source",
    "build_kubernetes_resource_event_history_reader",
    "build_resource_event_history_reader",
]
