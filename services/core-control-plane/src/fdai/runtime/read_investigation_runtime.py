"""Production binding for durable background read investigations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai_core_service.read_investigation_consumer import (
    ReadInvestigationConsumerBinding,
)
from fdai_service_contracts.read_investigation import (
    READ_INVESTIGATION_CONSUMER_GROUP,
    READ_INVESTIGATION_REQUEST_TOPIC,
)

from fdai.core.background_task import (
    BackgroundTaskCoordinator,
    BackgroundTaskCoordinatorConfig,
    BackgroundTaskService,
    ReadInvestigationBackgroundExecutor,
)
from fdai.core.read_investigation import ReadInvestigationService
from fdai.delivery.persistence import (
    PostgresBackgroundTaskStore,
    PostgresBackgroundTaskStoreConfig,
)
from fdai.delivery.persistence.background_task_lifecycle_audit import (
    StateStoreBackgroundTaskLifecycleAudit,
)
from fdai.delivery.persistence.read_investigation_latency import (
    StateStoreReadLatencyProfileStore,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.read_investigation import (
    ReadInvestigationDiscoveryRefresher,
    ReadInvestigationProvider,
)
from fdai.shared.providers.state_store import StateStore


class _CoordinatorControl:
    def __init__(self, coordinator: BackgroundTaskCoordinator) -> None:
        self._coordinator = coordinator
        self.event = asyncio.Event()

    def wake(self) -> None:
        self.event.set()

    async def cancel(
        self,
        task_id: str,
        *,
        actor: str,
        is_admin: bool,
    ) -> None:
        await self._coordinator.cancel(task_id, actor=actor, is_admin=is_admin)


@dataclass(frozen=True, slots=True)
class ReadInvestigationRuntimeBinding:
    """Own the complete optional Core lifecycle for one request topic."""

    consumer: ReadInvestigationConsumerBinding
    coordinator: BackgroundTaskCoordinator
    wake_signal: _CoordinatorControl
    maintenance_seconds: float = 30.0
    discovery_refresh: Callable[[], Awaitable[bool]] | None = None
    discovery_refresh_seconds: float = 30.0

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Supervise transport consumption, reconciliation, and bounded shutdown."""

        consumer_task = asyncio.create_task(
            self.consumer.run(bus=bus, stop=stop),
            name="read-investigation-consumer",
        )
        coordinator_task = asyncio.create_task(
            self._run_coordinator(stop),
            name="read-investigation-coordinator",
        )
        discovery_task = (
            asyncio.create_task(
                self._run_discovery_monitor(stop),
                name="read-investigation-mcp-discovery",
            )
            if self.discovery_refresh is not None
            else None
        )
        stop_task = asyncio.create_task(stop.wait(), name="read-investigation-stop")
        tasks = tuple(
            task
            for task in (consumer_task, coordinator_task, discovery_task, stop_task)
            if task is not None
        )
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if stop_task not in done:
                for task in done:
                    if not task.cancelled():
                        exception = task.exception()
                        if exception is not None:
                            raise exception
                raise RuntimeError("read investigation runtime stopped unexpectedly")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.coordinator.shutdown(drain_seconds=10.0)

    async def _run_coordinator(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                async with asyncio.timeout(self.maintenance_seconds):
                    await self.wake_signal.event.wait()
            except TimeoutError:
                pass
            self.wake_signal.event.clear()
            await self.coordinator.run_once()

    async def _run_discovery_monitor(self, stop: asyncio.Event) -> None:
        refresh = self.discovery_refresh
        if refresh is None:
            return
        while not stop.is_set():
            await refresh()
            try:
                async with asyncio.timeout(self.discovery_refresh_seconds):
                    await stop.wait()
            except TimeoutError:
                pass


def build_read_investigation_runtime_binding(
    *,
    environment: Mapping[str, str],
    provider: ReadInvestigationProvider | None,
    state_store: StateStore,
    saga_audit_chain: Any,
) -> ReadInvestigationRuntimeBinding | None:
    """Build the optional production path only from complete durable inputs."""

    topic = environment.get("FDAI_READ_INVESTIGATION_REQUEST_TOPIC", "").strip()
    if not topic:
        return None
    if topic != READ_INVESTIGATION_REQUEST_TOPIC:
        raise RuntimeError(
            "FDAI_READ_INVESTIGATION_REQUEST_TOPIC MUST use the versioned canonical topic"
        )
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("read investigation runtime requires FDAI_STATE_STORE_DSN")
    if provider is None:
        raise RuntimeError("read investigation runtime requires a production read provider")
    group_id = environment.get(
        "FDAI_READ_INVESTIGATION_CONSUMER_GROUP_ID",
        READ_INVESTIGATION_CONSUMER_GROUP,
    ).strip()
    if not group_id:
        raise RuntimeError("read investigation consumer group MUST be non-empty")
    coordinator_id = environment.get("HOSTNAME", "").strip() or "fdai-core"
    task_store = PostgresBackgroundTaskStore(config=PostgresBackgroundTaskStoreConfig(dsn=dsn))
    latency_store = StateStoreReadLatencyProfileStore(store=state_store)
    service = ReadInvestigationService(provider, latency_store=latency_store)
    coordinator = BackgroundTaskCoordinator(
        store=task_store,
        executor=ReadInvestigationBackgroundExecutor(service),
        config=BackgroundTaskCoordinatorConfig(coordinator_id=coordinator_id),
    )
    wake_signal = _CoordinatorControl(coordinator)
    consumer = ReadInvestigationConsumerBinding(
        request_topic=topic,
        group_id=group_id,
        service=BackgroundTaskService(
            store=task_store,
            audit=StateStoreBackgroundTaskLifecycleAudit(state_store),
        ),
        coordinator=wake_signal,
    )
    discovery_refresh = (
        provider.discover if isinstance(provider, ReadInvestigationDiscoveryRefresher) else None
    )
    return ReadInvestigationRuntimeBinding(
        consumer=consumer,
        coordinator=coordinator,
        wake_signal=wake_signal,
        discovery_refresh=discovery_refresh,
        discovery_refresh_seconds=_discovery_refresh_seconds(environment),
    )


def _discovery_refresh_seconds(environment: Mapping[str, str]) -> float:
    raw = environment.get("FDAI_AZURE_MCP_DISCOVERY_INTERVAL_SECONDS", "").strip()
    if not raw:
        return 30.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("FDAI_AZURE_MCP_DISCOVERY_INTERVAL_SECONDS MUST be numeric") from exc
    if not 5.0 <= value <= 3_600.0:
        raise RuntimeError("FDAI_AZURE_MCP_DISCOVERY_INTERVAL_SECONDS MUST be in [5, 3600]")
    return value


__all__ = [
    "ReadInvestigationRuntimeBinding",
    "build_read_investigation_runtime_binding",
]
