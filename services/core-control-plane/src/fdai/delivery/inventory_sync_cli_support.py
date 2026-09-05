"""Support routines for the inventory reconciliation CLI entry point."""

from __future__ import annotations

import logging
import ssl
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from fdai.delivery.azure.activity_log import AzureActivityLogFactory, AzureActivityLogFactoryConfig
from fdai.delivery.azure.arg_query import AzureArgQueryFactory, AzureArgQueryFactoryConfig
from fdai.delivery.azure.arg_resource_changes import (
    AzureResourceChangeFeed,
    AzureResourceChangeFeedConfig,
    forward_arg_resource_changes,
)
from fdai.delivery.azure.arm_inventory import (
    AzureArmInventoryFactory,
    AzureArmInventoryFactoryConfig,
)
from fdai.delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from fdai.delivery.inventory_delta import forward_inventory_delta
from fdai.delivery.inventory_job_config import InventoryJobConfig, verify_declarative_sha256
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiAuth,
    ServiceAccountTokenAuth,
    WorkloadIdentityKubernetesAuth,
)
from fdai.delivery.kubernetes_lifecycle_collection import KubernetesLifecycleCollector
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import (
    PostgresKubernetesLifecycleConfig,
    PostgresKubernetesLifecycleStore,
)
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.declarative_inventory import (
    DeclarativeInventory,
    DeclarativeInventoryConfig,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import Inventory, LinkRecord, ResourceRecord
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
    InventorySource,
)
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.workload_identity import WorkloadIdentity

_InventoryDeltaForwarder = Callable[..., Awaitable[int]]
_ResourceChangeForwarder = Callable[..., Awaitable[int]]
_WorkloadIdentityFactory = Callable[..., WorkloadIdentity]


def resolve_resource_types(
    config: InventoryJobConfig,
    vocabulary: ResourceTypeRegistry,
) -> tuple[str, ...]:
    """Validate the requested source types against the reviewed registry."""

    resource_types = config.resource_types or tuple(
        item.id for item in vocabulary if item.azure_arm_type is not None
    )
    unknown_types = sorted(set(resource_types) - vocabulary.ids())
    if unknown_types:
        raise ValueError(f"unknown inventory resource types: {', '.join(unknown_types)}")
    if "resource-group" not in resource_types:
        resource_types = ("resource-group", *resource_types)
    return resource_types


def build_sources(
    *,
    config: InventoryJobConfig,
    vocabulary: ResourceTypeRegistry,
    resource_types: tuple[str, ...],
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    started_at: datetime,
) -> tuple[InventorySource, ...]:
    """Build ordered provider sources without granting promotion authority."""

    sources: list[InventorySource] = []
    for source_priority, source_name in enumerate(config.source_order):
        observation_kind = InventoryObservationKind.OBSERVED
        link_types: tuple[str, ...] = (
            "contains",
            "attached_to",
            "depends_on",
            "peered_with",
            "routes_to",
        )
        inventory: Inventory
        if source_name == "arg":
            full_provider_scope = not config.resource_types
            query_factory = AzureArgQueryFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureArgQueryFactoryConfig(
                    subscription_scopes=config.scopes,
                    arg_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                    requests_per_second=config.arg_requests_per_second,
                ),
            )
            query = AzureArmInventoryFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureArmInventoryFactoryConfig(
                    subscription_scopes=config.scopes,
                    arm_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                ),
            ).build_child_overlay_query_fn(query_factory.build_query_fn())
            inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(
                    resource_types=resource_types,
                    subscription_scopes=config.scopes,
                ),
                query=query,
                scope_coverage=(
                    query_factory.build_scope_coverage_fn() if full_provider_scope else None
                ),
                unmapped_resources=(
                    query_factory.build_unmapped_resource_query_fn()
                    if full_provider_scope
                    else None
                ),
                generation_relationships=query_factory.build_generation_relationship_fn(),
            )
        elif source_name == "arm":
            link_types = ("contains",)
            query = AzureArmInventoryFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureArmInventoryFactoryConfig(
                    subscription_scopes=config.scopes,
                    arm_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                ),
            ).build_query_fn()
            inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(
                    resource_types=resource_types,
                    subscription_scopes=config.scopes,
                ),
                query=query,
            )
        else:
            if config.declarative_path is None or config.declarative_sha256 is None:
                raise ValueError("declarative fallback is missing its signed fixture")
            verify_declarative_sha256(config.declarative_path, config.declarative_sha256)
            inventory = DeclarativeInventory(
                DeclarativeInventoryConfig(
                    fixture_path=config.declarative_path,
                    known_resource_types=frozenset(vocabulary.ids()),
                    known_link_types=frozenset(
                        {"contains", "attached_to", "depends_on", "peered_with", "routes_to"}
                    ),
                )
            )
            observation_kind = InventoryObservationKind.EXPECTED
        sources.append(
            InventorySource(
                name=source_name,
                inventory=inventory,
                manifest=InventoryCoverageManifest(
                    source=source_name,
                    scopes=config.scopes,
                    resource_types=resource_types,
                    observation_kind=observation_kind,
                    started_at=started_at,
                    metadata={
                        "source_priority": source_priority,
                        "link_types": link_types,
                        "coverage_scope": (
                            "full_provider_scope"
                            if source_name == "arg" and not config.resource_types
                            else "requested_resource_types"
                        ),
                    },
                ),
            )
        )
    return tuple(sources)


