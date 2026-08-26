"""Production binding for durable background read investigations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai_core_service.read_investigation_completion import (
    InteractiveCompletionWakeSink,
    InteractiveReadInvestigationCompletionPublisher,
)
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
    EventBusReadInvestigationCompletionSink,
    ReadInvestigationBackgroundExecutor,
)
from fdai.core.read_investigation import (
    InteractiveReadInvestigationConfig,
    InteractiveReadInvestigationCoordinator,
    ReadInvestigationModeSelector,
    ReadInvestigationService,
    interactive_investigation_policy,
)
from fdai.delivery.persistence import (
    PostgresBackgroundTaskStore,
    PostgresBackgroundTaskStoreConfig,
    PostgresReadInvestigationCompletionStore,
    PostgresReadInvestigationCompletionStoreConfig,
    PostgresReadInvestigationProgressStore,
    PostgresReadInvestigationProgressStoreConfig,
    PostgresReadInvestigationRunStore,
    PostgresReadInvestigationRunStoreConfig,
)
from fdai.delivery.persistence.background_task_completion_audit import (
    StateStoreBackgroundTaskCompletionAudit,
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
    completion_sink: EventBusReadInvestigationCompletionSink
    interactive: InteractiveReadInvestigationCoordinator
    interactive_run_store: PostgresReadInvestigationRunStore
    interactive_progress_store: PostgresReadInvestigationProgressStore
    interactive_completion_store: PostgresReadInvestigationCompletionStore
    interactive_completion_publisher: InteractiveReadInvestigationCompletionPublisher
    interactive_completion_wake: InteractiveCompletionWakeSink
    maintenance_seconds: float = 30.0
    discovery_refresh: Callable[[], Awaitable[bool]] | None = None
    discovery_refresh_seconds: float = 30.0

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Supervise transport consumption, reconciliation, and bounded shutdown."""

        await asyncio.gather(
            self.interactive_run_store.verify_schema(),
            self.interactive_progress_store.verify_schema(),
            self.interactive_completion_store.verify_schema(),
        )
        self.completion_sink.bind(bus)
        consumer_task = asyncio.create_task(
            self.consumer.run(bus=bus, stop=stop),
            name="read-investigation-consumer",
        )
        coordinator_task = asyncio.create_task(
            self._run_coordinator(stop),
            name="read-investigation-coordinator",
        )
        interactive_task = asyncio.create_task(
            self._run_interactive_maintenance(stop),
            name="read-investigation-interactive-maintenance",
        )
        interactive_completion_task = asyncio.create_task(
            self._run_interactive_completions(bus, stop),
            name="read-investigation-interactive-completions",
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
            for task in (
                consumer_task,
                coordinator_task,
                interactive_task,
                interactive_completion_task,
                discovery_task,
                stop_task,
            )
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
            await self.interactive.shutdown(drain_seconds=10.0)
            await self.coordinator.shutdown(drain_seconds=10.0)
            self.completion_sink.unbind()

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

    async def _run_interactive_maintenance(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.interactive.reconcile()
            try:
                async with asyncio.timeout(self.maintenance_seconds):
                    await stop.wait()
            except TimeoutError:
                pass

    async def _run_interactive_completions(
        self,
        bus: EventBus,
        stop: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            self.interactive_completion_wake.event.clear()
            await self.interactive_completion_publisher.run_once(bus=bus)
            if stop.is_set():
                return
            if self.interactive_completion_wake.event.is_set():
                continue
            try:
                async with asyncio.timeout(self.maintenance_seconds):
                    await self.interactive_completion_wake.event.wait()
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

    del saga_audit_chain

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
    interactive_run_store = PostgresReadInvestigationRunStore(
        config=PostgresReadInvestigationRunStoreConfig(dsn=dsn)
    )
    interactive_progress_store = PostgresReadInvestigationProgressStore(
        config=PostgresReadInvestigationProgressStoreConfig(dsn=dsn)
    )
    interactive_completion_store = PostgresReadInvestigationCompletionStore(
        config=PostgresReadInvestigationCompletionStoreConfig(dsn=dsn)
    )
    interactive_completion_wake = InteractiveCompletionWakeSink()
    interactive = InteractiveReadInvestigationCoordinator(
        store=interactive_run_store,
        progress_store=interactive_progress_store,
        executor=service,
        mode_selector=ReadInvestigationModeSelector(
            latency_store=latency_store,
            transport=provider.transport,
            policy=interactive_investigation_policy(),
        ),
        config=InteractiveReadInvestigationConfig(coordinator_id=coordinator_id),
        completion_sink=interactive_completion_wake,
    )
    completion_sink = EventBusReadInvestigationCompletionSink(
        audit=StateStoreBackgroundTaskCompletionAudit(state_store),
    )
    coordinator = BackgroundTaskCoordinator(
        store=task_store,
        executor=ReadInvestigationBackgroundExecutor(service),
        config=BackgroundTaskCoordinatorConfig(coordinator_id=coordinator_id),
        completion_sink=completion_sink,
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
        interactive=interactive,
    )
    discovery_refresh = (
        provider.discover if isinstance(provider, ReadInvestigationDiscoveryRefresher) else None
    )
    return ReadInvestigationRuntimeBinding(
        consumer=consumer,
        coordinator=coordinator,
        wake_signal=wake_signal,
        completion_sink=completion_sink,
        interactive=interactive,
        interactive_run_store=interactive_run_store,
        interactive_progress_store=interactive_progress_store,
        interactive_completion_store=interactive_completion_store,
        interactive_completion_publisher=InteractiveReadInvestigationCompletionPublisher(
            store=interactive_completion_store,
        ),
        interactive_completion_wake=interactive_completion_wake,
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
