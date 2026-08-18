"""Compose the live Azure inventory adapter behind the provider-neutral seam."""

from __future__ import annotations

from dataclasses import replace

import httpx

from ..delivery.azure.activity_log import (
    AzureActivityLogFactory,
    AzureActivityLogFactoryConfig,
)
from ..delivery.azure.arg_query import AzureArgQueryFactory, AzureArgQueryFactoryConfig
from ..delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from ..rule_catalog.schema.resource_type import ResourceTypeRegistry
from ..shared.providers.workload_identity import WorkloadIdentity
from ._helpers import Container


def bind_azure_inventory(
    container: Container,
    *,
    arg_config: AzureArgQueryFactoryConfig,
    inventory_config: AzureInventoryConfig,
    resource_types: ResourceTypeRegistry,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    activity_log_config: AzureActivityLogFactoryConfig | None = None,
) -> Container:
    """Bind bounded Azure full and optional delta reads to the Inventory seam.

    Full snapshots combine mapped shards, provider coverage, and unclassified identities under
    one bounded semaphore and atomic final fence. The optional Activity Log adapter supplies only
    ordered deltas; neither path grants execution authority.
    """
    query_factory = AzureArgQueryFactory(
        identity=identity,
        resource_types=resource_types,
        http_client=http_client,
        config=arg_config,
    )
    delta_fetch = (
        AzureActivityLogFactory(
            identity=identity,
            resource_types=resource_types,
            http_client=http_client,
            config=activity_log_config,
        ).build_fetch_fn()
        if activity_log_config is not None
        else None
    )
    inventory = AzureResourceGraphInventory(
        config=inventory_config,
        query=query_factory.build_query_fn(),
        scope_coverage=query_factory.build_scope_coverage_fn(),
        unmapped_resources=query_factory.build_unmapped_resource_query_fn(),
        delta_fetch=delta_fetch,
    )
    return replace(container, inventory=inventory)


__all__ = ["bind_azure_inventory"]
