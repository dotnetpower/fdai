"""Provider composition owned by the isolated Executor distribution."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

import httpx
from fdai_service_contracts.executor import (
    DirectApiExecutor,
    IdempotencyStore,
    ResourceLock,
    WorkloadIdentity,
)

from fdai_executor_service.adapters.gateway_direct_api import (
    AzureGatewayDirectApiConfig,
    AzureGatewayDirectApiExecutor,
)
from fdai_executor_service.adapters.postgres_idempotency import (
    PostgresIdempotencyStore,
    PostgresIdempotencyStoreConfig,
)
from fdai_executor_service.adapters.postgres_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai_executor_service.adapters.postgres_safeguard_bundle import (
    PostgresSafeguardBundleStore,
    PostgresSafeguardBundleStoreConfig,
)
from fdai_executor_service.adapters.postgres_state import (
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai_executor_service.adapters.workload_identity import ManagedIdentityWorkloadIdentity
from fdai_executor_service.effect_executor import ServiceDirectApiEffectExecutor
from fdai_executor_service.ports import ExecutorStateStore


def new_http_client() -> httpx.AsyncClient:
    """Create the bounded HTTP client shared by identity and effect adapters."""

    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0),
        follow_redirects=False,
    )


def build_workload_identity(
    http_client: httpx.AsyncClient,
    *,
    client_id_env: str,
    require_client_id: bool,
) -> WorkloadIdentity:
    """Bind the dedicated managed identity without a Core runtime helper."""

    if require_client_id and not os.environ.get(client_id_env, "").strip():
        raise RuntimeError(f"{client_id_env} MUST identify the dedicated workload identity")
    return ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        client_id_env=client_id_env,
    )


def build_audit_store() -> ExecutorStateStore:
    """Bind the durable Executor state and audit store."""

    dsn = _required("FDAI_STATE_STORE_DSN")
    return PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))


def build_resource_lock() -> ResourceLock:
    """Bind the cross-replica PostgreSQL logical-target lock."""

    dsn = os.environ.get("FDAI_RESOURCE_LOCK_DSN", "").strip() or _required("FDAI_STATE_STORE_DSN")
    raw_timeout = os.environ.get("FDAI_RESOURCE_LOCK_TIMEOUT_MS", "").strip()
    try:
        timeout_ms = int(raw_timeout) if raw_timeout else 30_000
    except ValueError as exc:
        raise RuntimeError("FDAI_RESOURCE_LOCK_TIMEOUT_MS MUST be an integer") from exc
    if timeout_ms < 0:
        raise RuntimeError("FDAI_RESOURCE_LOCK_TIMEOUT_MS MUST be non-negative")
    return PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(
            dsn=dsn,
            lock_timeout_ms=timeout_ms,
        )
    )


def build_idempotency_store() -> PostgresIdempotencyStore:
    """Bind the durable exactly-once effect ledger."""

    dsn = os.environ.get("FDAI_IDEMPOTENCY_DSN", "").strip() or _required("FDAI_STATE_STORE_DSN")
    return PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn=dsn))


def build_safeguard_bundle_store() -> PostgresSafeguardBundleStore:
    """Bind authoritative read-only access to Core's persisted bundles."""

    return PostgresSafeguardBundleStore(
        config=PostgresSafeguardBundleStoreConfig(dsn=_required("FDAI_STATE_STORE_DSN"))
    )


