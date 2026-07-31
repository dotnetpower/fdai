"""AzureCliInventory - dev-mode Inventory shelling to ``az``."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from fdai.delivery.azure.arg_projection import build_arm_to_neutral_map
from fdai.delivery.azure.dev_inventory import (
    AzureCliInventory,
    AzureCliInventoryError,
)
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.providers.inventory import InventoryBatch

REPO_ROOT = Path(__file__).resolve().parents[3]
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _resource_types():  # type: ignore[no-untyped-def]
    return load_resource_type_registry_from_mapping(
        yaml.safe_load(VOCABULARY_FILE.read_text(encoding="utf-8"))
    )


def _completed(
    stdout: str, *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["az"], returncode=returncode, stdout=stdout, stderr=stderr
    )


async def _drain(inv: AzureCliInventory) -> list[InventoryBatch]:
    return [b async for b in inv.full_snapshot()]


class TestFullSnapshot:
    def test_yields_final_batch_at_end(self) -> None:
        inv = AzureCliInventory(resource_types=("resource-group",))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            return_value=_completed("[]"),
        ):
            batches = asyncio.run(_drain(inv))
        # 1 empty resource-group batch + 1 final fence.
        assert len(batches) == 2
        assert batches[-1].final is True
        assert batches[-1].cursor == "az-cli:end"

    def test_maps_resource_group_row(self) -> None:
        payload = json.dumps(
            [
                {
                    "id": (
                        "/subscriptions/00000000-0000-0000-0000-000000000000"
                        "/resourceGroups/rg-example"
                    ),
                    "name": "rg-example",
                    "location": "koreacentral",
                    "tags": {"env": "dev"},
                }
            ]
        )
        inv = AzureCliInventory(resource_types=("resource-group",))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            return_value=_completed(payload),
        ):
            batches = asyncio.run(_drain(inv))
        # First batch has the resource-group row.
        [rg_batch, _final] = batches
        assert len(rg_batch.resources) == 1
        rec = rg_batch.resources[0]
        assert rec.type == "resource-group"
        assert rec.resource_id.endswith("/resource-group/rg-example")
        assert (
            rec.provider_ref
            == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example"
        )
        assert rec.props["name"] == "rg-example"

    def test_maps_sql_database_row_with_resource_group(self) -> None:
        # `az resource list --resource-type Microsoft.Sql/servers/databases`
        # rows carry a `resourceGroup` field; the adapter must surface it as a
        # prop so a console read can scope MSSQL databases by resource group.
        payload = json.dumps(
            [
                {
                    "id": (
                        "/subscriptions/00000000-0000-0000-0000-000000000000"
                        "/resourceGroups/rg-payments/providers/Microsoft.Sql"
                        "/servers/sql-a/databases/orders"
                    ),
                    "name": "orders",
                    "location": "koreacentral",
                    "resourceGroup": "rg-payments",
                    "tags": {},
                    "properties": {"status": "Paused"},
                }
            ]
        )
        inv = AzureCliInventory(resource_types=("sql-database",))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            return_value=_completed(payload),
        ):
            batches = asyncio.run(_drain(inv))
        [db_batch, _final] = batches
        assert len(db_batch.resources) == 1
        rec = db_batch.resources[0]
        assert rec.type == "sql-database"
        assert rec.props["name"] == "orders"
        assert rec.props["resourceGroup"] == "rg-payments"
        assert rec.props["status"] == "Paused"

    def test_vm_uses_show_details_and_maps_power_state(self) -> None:
        payload = json.dumps(
            [
                {
                    "id": (
                        "/subscriptions/x/resourceGroups/rg-app/providers/"
                        "Microsoft.Compute/virtualMachines/vm-app"
                    ),
                    "name": "vm-app",
                    "resourceGroup": "rg-app",
                    "location": "koreacentral",
                    "powerState": "VM running",
                    "provisioningState": "Succeeded",
                }
            ]
        )
        captured: dict[str, list[str]] = {}

        def _side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
            captured["argv"] = list(args[0])
            return _completed(payload)

        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=_side_effect,
        ):
            batches = asyncio.run(_drain(AzureCliInventory(resource_types=("compute.vm",))))

        record = batches[0].resources[0]
        assert captured["argv"][1:4] == ["vm", "list", "--show-details"]
        assert record.props["powerState"] == "VM running"
        assert record.props["provisioningState"] == "Succeeded"

    def test_postgresql_uses_service_list_and_maps_state(self) -> None:
        payload = json.dumps(
            [
                {
                    "id": (
                        "/subscriptions/00000000-0000-0000-0000-000000000000/"
                        "resourceGroups/rg-data/providers/Microsoft.DBforPostgreSQL/"
                        "flexibleServers/postgres-data"
                    ),
                    "name": "postgres-data",
                    "resourceGroup": "rg-data",
                    "location": "koreacentral",
                    "state": "Stopped",
                }
            ]
        )
        captured: dict[str, list[str]] = {}

        def _side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
            captured["argv"] = list(args[0])
            return _completed(payload)

        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=_side_effect,
        ):
            batches = asyncio.run(_drain(AzureCliInventory(resource_types=("postgresql-server",))))

        record = batches[0].resources[0]
        assert captured["argv"][1:4] == ["postgres", "flexible-server", "list"]
        assert record.props["status"] == "Stopped"
        assert record.props["powerState"] == "Stopped"

    def test_aks_maps_nested_power_state_code(self) -> None:
        payload = json.dumps(
            [
                {
                    "id": (
                        "/subscriptions/00000000-0000-0000-0000-000000000000/"
                        "resourceGroups/rg-app/providers/Microsoft.ContainerService/"
                        "managedClusters/aks-example"
                    ),
                    "name": "aks-example",
                    "resourceGroup": "rg-app",
                    "location": "koreacentral",
                    "properties": {
                        "powerState": {"code": "Stopped"},
                        "provisioningState": "Succeeded",
                    },
                }
            ]
        )

        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            return_value=_completed(payload),
        ):
            batches = asyncio.run(_drain(AzureCliInventory(resource_types=("kubernetes-cluster",))))

        record = batches[0].resources[0]
        assert record.props["status"] == "Stopped"

    def test_resource_group_recovered_from_arm_id_when_field_absent(self) -> None:
        # A row missing the explicit `resourceGroup` field still recovers it
        # from the ARM path.
        payload = json.dumps(
            [
                {
                    "id": (
                        "/subscriptions/00000000-0000-0000-0000-000000000000"
                        "/resourceGroups/rg-analytics/providers/Microsoft.Sql"
                        "/servers/sql-b/databases/events"
                    ),
                    "name": "events",
                }
            ]
        )
        inv = AzureCliInventory(resource_types=("sql-database",))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            return_value=_completed(payload),
        ):
            batches = asyncio.run(_drain(inv))
        rec = batches[0].resources[0]
        assert rec.props["resourceGroup"] == "rg-analytics"

    def test_unknown_resource_type_skipped(self) -> None:
        inv = AzureCliInventory(resource_types=("resource-group", "not-a-type"))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            return_value=_completed("[]"),
        ) as run:
            batches = asyncio.run(_drain(inv))
        # Only resource-group emitted; final fence still present.
        cursors = [b.cursor for b in batches]
        assert cursors == ["az-cli:resource-group", "az-cli:end"]
        assert run.call_count == 1

    def test_multi_type_streaming_ordering(self) -> None:
        payload_rg = json.dumps([{"id": "/subscriptions/x/resourceGroups/rg1", "name": "rg1"}])
        sa_id = (
            "/subscriptions/x/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/sa1"
        )
        payload_sa = json.dumps([{"id": sa_id, "name": "sa1"}])
        inv = AzureCliInventory(resource_types=("resource-group", "object-storage"))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=[_completed(payload_rg), _completed(payload_sa)],
        ):
            batches = asyncio.run(_drain(inv))
        types_seen = [b.resources[0].type for b in batches if b.resources]
        assert types_seen == ["resource-group", "object-storage"]
        # Fence still last.
        assert batches[-1].final is True

    def test_discover_all_maps_registered_network_resources_and_links(self) -> None:
        group_payload = json.dumps(
            [
                {
                    "id": "/subscriptions/x/resourceGroups/rg-example",
                    "name": "rg-example",
                    "tags": {"fdai:managed": "true", "fdai:workload": "fdai"},
                }
            ]
        )
        public_ip_id = (
            "/subscriptions/x/resourceGroups/rg-example/providers/"
            "Microsoft.Network/publicIPAddresses/pip-example"
        )
        resources_payload = json.dumps(
            [
                {
                    "id": (
                        "/subscriptions/x/resourceGroups/rg-example/providers/"
                        "Microsoft.Network/loadBalancers/lb-example"
                    ),
                    "type": "Microsoft.Network/loadBalancers",
                    "name": "lb-example",
                    "resourceGroup": "rg-example",
                    "properties": {
                        "frontendIPConfigurations": [
                            {"properties": {"publicIPAddress": {"id": public_ip_id}}}
                        ]
                    },
                },
                {
                    "id": public_ip_id,
                    "type": "Microsoft.Network/publicIPAddresses",
                    "name": "pip-example",
                    "resourceGroup": "rg-example",
                },
                {
                    "id": "/subscriptions/x/resourceGroups/rg-example/providers/Other/type/x",
                    "type": "Other/type",
                    "name": "unsupported",
                },
            ]
        )
        inventory = AzureCliInventory(
            resource_types=("resource-group", "network.load-balancer", "network.public-ip"),
            azure_arm_types={
                "resource-group": "Microsoft.Resources/resourceGroups",
                "network.load-balancer": "Microsoft.Network/loadBalancers",
                "network.public-ip": "Microsoft.Network/publicIPAddresses",
            },
            discover_all=True,
        )

        def _discover_all_response(argv, **_kwargs):  # type: ignore[no-untyped-def]
            command = tuple(argv[1:3])
            if command == ("group", "list"):
                return _completed(group_payload)
            if command == ("graph", "query"):
                return _completed(
                    json.dumps(
                        {
                            "data": json.loads(resources_payload),
                            "skip_token": None,
                        }
                    )
                )
            if command == ("vm", "list"):
                return _completed("[]")
            raise AssertionError(f"unexpected Azure CLI command: {argv}")

        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=_discover_all_response,
        ):
            batches = asyncio.run(_drain(inventory))

        resource_batch, final = batches
        assert {record.type for record in resource_batch.resources} == {
            "resource-group",
            "network.load-balancer",
            "network.public-ip",
        }
        assert {
            (link.link_type, link.from_type, link.to_type) for link in resource_batch.links
        } >= {
            ("contains", "resource-group", "network.load-balancer"),
            ("contains", "resource-group", "network.public-ip"),
            ("attached_to", "network.load-balancer", "network.public-ip"),
        }
        resource_ids = {record.resource_id for record in resource_batch.resources}
        assert all(
            link.from_id in resource_ids and link.to_id in resource_ids
            for link in resource_batch.links
        )
        assert final.final is True

    def test_discover_all_falls_back_when_arg_is_unavailable(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        group_payload = json.dumps(
            [{"id": "/subscriptions/x/resourceGroups/rg-example", "name": "rg-example"}]
        )
        resources_payload = json.dumps(
            [
                {
                    "id": (
                        "/subscriptions/x/resourceGroups/rg-example/providers/"
                        "Microsoft.Network/publicIPAddresses/pip-example"
                    ),
                    "type": "Microsoft.Network/publicIPAddresses",
                    "name": "pip-example",
                    "resourceGroup": "rg-example",
                }
            ]
        )
        inventory = AzureCliInventory(
            resource_types=("resource-group", "network.public-ip"),
            azure_arm_types={
                "resource-group": "Microsoft.Resources/resourceGroups",
                "network.public-ip": "Microsoft.Network/publicIPAddresses",
            },
            discover_all=True,
        )

        def _fallback_response(argv, **_kwargs):  # type: ignore[no-untyped-def]
            command = tuple(argv[1:3])
            if command == ("group", "list"):
                return _completed(group_payload)
            if command == ("graph", "query"):
                return _completed("", returncode=1, stderr="extension unavailable")
            if command == ("resource", "list"):
                return _completed(resources_payload)
            if command == ("vm", "list"):
                return _completed("[]")
            raise AssertionError(f"unexpected Azure CLI command: {argv}")

        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=_fallback_response,
        ):
            batches = asyncio.run(_drain(inventory))

        assert {record.type for record in batches[0].resources} == {
            "resource-group",
            "network.public-ip",
        }
        assert "azure_cli_inventory_arg_fallback" in caplog.text

    def test_discover_all_rejects_ambiguous_rows_from_arg_fallback(self) -> None:
        registry = _resource_types()
        inventory = AzureCliInventory(
            resource_types=("compute.function", "compute.web-app"),
            azure_arm_types={
                "compute.function": "Microsoft.Web/sites",
                "compute.web-app": "Microsoft.Web/sites",
            },
            resource_type_registry=registry,
            discover_all=True,
        )
        fallback_rows = [
            {
                "id": (
                    "/subscriptions/00000000-0000-0000-0000-000000000000/"
                    "resourceGroups/rg-example/providers/Microsoft.Web/sites/app-example"
                ),
                "type": "Microsoft.Web/sites",
                "name": "app-example",
                "resourceGroup": "rg-example",
            }
        ]

        def _response(argv, **_kwargs):  # type: ignore[no-untyped-def]
            command = tuple(argv[1:3])
            if command == ("group", "list") or command == ("vm", "list"):
                return _completed("[]")
            if command == ("graph", "query"):
                return _completed("", returncode=1, stderr="extension unavailable")
            if command == ("resource", "list"):
                return _completed(json.dumps(fallback_rows))
            raise AssertionError(f"unexpected Azure CLI command: {argv}")

        with (
            patch(
                "fdai.delivery.azure.dev_inventory.subprocess.run",
                side_effect=_response,
            ),
            pytest.raises(AzureCliInventoryError, match="ambiguous"),
        ):
            asyncio.run(_drain(inventory))

    def test_discover_all_classifies_common_azure_resource_types(self) -> None:
        registry = _resource_types()
        expected_types = {
            "compute.web-app",
            "compute.function",
            "workflow.logic-app",
            "network.nsg",
            "network.firewall",
            "data-collection-rule",
        }
        arm_types = {
            entry.id: entry.azure_arm_type
            for entry in registry
            if entry.id in expected_types and entry.azure_arm_type is not None
        }
        rows = [
            {
                "id": (
                    "/subscriptions/00000000-0000-0000-0000-000000000000/"
                    "resourceGroups/rg-example/providers/Microsoft.Web/sites/web-example"
                ),
                "type": "Microsoft.Web/sites",
                "kind": "app,linux",
                "name": "web-example",
                "resourceGroup": "rg-example",
            },
            {
                "id": (
                    "/subscriptions/00000000-0000-0000-0000-000000000000/"
                    "resourceGroups/rg-example/providers/Microsoft.Web/sites/function-example"
                ),
                "type": "Microsoft.Web/sites",
                "kind": "functionapp,linux",
                "name": "function-example",
                "resourceGroup": "rg-example",
            },
            {
                "id": (
                    "/subscriptions/00000000-0000-0000-0000-000000000000/"
                    "resourceGroups/rg-example/providers/Microsoft.Logic/"
                    "workflows/logic-example"
                ),
                "type": "Microsoft.Logic/workflows",
                "name": "logic-example",
                "resourceGroup": "rg-example",
            },
            {
                "id": (
                    "/subscriptions/00000000-0000-0000-0000-000000000000/"
                    "resourceGroups/rg-example/providers/Microsoft.Network/"
                    "networkSecurityGroups/nsg-example"
                ),
                "type": "Microsoft.Network/networkSecurityGroups",
                "name": "nsg-example",
                "resourceGroup": "rg-example",
            },
            {
                "id": (
                    "/subscriptions/00000000-0000-0000-0000-000000000000/"
                    "resourceGroups/rg-example/providers/Microsoft.Network/"
                    "azureFirewalls/firewall-example"
                ),
                "type": "Microsoft.Network/azureFirewalls",
                "name": "firewall-example",
                "resourceGroup": "rg-example",
            },
            {
                "id": (
                    "/subscriptions/00000000-0000-0000-0000-000000000000/"
                    "resourceGroups/rg-example/providers/Microsoft.Insights/"
                    "dataCollectionRules/dcr-example"
                ),
                "type": "Microsoft.Insights/dataCollectionRules",
                "name": "dcr-example",
                "resourceGroup": "rg-example",
            },
        ]
        inventory = AzureCliInventory(
            resource_types=tuple(sorted(expected_types)),
            azure_arm_types=arm_types,
            resource_type_registry=registry,
            discover_all=True,
        )

        def _response(argv, **_kwargs):  # type: ignore[no-untyped-def]
            command = tuple(argv[1:3])
            if command == ("group", "list") or command == ("vm", "list"):
                return _completed("[]")
            if command == ("graph", "query"):
                return _completed(json.dumps({"data": rows, "skip_token": None}))
            raise AssertionError(f"unexpected Azure CLI command: {argv}")

        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=_response,
        ):
            batches = asyncio.run(_drain(inventory))

        assert {record.type for record in batches[0].resources} == expected_types
        assert len(batches[0].resources) == len(expected_types)

    def test_arm_reverse_map_is_built_once_per_inventory(self) -> None:
        registry = _resource_types()

        with patch(
            "fdai.delivery.azure.dev_inventory.build_arm_to_neutral_map",
            wraps=build_arm_to_neutral_map,
        ) as build:
            inventory = AzureCliInventory(
                resource_types=("network.nsg",),
                azure_arm_types={"network.nsg": "Microsoft.Network/networkSecurityGroups"},
                resource_type_registry=registry,
            )
            inventory._project_rows([], "network.nsg")
            inventory._project_rows([], "network.nsg")

        build.assert_called_once_with(registry)

    def test_subscription_id_forwarded_as_arg(self) -> None:
        captured: dict[str, list[str]] = {}

        def _side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
            captured["argv"] = list(args[0])
            return _completed("[]")

        inv = AzureCliInventory(
            resource_types=("resource-group",),
            subscription_id="00000000-0000-0000-0000-000000000000",
        )
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=_side_effect,
        ):
            asyncio.run(_drain(inv))
        argv = captured["argv"]
        idx = argv.index("--subscription")
        assert argv[idx + 1] == "00000000-0000-0000-0000-000000000000"

    def test_project_rows_materializes_nested_subnet_shard(self) -> None:
        vnet_id = (
            "/subscriptions/00000000-0000-0000-0000-000000000001/"
            "resourceGroups/rg-example/providers/Microsoft.Network/virtualNetworks/vnet-example"
        )
        inventory = AzureCliInventory(
            resource_types=("network.vnet", "network.subnet"),
            azure_arm_types={
                "network.vnet": "Microsoft.Network/virtualNetworks",
                "network.subnet": "Microsoft.Network/virtualNetworks/subnets",
            },
        )

        records, links = inventory._project_rows(
            [
                {
                    "id": vnet_id,
                    "name": "vnet-example",
                    "resourceGroup": "rg-example",
                    "properties": {"subnets": [{"id": f"{vnet_id}/subnets/app", "name": "app"}]},
                }
            ],
            "network.subnet",
        )

        assert [record.type for record in records] == ["network.subnet"]
        assert [(link.from_type, link.link_type, link.to_type) for link in links] == [
            ("network.vnet", "contains", "network.subnet")
        ]

    def test_default_profile_drops_inherited_azure_config_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AZURE_CONFIG_DIR", "/home/example/.azure-other")
        captured: dict[str, object] = {}

        def _side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
            captured["env"] = kwargs["env"]
            return _completed("[]")

        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=_side_effect,
        ):
            asyncio.run(_drain(AzureCliInventory(resource_types=("resource-group",))))
        assert "AZURE_CONFIG_DIR" not in captured["env"]

    def test_explicit_profile_sets_azure_config_dir(self) -> None:
        captured: dict[str, object] = {}

        def _side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
            captured["env"] = kwargs["env"]
            return _completed("[]")

        inventory = AzureCliInventory(
            resource_types=("resource-group",),
            azure_config_dir="/home/example/.azure-explicit",
        )
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=_side_effect,
        ):
            asyncio.run(_drain(inventory))
        assert captured["env"]["AZURE_CONFIG_DIR"] == "/home/example/.azure-explicit"


class TestErrorPaths:
    def test_non_zero_exit_raises(self) -> None:
        inv = AzureCliInventory(resource_types=("resource-group",))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            return_value=_completed("", returncode=1, stderr="run 'az login'"),
        ):
            with pytest.raises(AzureCliInventoryError, match="exited with code 1"):
                asyncio.run(_drain(inv))

    def test_missing_az_binary_raises(self) -> None:
        inv = AzureCliInventory(resource_types=("resource-group",))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            with pytest.raises(AzureCliInventoryError, match="not found on PATH"):
                asyncio.run(_drain(inv))

    def test_timeout_raises(self) -> None:
        inv = AzureCliInventory(resource_types=("resource-group",))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="az", timeout=30),
        ):
            with pytest.raises(AzureCliInventoryError, match="timed out"):
                asyncio.run(_drain(inv))

    def test_non_json_stdout_raises(self) -> None:
        inv = AzureCliInventory(resource_types=("resource-group",))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            return_value=_completed("not-json"),
        ):
            with pytest.raises(AzureCliInventoryError, match="non-JSON"):
                asyncio.run(_drain(inv))

    def test_non_list_json_stdout_raises(self) -> None:
        inv = AzureCliInventory(resource_types=("resource-group",))
        with patch(
            "fdai.delivery.azure.dev_inventory.subprocess.run",
            return_value=_completed('{"not":"a list"}'),
        ):
            with pytest.raises(AzureCliInventoryError, match="non-list"):
                asyncio.run(_drain(inv))


class TestDelta:
    def test_delta_returns_empty_final_fence(self) -> None:
        inv = AzureCliInventory()

        async def _run() -> list[InventoryBatch]:
            return [b async for b in inv.delta(cursor="anything")]

        assert asyncio.run(_run()) == [InventoryBatch(final=True)]
