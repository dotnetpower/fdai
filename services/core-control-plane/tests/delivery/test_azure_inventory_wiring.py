"""Composition-root wiring test for the live Azure Resource Graph inventory.

Verifies that ``bind_azure_inventory`` assembles the real
``AzureArgQueryFactory`` (Kusto-over-ARG REST) into the
``AzureResourceGraphInventory`` shard runner and swaps it onto the
``Container`` in place of the default ``EmptyInventory`` - the P0-2 pairing
that was documented but never wired. No real Azure endpoint is contacted;
the httpx client is backed by ``httpx.MockTransport``.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from fdai.composition import bind_azure_inventory, default_container
from fdai.delivery.azure.arg_query import AzureArgQueryFactoryConfig
from fdai.delivery.azure.inventory import AzureInventoryConfig
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.shared.config.models import AppConfig
from fdai.shared.providers.inventory import EmptyInventory, InventoryBatch
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

REPO_ROOT = Path(__file__).resolve().parents[4]
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _vocab() -> ResourceTypeRegistry:
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        return load_resource_type_registry_from_mapping(yaml.safe_load(fh))


def _container():
    config = AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "example:9093",
                "topic_events": "aw.change.events",
            },
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "local-fake"},
        }
    )
    return default_container(config)


def test_default_container_uses_empty_inventory() -> None:
    container = _container()
    assert isinstance(container.inventory, EmptyInventory)


@pytest.mark.asyncio
async def test_bind_azure_inventory_makes_full_snapshot_live() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": (
                            "/subscriptions/00000000-0000-0000-0000-000000000001/"
                            "resourceGroups/rg-example/providers/Microsoft.Storage/"
                            "storageAccounts/stg1"
                        ),
                        "type": "Microsoft.Storage/storageAccounts",
                        "name": "stg1",
                        "location": "koreacentral",
                        "resourceGroup": "rg-example",
                        "subscriptionId": "00000000-0000-0000-0000-000000000001",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), base_url="https://mock-arm.local"
    ) as client:
        container = bind_azure_inventory(
            _container(),
            arg_config=AzureArgQueryFactoryConfig(
                subscription_scopes=("00000000-0000-0000-0000-000000000001",),
            ),
            inventory_config=AzureInventoryConfig(resource_types=("object-storage",)),
            resource_types=_vocab(),
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test literal
            ),
            http_client=client,
        )

        assert not isinstance(container.inventory, EmptyInventory)

        batches: list[InventoryBatch] = [b async for b in container.inventory.full_snapshot()]

    # One shard batch with the mapped resource, then the atomic-promote fence.
    assert batches[-1].final is True
    resources = [r for b in batches for r in b.resources]
    assert len(resources) == 1
    assert resources[0].type == "object-storage"
    assert resources[0].provider_ref is not None
    assert resources[0].provider_ref.endswith("/storageAccounts/stg1")