async def forward_recovery_deltas(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    vocabulary: ResourceTypeRegistry,
    http_client: httpx.AsyncClient,
    event_bus: EventBus,
    topic: str,
    scope_lock: ResourceLock,
    forward_inventory_delta_fn: _InventoryDeltaForwarder = forward_inventory_delta,
) -> int:
    """Forward every configured Activity Log cursor without cross-scope coupling."""

    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn))
    published = 0
    for scope in config.scopes:
        async with scope_lock.acquire(f"inventory-recovery-delta:{scope}"):
            activity_fetch = AzureActivityLogFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureActivityLogFactoryConfig(
                    subscription_scope=scope,
                    arg_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                ),
            ).build_fetch_fn()

            async def _noop_query(
                _resource_type: str,
            ) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
                return (), ()

            delta_inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(resource_types=()),
                query=_noop_query,
                delta_fetch=activity_fetch,
            )
            published += await forward_inventory_delta_fn(
                inventory=delta_inventory,
                state_store=state_store,
                event_bus=event_bus,
                topic=topic,
                scope=scope,
            )
    return published


async def forward_resource_changes(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    vocabulary: ResourceTypeRegistry,
    http_client: httpx.AsyncClient,
    event_bus: EventBus,
    topic: str,
    scope_lock: ResourceLock,
    forward_arg_resource_changes_fn: _ResourceChangeForwarder = forward_arg_resource_changes,
) -> int:
    """Forward one bounded resourcechanges poll per configured scope."""

    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn))
    published = 0
    for scope in config.scopes:
        async with scope_lock.acquire(f"inventory-resource-change-feed:{scope}"):
            feed = AzureResourceChangeFeed(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureResourceChangeFeedConfig(
                    subscription_scope=scope,
                    arg_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                    requests_per_second=config.arg_requests_per_second,
                ),
            )
            published += await forward_arg_resource_changes_fn(
                feed=feed,
                state_store=state_store,
                event_bus=event_bus,
                topic=topic,
                scope=scope,
            )
    return published


async def collect_kubernetes_lifecycle(
    config: InventoryJobConfig,
    *,
    logger: logging.Logger,
    workload_identity_factory: _WorkloadIdentityFactory,
) -> int | None:
    """Collect one leased Kubernetes lifecycle window without affecting due-state."""

    if (
        config.kubernetes_api_server is None
        or config.kubernetes_cluster_ref is None
        or config.kubernetes_auth_mode is None
        or (config.kubernetes_ca_path is None and config.kubernetes_ca_pem is None)
    ):
        return 0
    now = datetime.now(UTC)
    holder = f"inventory-lifecycle:{uuid4()}"
    store = PostgresKubernetesLifecycleStore(
        config=PostgresKubernetesLifecycleConfig(dsn=config.dsn)
    )
    try:
        cursor = await store.acquire(
            cluster_ref=config.kubernetes_cluster_ref,
            holder=holder,
            now=now,
            lease_until=now + timedelta(seconds=45),
        )
        if cursor is None:
            return 0
        kubernetes_ssl = ssl.create_default_context(
            cafile=str(config.kubernetes_ca_path) if config.kubernetes_ca_path else None,
            cadata=config.kubernetes_ca_pem,
        )
        async with httpx.AsyncClient() as identity_client:
            identity = workload_identity_factory(http_client=identity_client)
            auth: KubernetesApiAuth
            if config.kubernetes_auth_mode == "workload-identity":
                if config.kubernetes_audience is None:
                    raise RuntimeError("Kubernetes lifecycle workload audience is unavailable")
                auth = WorkloadIdentityKubernetesAuth(
                    identity=identity,
                    audience=config.kubernetes_audience,
                )
            else:
                if config.kubernetes_token_path is None:
                    raise RuntimeError("Kubernetes lifecycle service-account token is unavailable")
                auth = ServiceAccountTokenAuth(config.kubernetes_token_path)
            async with httpx.AsyncClient(verify=kubernetes_ssl) as kubernetes_client:
                batch = await KubernetesLifecycleCollector(
                    api_server=config.kubernetes_api_server,
                    cluster_ref=config.kubernetes_cluster_ref,
                    auth=auth,
                    http_client=kubernetes_client,
                ).collect(cursor)
        if not await store.append(batch, holder=holder, now=datetime.now(UTC)):
            logger.warning(
                "kubernetes_lifecycle_cursor_contended",
                extra={"reason": "lease_or_sequence_changed"},
            )
            return None
        if batch.limitation is not None:
            logger.warning(
                "kubernetes_lifecycle_collection_incomplete",
                extra={"reason": batch.limitation},
            )
        return len(batch.observations)
    except Exception as exc:  # noqa: BLE001 - independent read-only evidence source
        logger.warning(
            "kubernetes_lifecycle_collection_failed",
            extra={"reason": type(exc).__name__},
        )
        return None
