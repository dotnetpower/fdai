"""Local Azure CLI inventory graph projection tests."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.delivery.read_api.dev.azure_inventory_graph import (
    AzureCliInventoryGraphProvider,
    inventory_cache_path,
    inventory_invalidation_path,
)
from fdai.delivery.read_api.dev.helpers import build_inventory_graph_provider
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
                    props={
                        "name": "vm-example",
                        "resourceGroup": "rg-example",
                        "powerState": "VM running",
                        "provisioningState": "Succeeded",
                    },
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


class _InventoryAfterFinal(_Inventory):
    async def full_snapshot(self, since: str | None = None):  # type: ignore[no-untyped-def]
        async for batch in super().full_snapshot(since):
            yield batch
        yield InventoryBatch(resources=(), cursor="late", final=False)


class _InventoryInvalidatedDuringFirstScan(_Inventory):
    def __init__(self, marker: Path) -> None:
        super().__init__()
        self.marker = marker

    async def full_snapshot(self, since: str | None = None):  # type: ignore[no-untyped-def]
        async for batch in super().full_snapshot(since):
            if self.calls == 1 and batch.final:
                self.marker.parent.mkdir(parents=True, exist_ok=True)
                self.marker.write_text("changed\n", encoding="ascii")
            yield batch


class _HangingInventory(_Inventory):
    async def full_snapshot(self, since: str | None = None):  # type: ignore[no-untyped-def]
        del since
        await asyncio.Event().wait()
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
    vm = next(resource for resource in resources if resource["type"] == "compute.vm")
    assert vm["status"] == "VM running"
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


def test_rejects_batches_after_final_fence() -> None:
    provider = AzureCliInventoryGraphProvider(inventory=_InventoryAfterFinal())

    with pytest.raises(RuntimeError, match="after its final fence"):
        asyncio.run(provider(None, 4, ("contains",)))


def test_bounds_inventory_refresh_duration() -> None:
    provider = AzureCliInventoryGraphProvider(
        inventory=_HangingInventory(),
        refresh_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError):
        asyncio.run(provider(None, 4, ("contains",)))


def test_helper_disables_persistent_cache_without_explicit_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_LOCAL_AZURE_DISCOVERY", raising=False)
    monkeypatch.delenv("FDAI_LOCAL_AZURE_SUBSCRIPTION_ID", raising=False)
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
    monkeypatch.delenv("FDAI_LOCAL_AZURE_CONFIG_DIR", raising=False)

    provider = build_inventory_graph_provider()

    assert provider.inventory.subscription_id is None
    assert provider.cache_path is None
    assert provider.cache_identity is None
    assert provider.invalidation_path is None


def test_helper_isolates_cache_by_explicit_subscription_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_LOCAL_AZURE_DISCOVERY", raising=False)
    monkeypatch.delenv("FDAI_LOCAL_AZURE_SUBSCRIPTION_ID", raising=False)
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "subscription-example")
    monkeypatch.setenv("FDAI_LOCAL_AZURE_CONFIG_DIR", "/profiles/example")

    provider = build_inventory_graph_provider()

    assert provider.inventory.subscription_id == "subscription-example"
    assert provider.inventory.azure_config_dir == "/profiles/example"
    assert provider.cache_path is not None
    assert provider.cache_identity is not None
    assert provider.cache_identity in provider.cache_path.name
    assert "subscription-example" not in provider.cache_path.name
    assert provider.invalidation_path == provider.cache_path.with_suffix(".invalidated")


def test_cache_path_rejects_empty_subscription_and_canonicalizes_profile(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="MUST NOT be empty"):
        inventory_cache_path(
            repo_root=tmp_path,
            subscription_id=" ",
            azure_config_dir=None,
        )
    profile = tmp_path / "profiles" / ".." / "profile"
    first_path, _ = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=str(profile),
    )
    second_path, _ = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=str(tmp_path / "profile"),
    )

    assert first_path == second_path
    assert inventory_invalidation_path(first_path) == first_path.with_suffix(".invalidated")


def test_persistent_cache_survives_provider_restart(tmp_path: Path) -> None:
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    first_inventory = _Inventory()
    first_provider = AzureCliInventoryGraphProvider(
        inventory=first_inventory,
        cache_path=cache_path,
        cache_identity=identity,
    )
    first = asyncio.run(first_provider(None, 4, ("contains",)))

    second_inventory = _Inventory()
    second_provider = AzureCliInventoryGraphProvider(
        inventory=second_inventory,
        cache_path=cache_path,
        cache_identity=identity,
    )
    second = asyncio.run(second_provider(None, 4, ("contains",)))

    assert first_inventory.calls == 1
    assert second_inventory.calls == 0
    assert second["resources"] == first["resources"]
    assert second["cache"] == {
        "status": "fresh",
        "age_seconds": 0,
        "persistent": True,
    }
    assert "subscription-example" not in cache_path.name
    serialized = cache_path.read_text(encoding="utf-8")
    assert "subscription-example" not in serialized
    assert "/subscriptions/" not in serialized
    assert "provider_ref" not in serialized


def test_stale_cache_returns_immediately_and_refreshes_in_background(tmp_path: Path) -> None:
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir="/profiles/example",
    )
    seed_provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(),
        cache_path=cache_path,
        cache_identity=identity,
    )
    asyncio.run(seed_provider(None, 4, ("contains",)))
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["cached_at"] = (datetime.now(tz=UTC) - timedelta(minutes=5)).isoformat()
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    inventory = _Inventory()
    provider = AzureCliInventoryGraphProvider(
        inventory=inventory,
        cache_ttl_seconds=60,
        cache_path=cache_path,
        cache_identity=identity,
    )

    async def _run() -> tuple[dict[str, object], dict[str, object]]:
        stale = await provider(None, 4, ("contains",))
        await provider.wait_for_refresh()
        fresh = await provider(None, 4, ("contains",))
        return stale, fresh

    stale, fresh = asyncio.run(_run())
    assert stale["freshness"] == "stale"
    assert stale["cache"]["status"] == "refreshing"
    assert inventory.calls == 1
    assert fresh["freshness"] == "fresh"
    assert fresh["cache"]["status"] == "fresh"


def test_cache_identity_mismatch_forces_new_snapshot(tmp_path: Path) -> None:
    cache_path = tmp_path / "inventory.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": 2,
                "identity": "other-subscription",
                "max_resources": 120,
                "cached_at": datetime.now(tz=UTC).isoformat(),
                "graph": {"resources": [], "links": []},
            }
        ),
        encoding="utf-8",
    )
    inventory = _Inventory()
    provider = AzureCliInventoryGraphProvider(
        inventory=inventory,
        cache_path=cache_path,
        cache_identity="expected-subscription",
    )

    graph = asyncio.run(provider(None, 4, ("contains",)))

    assert inventory.calls == 1
    assert len(graph["resources"]) == 3


def test_cache_limit_change_forces_new_snapshot(tmp_path: Path) -> None:
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    asyncio.run(
        AzureCliInventoryGraphProvider(
            inventory=_Inventory(),
            max_resources=120,
            cache_path=cache_path,
            cache_identity=identity,
        )(None, 4, ("contains",))
    )
    inventory = _Inventory()
    graph = asyncio.run(
        AzureCliInventoryGraphProvider(
            inventory=inventory,
            max_resources=1,
            cache_path=cache_path,
            cache_identity=identity,
        )(None, 4, ("contains",))
    )

    assert inventory.calls == 1
    assert graph["truncated"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(cached_at="2999-01-01T00:00:00+00:00"),
        lambda payload: payload["graph"].update(resources=[{"id": 7}]),
    ],
)
def test_invalid_persistent_cache_forces_new_snapshot(tmp_path: Path, mutation) -> None:  # type: ignore[no-untyped-def]
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    asyncio.run(
        AzureCliInventoryGraphProvider(
            inventory=_Inventory(),
            cache_path=cache_path,
            cache_identity=identity,
        )(None, 4, ("contains",))
    )
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    mutation(payload)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    inventory = _Inventory()

    asyncio.run(
        AzureCliInventoryGraphProvider(
            inventory=inventory,
            cache_path=cache_path,
            cache_identity=identity,
        )(None, 4, ("contains",))
    )

    assert inventory.calls == 1


def test_cache_write_failure_keeps_live_snapshot_available(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(),
        cache_path=blocked_parent / "inventory.json",
        cache_identity="identity",
    )

    graph = asyncio.run(provider(None, 4, ("contains",)))

    assert graph["freshness"] == "fresh"
    assert "azure_cli_inventory_cache_write_failed" in caplog.text


def test_cache_serialization_failure_keeps_live_snapshot_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fdai.delivery.read_api.dev import azure_inventory_graph as module

    def fail_serialization(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        del args, kwargs
        raise TypeError("unsupported cache value")

    monkeypatch.setattr(module.json, "dump", fail_serialization)
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(),
        cache_path=cache_path,
        cache_identity=identity,
    )

    graph = asyncio.run(provider(None, 4, ("contains",)))

    assert graph["freshness"] == "fresh"
    assert "azure_cli_inventory_cache_write_failed" in caplog.text


def test_invalidation_marker_refreshes_cache_before_ttl(tmp_path: Path) -> None:
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    marker = cache_path.parent / f"{identity}.invalidated"
    seed_provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(),
        cache_path=cache_path,
        cache_identity=identity,
        invalidation_path=marker,
    )
    asyncio.run(seed_provider(None, 4, ("contains",)))
    time.sleep(0.01)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("changed\n", encoding="ascii")

    inventory = _Inventory()
    provider = AzureCliInventoryGraphProvider(
        inventory=inventory,
        cache_ttl_seconds=3600,
        cache_path=cache_path,
        cache_identity=identity,
        invalidation_path=marker,
    )

    async def _run() -> dict[str, object]:
        stale = await provider(None, 4, ("contains",))
        await provider.wait_for_refresh()
        return stale

    stale = asyncio.run(_run())
    assert stale["cache"]["status"] == "refreshing"
    assert inventory.calls == 1


def test_equal_invalidation_timestamp_fails_closed(tmp_path: Path) -> None:
    marker = tmp_path / "inventory.invalidated"
    marker.write_text("changed\n", encoding="ascii")
    provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(),
        invalidation_path=marker,
    )
    provider._cached_at_utc = datetime.fromtimestamp(marker.stat().st_mtime, tz=UTC)

    assert provider._cache_invalidated() is True


def test_invalidation_metadata_error_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = tmp_path / "inventory.invalidated"
    provider = AzureCliInventoryGraphProvider(
        inventory=_Inventory(),
        invalidation_path=marker,
    )
    provider._cached_at_utc = datetime.now(tz=UTC)
    original_stat = Path.stat

    def fail_marker_stat(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if path == marker:
            raise PermissionError("marker metadata unavailable")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_marker_stat)

    assert provider._cache_invalidated() is True
    assert "azure_cli_inventory_invalidation_check_failed" in caplog.text


def test_change_during_scan_remains_invalidated_until_follow_up_refresh(tmp_path: Path) -> None:
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    marker = inventory_invalidation_path(cache_path)
    inventory = _InventoryInvalidatedDuringFirstScan(marker)
    provider = AzureCliInventoryGraphProvider(
        inventory=inventory,
        cache_path=cache_path,
        cache_identity=identity,
        invalidation_path=marker,
    )

    async def _run() -> tuple[dict[str, object], dict[str, object]]:
        first = await provider(None, 4, ("contains",))
        await provider.wait_for_refresh()
        second = await provider(None, 4, ("contains",))
        return first, second

    first, second = asyncio.run(_run())
    assert first["cache"]["status"] == "refreshing"
    assert second["cache"]["status"] == "fresh"
    assert inventory.calls == 2


def test_change_during_background_refresh_runs_immediate_follow_up(tmp_path: Path) -> None:
    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    asyncio.run(
        AzureCliInventoryGraphProvider(
            inventory=_Inventory(),
            cache_path=cache_path,
            cache_identity=identity,
        )(None, 4, ("contains",))
    )
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["cached_at"] = (datetime.now(tz=UTC) - timedelta(minutes=5)).isoformat()
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    marker = inventory_invalidation_path(cache_path)
    inventory = _InventoryInvalidatedDuringFirstScan(marker)
    provider = AzureCliInventoryGraphProvider(
        inventory=inventory,
        cache_ttl_seconds=60,
        cache_path=cache_path,
        cache_identity=identity,
        invalidation_path=marker,
    )

    async def _run() -> dict[str, object]:
        stale = await provider(None, 4, ("contains",))
        await provider.wait_for_refresh()
        return stale

    stale = asyncio.run(_run())
    assert stale["cache"]["status"] == "refreshing"
    assert inventory.calls == 2


def test_concurrent_first_requests_share_persistent_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.delivery.read_api.dev import azure_inventory_graph as module

    cache_path, identity = inventory_cache_path(
        repo_root=tmp_path,
        subscription_id="subscription-example",
        azure_config_dir=None,
    )
    asyncio.run(
        AzureCliInventoryGraphProvider(
            inventory=_Inventory(),
            cache_path=cache_path,
            cache_identity=identity,
        )(None, 4, ("contains",))
    )
    original_read = module._read_cache_file
    started = threading.Event()
    release = threading.Event()

    def slow_read(*args):  # type: ignore[no-untyped-def]
        started.set()
        assert release.wait(timeout=1)
        return original_read(*args)

    monkeypatch.setattr(module, "_read_cache_file", slow_read)
    inventory = _Inventory()
    provider = AzureCliInventoryGraphProvider(
        inventory=inventory,
        cache_path=cache_path,
        cache_identity=identity,
    )

    async def _run() -> None:
        first = asyncio.create_task(provider(None, 4, ("contains",)))
        assert await asyncio.to_thread(started.wait, 1)
        second = asyncio.create_task(provider(None, 4, ("contains",)))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)

    asyncio.run(_run())
    assert inventory.calls == 0
