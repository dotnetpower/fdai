"""AzureCliInventory - dev-mode Inventory shelling to ``az``."""

from __future__ import annotations

import asyncio
import json
import subprocess
from unittest.mock import patch

import pytest

from fdai.delivery.azure.dev_inventory import (
    AzureCliInventory,
    AzureCliInventoryError,
)
from fdai.shared.providers.inventory import InventoryBatch


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
        assert rec.resource_id == "resourcegroups/rg-example"
        assert (
            rec.provider_ref
            == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example"
        )
        assert rec.props["name"] == "rg-example"

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
    def test_delta_returns_empty_stream(self) -> None:
        inv = AzureCliInventory()

        async def _run() -> list[InventoryBatch]:
            return [b async for b in inv.delta(cursor="anything")]

        assert asyncio.run(_run()) == []
