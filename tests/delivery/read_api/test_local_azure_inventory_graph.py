"""Local Azure CLI inventory graph projection tests."""

from __future__ import annotations

import asyncio

import pytest

from fdai.delivery.read_api.dev.azure_inventory_graph import (
    AzureCliInventoryGraphProvider,
)
from fdai.delivery.read_api.routes.inventory_graph import InventoryGraphViewNotFoundError
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord


class _Inventory:
    def __init__(self, *, final: bool = True) -> None:
        self.calls = 0
        self.final = final

    async def full_snapshot(self, since: str | None = None):  # type: ignore[no-untyped-def]
        del since
        self.calls += 1
        yield InventoryBatch(
            resources=(
                ResourceRecord(
                    resource_id="resourcegroups/rg-example",
                    type="resource-group",
                    props={
                        "name": "rg-example",
                        "resourceGroup": "rg-example",
                        "tags": {"fdai:managed": "true", "fdai:workload": "fdai"},
                    },
                    provider_ref="/subscriptions/example/resourceGroups/rg-example",
                ),
                ResourceRecord(
                    resource_id=(
                        "resourcegroups/rg-example/providers/"
                        "microsoft.compute/virtualmachines/vm-example"
                    ),
                    type="compute.vm",
                    props={"name": "vm-example", "resourceGroup": "rg-example"},
                    provider_ref="/subscriptions/example/resourceGroups/rg-example/vm-example",
                ),
            ),
            cursor="page-1",
        )
        if self.final:
            yield InventoryBatch(cursor="done", final=True)

    async def delta(self, cursor: str):  # type: ignore[no-untyped-def]
        del cursor
        if False:
            yield InventoryBatch()


def test_projects_contains_graph_without_provider_refs_and_caches() -> None:
    inventory = _Inventory()
    provider = AzureCliInventoryGraphProvider(inventory=inventory, cache_ttl_seconds=60)

    async def _run() -> tuple[dict[str, object], dict[str, object]]:
        first = await provider(None, 4, ("contains",))
        second = await provider(None, 4, ("contains",))
        return first, second

    first, second = asyncio.run(_run())
    assert inventory.calls == 1
    assert first == second
    assert first["source"] == "azure-cli-local"
    assert first["cursor"] == "done"
    resources = first["resources"]
    assert len(resources) == 3
    assert all("provider_ref" not in resource and "props" not in resource for resource in resources)
    assert all(0 <= resource["x"] <= 18 and 0 <= resource["y"] <= 12 for resource in resources)
    assert all(
        resource.get("x", 0) + resource.get("w", 0) <= 18
        and resource.get("y", 0) + resource.get("h", 0) <= 12
        for resource in resources
    )
    assert first["links"] == [
        {
            "source": "azure-subscription",
            "target": "resourcegroups/rg-example",
            "type": "contains",
        },
        {
            "source": "resourcegroups/rg-example",
            "target": (
                "resourcegroups/rg-example/providers/microsoft.compute/virtualmachines/vm-example"
            ),
            "type": "contains",
        },
    ]


def test_filters_links_and_marks_truncation() -> None:
    provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(), cache_ttl_seconds=0, max_resources=1
    )
    graph = asyncio.run(provider(None, 4, ("depends_on",)))
    assert graph["truncated"] is True
    assert graph["links"] == []


def test_rejects_unknown_named_view() -> None:
    provider = AzureCliInventoryGraphProvider(inventory=_Inventory())

    with pytest.raises(InventoryGraphViewNotFoundError, match="production"):
        asyncio.run(provider("production", 4, ("contains",)))


def test_rejects_snapshot_without_final_fence() -> None:
    provider = AzureCliInventoryGraphProvider(inventory=_Inventory(final=False))
    with pytest.raises(RuntimeError, match="final fence"):
        asyncio.run(provider(None, 4, ("contains",)))
