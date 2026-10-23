from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fdai.delivery import inventory_initial_closure, inventory_sync_cli
from fdai.delivery.inventory_collection import classify_inventory_failure
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.shared.providers.inventory_snapshot import InventoryFailureCode


def _config() -> InventoryJobConfig:
    return InventoryJobConfig.from_env(
        {"FDAI_INVENTORY_DSN": "postgresql://example", "AZURE_SUBSCRIPTION_ID": "sub-1"}
    )


@pytest.mark.parametrize("return_code", [0, 1])
async def test_independent_observer_has_no_blob_or_credential_arguments(
    monkeypatch: pytest.MonkeyPatch, return_code: int
) -> None:
    config = _config()
    process = SimpleNamespace(wait=AsyncMock(return_value=return_code), returncode=return_code)
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    if return_code:
        with pytest.raises(RuntimeError, match="independent closure retention failed"):
            await inventory_initial_closure.retain_initial_inventory_closure(config)
    else:
        await inventory_initial_closure.retain_initial_inventory_closure(config)
    assert spawn.call_args.args[-1] == "--retain-only"
    assert config.dsn not in spawn.call_args.args
    assert spawn.call_args.kwargs["env"]["FDAI_INVENTORY_DSN"] == config.dsn


async def test_independent_observer_cancellation_kills_only_its_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    process = SimpleNamespace(
        wait=AsyncMock(side_effect=[asyncio.CancelledError, 0]),
        kill=Mock(),
        returncode=None,
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(asyncio.CancelledError):
        await inventory_initial_closure.retain_initial_inventory_closure(config)
    process.kill.assert_called_once()
    assert process.wait.await_count == 2


def test_provider_coverage_failure_exposes_only_reviewed_reason() -> None:
    failure = classify_inventory_failure(
        RuntimeError("mapped resource identities do not reconcile with provider coverage")
    )
    assert failure.code is InventoryFailureCode.INVALID_DATA
    assert failure.message == "provider_coverage_changed"
    private = classify_inventory_failure(RuntimeError("provider failed: private-id secret"))
    assert private.message == "RuntimeError"


async def test_recurring_run_keeps_lock_acquisition_in_its_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = SimpleNamespace(acquire=Mock())
    monkeypatch.setattr(
        inventory_initial_closure, "PostgresAdvisoryResourceLock", Mock(return_value=lock)
    )
    async with inventory_initial_closure.initial_context(_config(), 1000, False) as context:
        _stack, coordinator_lock = context
        assert coordinator_lock is lock
        lock.acquire.assert_not_called()


@pytest.mark.parametrize("observer_fails", [False, True])
async def test_initial_lock_covers_independent_observation_and_precedes_completion(
    monkeypatch: pytest.MonkeyPatch, observer_fails: bool
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def acquire(lock_id: str):
        assert lock_id == "inventory-sync-coordinator"
        events.append("locked")
        try:
            yield
        finally:
            events.append("unlocked")

    async def retain(_config: InventoryJobConfig) -> None:
        assert events == ["locked"]
        events.append("observed")
        if observer_fails:
            raise RuntimeError("independent observer failed")

    async def complete() -> None:
        events.append("complete")

    config = replace(_config(), recovery_delta_enabled=False)
    monkeypatch.setattr(inventory_sync_cli, "_load_resource_type_registry", Mock())
    monkeypatch.setattr(inventory_sync_cli, "_load_relationship_mapping_catalog", Mock())
    monkeypatch.setattr(inventory_sync_cli, "_resolve_resource_types", Mock(return_value=()))
    monkeypatch.setattr(inventory_sync_cli, "_build_sources", Mock(return_value=()))
    monkeypatch.setattr(inventory_sync_cli, "_workload_identity", Mock())
    monkeypatch.setattr(
        inventory_sync_cli,
        "_build_job_event_bus",
        Mock(return_value=(SimpleNamespace(close=AsyncMock()), "t")),
    )
    monkeypatch.setattr(
        inventory_sync_cli, "build_ontology_observer", Mock(return_value=(None, None))
    )
    monkeypatch.setattr(inventory_sync_cli, "build_inventory_promotion_enricher", AsyncMock())
    progress = SimpleNamespace(
        advance=AsyncMock(), complete=AsyncMock(side_effect=complete), fail=AsyncMock()
    )
    monkeypatch.setattr(
        inventory_sync_cli, "build_inventory_progress_recorder", AsyncMock(return_value=progress)
    )
    store = SimpleNamespace(active_snapshot_id=AsyncMock(return_value="snapshot"))
    monkeypatch.setattr(
        inventory_sync_cli, "PostgresInventorySnapshotStore", Mock(return_value=store)
    )
    monkeypatch.setattr(
        inventory_sync_cli,
        "ObservedInventorySnapshotStore",
        Mock(return_value=SimpleNamespace(publish_terminal=AsyncMock())),
    )
    monkeypatch.setattr(
        inventory_initial_closure,
        "PostgresAdvisoryResourceLock",
        Mock(return_value=SimpleNamespace(acquire=acquire)),
    )
    coordinator = Mock(
        return_value=SimpleNamespace(
            run=AsyncMock(
                return_value=SimpleNamespace(attempt_id="snapshot", source="arg", failures=())
            )
        )
    )
    monkeypatch.setattr(inventory_sync_cli, "InventorySyncCoordinator", coordinator)
    monkeypatch.setattr(inventory_sync_cli, "retain_initial_inventory_closure", retain)
    if observer_fails:
        with pytest.raises(RuntimeError, match="independent observer failed"):
            await inventory_sync_cli.run(config, retain_initial_closure=True)
        assert events == ["locked", "observed", "unlocked"]
        progress.fail.assert_awaited_once()
    else:
        await inventory_sync_cli.run(config, retain_initial_closure=True)
        assert events == ["locked", "observed", "complete", "unlocked"]
    assert coordinator.call_args.kwargs["run_lock"] is None
