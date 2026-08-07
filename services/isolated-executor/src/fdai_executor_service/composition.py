"""Provider composition owned by the isolated Executor distribution."""

from __future__ import annotations

import os

import httpx

from fdai.delivery.azure.gateway_direct_api import (
    AzureGatewayDirectApiConfig,
    AzureGatewayDirectApiExecutor,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.persistence import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
    PostgresIdempotencyStore,
    PostgresIdempotencyStoreConfig,
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.shared.providers.idempotency import IdempotencyStore
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity
from fdai_executor_service.effect_executor import ServiceDirectApiEffectExecutor


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


def build_audit_store() -> StateStore:
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


def build_idempotency_store() -> IdempotencyStore:
    """Bind the durable exactly-once effect ledger."""

    dsn = os.environ.get("FDAI_IDEMPOTENCY_DSN", "").strip() or _required("FDAI_STATE_STORE_DSN")
    return PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn=dsn))


def build_direct_api_effect_executor(
    *,
    audit_store: StateStore,
    resource_lock: ResourceLock,
    idempotency: IdempotencyStore,
    http_client: httpx.AsyncClient,
    identity: WorkloadIdentity,
) -> ServiceDirectApiEffectExecutor:
    """Bind the provider adapter behind the service-owned safety executor."""

    gateway = AzureGatewayDirectApiExecutor(
        config=AzureGatewayDirectApiConfig(
            base_url=_required("FDAI_DEV_OPERATIONS_GATEWAY_URL"),
            audience=_required("FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE"),
        ),
        identity=identity,
        http_client=http_client,
    )
    return ServiceDirectApiEffectExecutor(
        executor=gateway,
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency,
        allow_enforce=True,
    )


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
    "build_workload_identity",
    "new_http_client",
]
