"""Compose read-only inventory change accelerators for the inventory job."""

from __future__ import annotations

import httpx
import yaml

from fdai.delivery.azure.activity_log import AzureActivityLogFactory, AzureActivityLogFactoryConfig
from fdai.delivery.azure.arg_resource_changes import (
    AzureResourceChangeFeed,
    AzureResourceChangeFeedConfig,
    forward_arg_resource_changes,
)
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.inventory_delta import forward_inventory_delta
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.runtime.venue import (
    bus_security_protocol,
    resolve_execution_venue,
    uses_developer_identity,
    uses_workload_identity,
)
from fdai.shared.config.loader import load_config_from_env
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.workload_identity import WorkloadIdentity


def load_resource_type_registry() -> ResourceTypeRegistry:
    """Load the reviewed inventory vocabulary from repository assets."""

    path = repo_asset_root() / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    return load_resource_type_registry_from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )


async def run_recovery_delta(config: InventoryJobConfig) -> int:
    """Retry the read-only Activity Log delta independently of full-scan due state."""

    vocabulary = load_resource_type_registry()
    async with httpx.AsyncClient() as client:
        identity = workload_identity(http_client=client)
        event_bus, event_topic = build_job_event_bus(identity)
        try:
            return await forward_recovery_deltas(
                config=config,
                identity=identity,
                vocabulary=vocabulary,
                http_client=client,
                event_bus=event_bus,
                topic=event_topic,
                scope_lock=recovery_delta_lock(config),
            )
        finally:
            await event_bus.close()


def build_job_event_bus(identity: WorkloadIdentity) -> tuple[EventHubsKafkaBus, str]:
    """Build the inventory accelerator event bus for the current execution venue."""

    app_config = load_config_from_env()
    venue = resolve_execution_venue()
    return EventHubsKafkaBus(
        identity=identity if uses_workload_identity(venue) else None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=app_config.kafka.bootstrap_servers,
            dlq_suffix=app_config.kafka.topic_dlq_suffix,
            security_protocol=bus_security_protocol(venue),
            client_id="fdai-inventory-recovery",
        ),
    ), app_config.kafka.topic_events


def workload_identity(*, http_client: httpx.AsyncClient) -> WorkloadIdentity:
    """Select the venue-specific read identity without fallback."""

    if uses_developer_identity(resolve_execution_venue()):
        return AsyncAzureCliWorkloadIdentity.from_env()
    return ManagedIdentityWorkloadIdentity.from_env(http_client=http_client)


async def forward_recovery_deltas(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    vocabulary: ResourceTypeRegistry,
    http_client: httpx.AsyncClient,
    event_bus: EventBus,
    topic: str,
    scope_lock: ResourceLock,
) -> int:
    """Forward every configured scope and commit each cursor only at its final fence."""

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
            published += await forward_inventory_delta(
                inventory=delta_inventory,
                state_store=state_store,
                event_bus=event_bus,
                topic=topic,
                scope=scope,
            )
    return published


def recovery_delta_lock(config: InventoryJobConfig) -> ResourceLock:
    """Build the per-scope advisory lock used by both accelerators."""

    return PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(
            dsn=config.dsn,
            lock_timeout_ms=30_000,
        )
    )


async def run_resource_change_feed(config: InventoryJobConfig) -> int:
    """Poll ARG resource changes independently of full-scan due state."""

    vocabulary = load_resource_type_registry()
    async with httpx.AsyncClient() as client:
        identity = workload_identity(http_client=client)
        event_bus, event_topic = build_job_event_bus(identity)
        try:
            return await _forward_resource_changes(
                config=config,
                identity=identity,
                vocabulary=vocabulary,
                http_client=client,
                event_bus=event_bus,
                topic=event_topic,
                scope_lock=recovery_delta_lock(config),
            )
        finally:
            await event_bus.close()


async def _forward_resource_changes(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    vocabulary: ResourceTypeRegistry,
    http_client: httpx.AsyncClient,
    event_bus: EventBus,
    topic: str,
    scope_lock: ResourceLock,
) -> int:
    """Forward one bounded resource-change poll per configured scope."""

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
            published += await forward_arg_resource_changes(
                feed=feed,
                state_store=state_store,
                event_bus=event_bus,
                topic=topic,
                scope=scope,
            )
    return published


__all__ = [
    "build_job_event_bus",
    "forward_recovery_deltas",
    "load_resource_type_registry",
    "recovery_delta_lock",
    "run_recovery_delta",
    "run_resource_change_feed",
    "workload_identity",
]