def build_direct_api_effect_executor(
    *,
    audit_store: ExecutorStateStore,
    resource_lock: ResourceLock,
    idempotency: IdempotencyStore,
    http_client: httpx.AsyncClient,
    identities: Mapping[str, WorkloadIdentity],
) -> ServiceDirectApiEffectExecutor:
    """Bind the provider adapter behind the service-owned safety executor."""

    gateway_url = os.environ.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", "").strip()
    gateway_audience = os.environ.get("FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE", "").strip()
    if bool(gateway_url) != bool(gateway_audience):
        raise RuntimeError("isolated Executor gateway URL and audience MUST be configured together")
    gateway: DirectApiExecutor | None = None
    if gateway_url:
        gateway = AzureGatewayDirectApiExecutor(
            config=AzureGatewayDirectApiConfig(
                base_url=gateway_url,
                audience=gateway_audience,
            ),
            identities=identities,
            http_client=http_client,
        )
    kubernetes = _build_kubernetes_direct_api(identities=identities)
    executor: DirectApiExecutor | None = gateway
    if kubernetes is not None:
        from fdai_executor_service.adapters.kubernetes_direct_api import (
            KubernetesDirectApiRouter,
        )

        executor = KubernetesDirectApiRouter(kubernetes, gateway)
    if executor is None:
        raise RuntimeError("isolated Executor authority cutover requires a direct-API adapter")

    from fdai_executor_service.adapters.entra_membership import EntraMembershipClient
    from fdai_executor_service.adapters.postgres_human_access import PostgresHumanAccessSource
    from fdai_executor_service.human_access import IsolatedHumanAccessExecutor
    from fdai_executor_service.human_access_binding import (
        HumanAccessDirectApiRouter,
        human_access_role_groups,
        require_human_access_identity,
    )

    role_groups = human_access_role_groups(os.environ)
    if role_groups is not None:
        require_human_access_identity(os.environ)
        human_identity = build_workload_identity(
            http_client, client_id_env="FDAI_HUMAN_ACCESS_MI_CLIENT_ID", require_client_id=True
        )
        human = IsolatedHumanAccessExecutor(
            source=PostgresHumanAccessSource(_required("FDAI_STATE_STORE_DSN"), role_groups),
            graph=EntraMembershipClient(
                http_client, human_identity, frozenset(role_groups.values())
            ),
            store=audit_store,
        )
        executor = HumanAccessDirectApiRouter(human, executor)
    return ServiceDirectApiEffectExecutor(
        executor=executor,
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency,
        allow_enforce=True,
    )


def _build_kubernetes_direct_api(
    *,
    identities: Mapping[str, WorkloadIdentity] | None = None,
) -> DirectApiExecutor | None:
    raw = os.environ.get("FDAI_KUBERNETES_DIRECT_API_JSON", "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FDAI_KUBERNETES_DIRECT_API_JSON MUST be valid JSON") from exc
    common = {"api_server", "cluster_ref", "allowed_namespaces"}
    accepted = [
        common | {credential, certificate}
        for credential in ("token_path", "audience")
        for certificate in ("ca_path", "ca_pem")
    ]
    if not isinstance(value, dict) or set(value) not in accepted:
        raise RuntimeError(
            "FDAI_KUBERNETES_DIRECT_API_JSON MUST contain api_server, cluster_ref, "
            "allowed_namespaces, exactly one of token_path or audience, "
            "and exactly one of ca_path or ca_pem"
        )
    namespaces = value["allowed_namespaces"]
    if (
        not isinstance(namespaces, list)
        or not namespaces
        or any(not isinstance(item, str) for item in namespaces)
    ):
        raise RuntimeError("Kubernetes allowed_namespaces MUST be a non-empty string array")
    text_fields = {name: value[name] for name in set(value) - {"allowed_namespaces"}}
    if any(
        not isinstance(item, str) or not item or (name != "ca_pem" and item != item.strip())
        for name, item in text_fields.items()
    ):
        raise RuntimeError("Kubernetes direct-API text settings MUST be non-empty strings")
    from fdai_executor_service.adapters.kubernetes_direct_api import (
        KubernetesDirectApiConfig,
        KubernetesDirectApiExecutor,
    )

    try:
        return KubernetesDirectApiExecutor(
            config=KubernetesDirectApiConfig(
                api_server=str(value["api_server"]),
                cluster_ref=str(value["cluster_ref"]),
                token_path=Path(str(value["token_path"])) if "token_path" in value else None,
                ca_path=Path(str(value["ca_path"])) if "ca_path" in value else None,
                allowed_namespaces=frozenset(namespaces),
                audience=str(value["audience"]) if "audience" in value else None,
                ca_pem=str(value["ca_pem"]) if "ca_pem" in value else None,
            ),
            identities=identities,
        )
    except ValueError as exc:
        raise RuntimeError("Kubernetes direct API configuration is invalid") from exc


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} MUST be configured for the isolated Executor")
    return value


__all__ = [
    "build_audit_store",
    "build_direct_api_effect_executor",
    "build_idempotency_store",
    "build_resource_lock",
    "build_safeguard_bundle_store",
    "build_workload_identity",
    "new_http_client",
]
