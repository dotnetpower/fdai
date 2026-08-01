"""Managed MCP catalog durability, health, and audit tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from fdai.delivery.mcp import (
    InMemoryMcpCatalogStore,
    ManagedMcpCatalogService,
    McpCatalogError,
    McpHealthMonitor,
    McpHealthStatus,
    McpServerManifest,
)

_NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


class _Discovery:
    def __init__(self, tools: frozenset[str] = frozenset({"example_tool"})) -> None:
        self.tools = tools
        self.fail = False

    async def discover(self, manifest: McpServerManifest) -> frozenset[str]:
        if self.fail:
            raise McpCatalogError("synthetic discovery failure")
        return self.tools


def _manifest(url: str = "https://tools.example.com/mcp") -> McpServerManifest:
    return McpServerManifest(
        server_id="example.tools",
        server_url=url,
        tool_map={"tool.example": "example_tool"},
    )


async def test_admin_lifecycle_is_restart_safe_and_audited() -> None:
    store = InMemoryMcpCatalogStore()
    discovery = _Discovery()
    service = ManagedMcpCatalogService(store=store, discovery=discovery)

    installed = await service.install(_manifest(), actor_id="owner-example", at=_NOW)
    enabled = await service.enable("example.tools", actor_id="owner-example", at=_NOW)

    assert installed.catalog.get("example.tools").enabled is False
    assert enabled.catalog.get("example.tools").enabled is True
    assert enabled.health["example.tools"].status is McpHealthStatus.HEALTHY
    restarted = ManagedMcpCatalogService(store=store, discovery=discovery)
    assert (await store.load()).catalog.get("example.tools").enabled is True
    await restarted.disable("example.tools", actor_id="owner-example", at=_NOW)
    await restarted.uninstall("example.tools", actor_id="owner-example", at=_NOW)
    assert [record.action for record in store.audit_records] == [
        "mcp.server.installed",
        "mcp.server.enabled",
        "mcp.server.disabled",
        "mcp.server.uninstalled",
    ]


async def test_enable_requires_allowlisted_discovery() -> None:
    store = InMemoryMcpCatalogStore()
    service = ManagedMcpCatalogService(store=store, discovery=_Discovery(frozenset()))
    await service.install(_manifest(), actor_id="owner-example", at=_NOW)

    with pytest.raises(McpCatalogError, match="missing tools"):
        await service.enable("example.tools", actor_id="owner-example", at=_NOW)

    assert (await store.load()).catalog.get("example.tools").enabled is False


async def test_health_transition_is_persisted_and_audited_once() -> None:
    store = InMemoryMcpCatalogStore()
    discovery = _Discovery()
    service = ManagedMcpCatalogService(store=store, discovery=discovery)
    await service.install(_manifest(), actor_id="owner-example", at=_NOW)
    await service.enable("example.tools", actor_id="owner-example", at=_NOW)
    discovery.fail = True

    first = await service.check_health("example.tools", at=_NOW)
    second = await service.check_health("example.tools", at=_NOW)

    assert first.status is second.status is McpHealthStatus.UNHEALTHY
    assert first.reason == "discovery_failed"
    assert [record.action for record in store.audit_records].count("mcp.server.health_changed") == 1
    assert (await store.load()).routable_servers() == ()


async def test_periodic_monitor_checks_enabled_servers() -> None:
    store = InMemoryMcpCatalogStore()
    discovery = _Discovery()
    service = ManagedMcpCatalogService(store=store, discovery=discovery)
    await service.install(_manifest(), actor_id="owner-example", at=_NOW)
    await service.enable("example.tools", actor_id="owner-example", at=_NOW)
    monitor = McpHealthMonitor(service=service, clock=lambda: _NOW, interval_seconds=1)

    results = await monitor.run_once()

    assert results[0].status is McpHealthStatus.HEALTHY
    assert [server.server_id for server in (await store.load()).routable_servers()] == [
        "example.tools"
    ]


async def test_periodic_monitor_retries_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryMcpCatalogStore()
    service = ManagedMcpCatalogService(store=store, discovery=_Discovery())
    monitor = McpHealthMonitor(service=service, clock=lambda: _NOW, interval_seconds=0.001)
    stop = asyncio.Event()
    calls = 0

    async def run_once() -> tuple[()]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise McpCatalogError("synthetic revision conflict")
        stop.set()
        return ()

    monkeypatch.setattr(monitor, "run_once", run_once)

    await asyncio.wait_for(monitor.run(stop), timeout=0.1)

    assert calls == 2


async def test_revision_conflict_fails_without_unaudited_overwrite() -> None:
    store = InMemoryMcpCatalogStore()
    service = ManagedMcpCatalogService(store=store, discovery=_Discovery())
    stale = await store.load()
    await service.install(_manifest(), actor_id="owner-example", at=_NOW)

    committed = await store.commit(
        expected_revision=stale.revision,
        catalog=stale.catalog,
        health=stale.health,
        audit=store.audit_records[0],
    )

    assert committed is False
    assert (await store.load()).catalog.get("example.tools").server_id == "example.tools"
