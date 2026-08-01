"""Durable managed MCP catalog lifecycle, health, and admin audit."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from fdai.delivery.mcp.catalog import (
    McpCatalogError,
    McpServerCatalog,
    McpServerManifest,
)

_LOGGER = logging.getLogger(__name__)


class McpHealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class McpServerHealth:
    status: McpHealthStatus
    checked_at: datetime | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class McpAdminAuditRecord:
    action: str
    actor_id: str
    server_id: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ManagedMcpSnapshot:
    revision: int
    catalog: McpServerCatalog
    health: Mapping[str, McpServerHealth] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("managed MCP revision MUST be non-negative")
        object.__setattr__(self, "health", MappingProxyType(dict(self.health)))

    def routable_servers(self) -> tuple[McpServerManifest, ...]:
        return tuple(
            manifest
            for manifest in self.catalog.list()
            if manifest.enabled
            and self.health.get(manifest.server_id, McpServerHealth(McpHealthStatus.UNKNOWN)).status
            is McpHealthStatus.HEALTHY
        )


class McpCatalogStore(Protocol):
    async def load(self) -> ManagedMcpSnapshot: ...

    async def commit(
        self,
        *,
        expected_revision: int,
        catalog: McpServerCatalog,
        health: Mapping[str, McpServerHealth],
        audit: McpAdminAuditRecord,
    ) -> bool: ...


class McpToolDiscovery(Protocol):
    async def discover(self, manifest: McpServerManifest) -> frozenset[str]: ...


class InMemoryMcpCatalogStore:
    def __init__(self) -> None:
        self.snapshot = ManagedMcpSnapshot(revision=0, catalog=McpServerCatalog())
        self.audit_records: list[McpAdminAuditRecord] = []

    async def load(self) -> ManagedMcpSnapshot:
        return self.snapshot

    async def commit(
        self,
        *,
        expected_revision: int,
        catalog: McpServerCatalog,
        health: Mapping[str, McpServerHealth],
        audit: McpAdminAuditRecord,
    ) -> bool:
        if self.snapshot.revision != expected_revision:
            return False
        self.snapshot = ManagedMcpSnapshot(
            revision=expected_revision + 1,
            catalog=catalog,
            health=health,
        )
        self.audit_records.append(audit)
        return True


class ManagedMcpCatalogService:
    """Apply one audited catalog or health transition per CAS commit."""

    def __init__(self, *, store: McpCatalogStore, discovery: McpToolDiscovery) -> None:
        self._store = store
        self._discovery = discovery

    async def install(
        self,
        manifest: McpServerManifest,
        *,
        actor_id: str,
        at: datetime,
    ) -> ManagedMcpSnapshot:
        snapshot = await self._store.load()
        catalog = snapshot.catalog.install(manifest)
        health = {**snapshot.health, manifest.server_id: McpServerHealth(McpHealthStatus.UNKNOWN)}
        return await self._commit(
            snapshot,
            catalog,
            health,
            "mcp.server.installed",
            actor_id,
            manifest.server_id,
            at,
        )

    async def update(
        self,
        manifest: McpServerManifest,
        *,
        actor_id: str,
        at: datetime,
    ) -> ManagedMcpSnapshot:
        if manifest.enabled:
            raise McpCatalogError("MCP server updates MUST remain disabled until rediscovery")
        snapshot = await self._store.load()
        current = snapshot.catalog.get(manifest.server_id)
        if current.enabled:
            raise McpCatalogError("disable an MCP server before updating it")
        servers = {server.server_id: server for server in snapshot.catalog.list()}
        servers[manifest.server_id] = manifest
        catalog = McpServerCatalog(servers)
        health = {**snapshot.health, manifest.server_id: McpServerHealth(McpHealthStatus.UNKNOWN)}
        return await self._commit(
            snapshot,
            catalog,
            health,
            "mcp.server.updated",
            actor_id,
            manifest.server_id,
            at,
        )

    async def enable(
        self,
        server_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> ManagedMcpSnapshot:
        snapshot = await self._store.load()
        manifest = snapshot.catalog.get(server_id)
        discovered = await self._discovery.discover(manifest)
        catalog = snapshot.catalog.enable(server_id, discovered_tools=discovered)
        health = {
            **snapshot.health,
            server_id: McpServerHealth(McpHealthStatus.HEALTHY, checked_at=at),
        }
        return await self._commit(
            snapshot, catalog, health, "mcp.server.enabled", actor_id, server_id, at
        )

    async def disable(
        self,
        server_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> ManagedMcpSnapshot:
        snapshot = await self._store.load()
        catalog = snapshot.catalog.disable(server_id)
        return await self._commit(
            snapshot,
            catalog,
            snapshot.health,
            "mcp.server.disabled",
            actor_id,
            server_id,
            at,
        )

    async def uninstall(
        self,
        server_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> ManagedMcpSnapshot:
        snapshot = await self._store.load()
        catalog = snapshot.catalog.uninstall(server_id)
        health = dict(snapshot.health)
        health.pop(server_id, None)
        return await self._commit(
            snapshot,
            catalog,
            health,
            "mcp.server.uninstalled",
            actor_id,
            server_id,
            at,
        )

    async def check_health(self, server_id: str, *, at: datetime) -> McpServerHealth:
        snapshot = await self._store.load()
        manifest = snapshot.catalog.get(server_id)
        try:
            discovered = await self._discovery.discover(manifest)
            missing = set(manifest.tool_map.values()) - discovered
            if missing:
                health = McpServerHealth(
                    McpHealthStatus.UNHEALTHY,
                    checked_at=at,
                    reason="allowlisted_tools_missing",
                )
            else:
                health = McpServerHealth(McpHealthStatus.HEALTHY, checked_at=at)
        except McpCatalogError:
            health = McpServerHealth(
                McpHealthStatus.UNHEALTHY,
                checked_at=at,
                reason="discovery_failed",
            )
        prior = snapshot.health.get(server_id)
        if prior is not None and prior.status is health.status and prior.reason == health.reason:
            return health
        updated = {**snapshot.health, server_id: health}
        await self._commit(
            snapshot,
            snapshot.catalog,
            updated,
            "mcp.server.health_changed",
            "mcp-health-monitor",
            server_id,
            at,
        )
        return health

    async def check_all(self, *, at: datetime) -> Sequence[McpServerHealth]:
        snapshot = await self._store.load()
        results: list[McpServerHealth] = []
        for manifest in snapshot.catalog.list():
            if manifest.enabled:
                results.append(await self.check_health(manifest.server_id, at=at))
        return tuple(results)

    async def _commit(
        self,
        snapshot: ManagedMcpSnapshot,
        catalog: McpServerCatalog,
        health: Mapping[str, McpServerHealth],
        action: str,
        actor_id: str,
        server_id: str,
        at: datetime,
    ) -> ManagedMcpSnapshot:
        if not actor_id:
            raise McpCatalogError("MCP admin actor MUST be non-empty")
        committed = await self._store.commit(
            expected_revision=snapshot.revision,
            catalog=catalog,
            health=health,
            audit=McpAdminAuditRecord(action, actor_id, server_id, at),
        )
        if not committed:
            raise McpCatalogError("MCP catalog changed concurrently")
        return replace(snapshot, revision=snapshot.revision + 1, catalog=catalog, health=health)


class McpHealthMonitor:
    """Periodically refresh enabled-server health until stopped."""

    def __init__(
        self,
        *,
        service: ManagedMcpCatalogService,
        clock: ProtocolClock,
        interval_seconds: float = 60.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("MCP health interval MUST be positive")
        self._service = service
        self._clock = clock
        self._interval = interval_seconds

    async def run_once(self) -> Sequence[McpServerHealth]:
        return await self._service.check_all(at=self._clock())

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001 - retry transient health failures
                _LOGGER.warning(
                    "mcp_health_check_failed",
                    extra={"error_type": type(exc).__name__},
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue


class ProtocolClock(Protocol):
    def __call__(self) -> datetime: ...


__all__ = [
    "InMemoryMcpCatalogStore",
    "ManagedMcpCatalogService",
    "ManagedMcpSnapshot",
    "McpAdminAuditRecord",
    "McpCatalogStore",
    "McpHealthStatus",
    "McpHealthMonitor",
    "McpServerHealth",
    "McpToolDiscovery",
]
