"""Lifecycle supervisor for the required document worker loops."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol

from fdai_document_worker_service.health import RuntimeHealthServer

_LOGGER = logging.getLogger("fdai.ingestion.worker")


class WorkerLoopService(Protocol):
    def readiness(self) -> bool: ...
    def status(self) -> Mapping[str, object]: ...
    async def run(self) -> None: ...
    async def run_index_commands(self) -> None: ...
    async def run_deletion_requests(self) -> None: ...
    async def drain_outbox(self) -> None: ...
    async def reconcile(self) -> None: ...


class IngestionWorkerRuntime(Protocol):
    @property
    def worker_service(self) -> WorkerLoopService: ...
    @property
    def startup_checks(self) -> tuple[Callable[[], Awaitable[None]], ...]: ...
    @property
    def shutdown_callbacks(self) -> tuple[Callable[[], Awaitable[None]], ...]: ...


class IngestionWorkerSupervisor:
    """Fail the process when any required worker loop stops or fails."""

    def __init__(
        self,
        *,
        runtime: IngestionWorkerRuntime,
        health_port: int,
        readiness_interval_seconds: float = 5.0,
        readiness_freshness_seconds: float = 15.0,
        status_interval_seconds: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 1 <= health_port <= 65_535:
            raise ValueError("FDAI_INGESTION_WORKER_HEALTH_PORT MUST be between 1 and 65535")
        if readiness_interval_seconds <= 0:
            raise ValueError("worker readiness interval MUST be positive")
        if readiness_freshness_seconds < readiness_interval_seconds:
            raise ValueError("worker readiness freshness MUST cover at least one probe interval")
        if status_interval_seconds <= 0:
            raise ValueError("worker status interval MUST be positive")
        self._runtime = runtime
        self._health_port = health_port
        self._readiness_interval_seconds = readiness_interval_seconds
        self._readiness_freshness_seconds = readiness_freshness_seconds
        self._status_interval_seconds = status_interval_seconds
        self._monotonic = monotonic
        self._ready = False
        self._last_dependency_success: float | None = None
        self._loop_tasks: tuple[asyncio.Task[None], ...] = ()

    @property
    def ready(self) -> bool:
        last_success = self._last_dependency_success
        return (
            self._ready
            and last_success is not None
            and self._monotonic() - last_success <= self._readiness_freshness_seconds
            and bool(self._loop_tasks)
            and all(not task.done() for task in self._loop_tasks)
            and self._runtime.worker_service.readiness()
        )

    def status(self) -> dict[str, object]:
        """Return readiness and measured worker signals as separate fields."""
        now = self._monotonic()
        last_success = self._last_dependency_success
        dependency_age = max(0.0, now - last_success) if last_success is not None else None
        return {
            "ready": self.ready,
            "dependency": {
                "last_success_age_seconds": dependency_age,
                "fresh": bool(
                    dependency_age is not None
                    and dependency_age <= self._readiness_freshness_seconds
                ),
            },
            "loops": {task.get_name(): {"running": not task.done()} for task in self._loop_tasks},
            "worker": dict(self._runtime.worker_service.status()),
        }

    async def run(self, *, stop: asyncio.Event | None = None) -> int:
        health = RuntimeHealthServer(
            port=self._health_port,
            readiness=lambda: self.ready,
            status=self.status,
        )
        tasks: tuple[asyncio.Task[None], ...] = ()
        stop_task: asyncio.Task[bool] | None = None
        failure: BaseException | None = None
        try:
            for check in self._runtime.startup_checks:
                await check()
            self._last_dependency_success = self._monotonic()
            await health.start()
            tasks = (
                asyncio.create_task(
                    self._runtime.worker_service.run(), name="document-audit-consumer"
                ),
                asyncio.create_task(
                    self._runtime.worker_service.run_index_commands(),
                    name="document-index-consumer",
                ),
                asyncio.create_task(
                    self._runtime.worker_service.run_deletion_requests(),
                    name="document-deletion-consumer",
                ),
                asyncio.create_task(
                    self._runtime.worker_service.drain_outbox(),
                    name="document-outbox-drainer",
                ),
                asyncio.create_task(
                    self._runtime.worker_service.reconcile(), name="document-reconciler"
                ),
                asyncio.create_task(
                    self._monitor_dependencies(),
                    name="document-dependency-readiness",
                ),
                asyncio.create_task(
                    self._report_status(),
                    name="document-status-reporter",
                ),
            )
            self._loop_tasks = tasks
            stop_event = stop or _install_shutdown_signals()
            stop_task = asyncio.create_task(stop_event.wait(), name="ingestion-worker-stop")
            self._ready = True
            done, _ = await asyncio.wait({*tasks, stop_task}, return_when=asyncio.FIRST_COMPLETED)
            if stop_task not in done:
                completed = next(task for task in tasks if task in done)
                try:
                    await completed
                except BaseException as exc:  # noqa: BLE001 - re-raised after full drain
                    failure = exc
                else:
                    failure = RuntimeError(
                        f"required ingestion worker loop stopped: {completed.get_name()}"
                    )
        finally:
            self._ready = False
            self._last_dependency_success = None
            tracked = (*tasks, stop_task) if stop_task is not None else tasks
            for task in tracked:
                task.cancel()
            await asyncio.gather(*tracked, return_exceptions=True)
            await health.close()
            close_results = await asyncio.gather(
                *(callback() for callback in self._runtime.shutdown_callbacks),
                return_exceptions=True,
            )
            for result in close_results:
                if isinstance(result, BaseException):
                    _LOGGER.error("ingestion_worker_shutdown_failed", exc_info=result)
                    failure = failure or result
            self._loop_tasks = ()
        if failure is not None:
            raise RuntimeError("ingestion worker runtime failed") from failure
        return 0

    async def _monitor_dependencies(self) -> None:
        """Refresh required DB and broker evidence or fail the supervised loop."""
        while True:
            await asyncio.sleep(self._readiness_interval_seconds)
            for check in self._runtime.startup_checks:
                await check()
            self._last_dependency_success = self._monotonic()

    async def _report_status(self) -> None:
        """Periodically emit the same bounded snapshot served by the status endpoint."""
        while True:
            _LOGGER.info("ingestion_worker_status", extra={"worker_status": self.status()})
            await asyncio.sleep(self._status_interval_seconds)


def _install_shutdown_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(handled_signal, stop.set)
    return stop
