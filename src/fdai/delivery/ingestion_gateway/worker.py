"""Standalone production process for durable document-ingestion worker loops."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Protocol

from fdai.delivery.ingestion_gateway.prod import (
    IngestionDeploymentRole,
    ProdIngestionConfigError,
    build_prod_runtime,
)
from fdai.runtime.bootstrap_lifecycle import install_shutdown_signals, run_main
from fdai.runtime.health import RuntimeHealthServer

_LOGGER = logging.getLogger("fdai.ingestion.worker")


class WorkerLoopService(Protocol):
    """Required worker loops supplied by the production composition."""

    async def run(self) -> None: ...

    async def run_index_commands(self) -> None: ...

    async def reconcile(self) -> None: ...


class IngestionWorkerRuntime(Protocol):
    """Minimal owned runtime needed by the standalone supervisor."""

    @property
    def worker_service(self) -> WorkerLoopService: ...

    @property
    def startup_checks(self) -> tuple[Callable[[], Awaitable[None]], ...]: ...

    @property
    def shutdown_callbacks(self) -> tuple[Callable[[], Awaitable[None]], ...]: ...


class IngestionWorkerSupervisor:
    """Supervise required loops and expose internal process health.

    Readiness is true only while all three required loops are running. A loop
    that returns or fails stops the process, drains every sibling, and closes
    every owned provider so Container Apps can restart the worker safely.
    """

    def __init__(self, *, runtime: IngestionWorkerRuntime, health_port: int) -> None:
        if not 1 <= health_port <= 65_535:
            raise ProdIngestionConfigError(
                "FDAI_INGESTION_WORKER_HEALTH_PORT MUST be between 1 and 65535"
            )
        self._runtime = runtime
        self._health_port = health_port
        self._ready = False
        self._loop_tasks: tuple[asyncio.Task[None], ...] = ()

    @property
    def ready(self) -> bool:
        return (
            self._ready
            and bool(self._loop_tasks)
            and all(not task.done() for task in self._loop_tasks)
        )

    async def run(self, *, stop: asyncio.Event | None = None) -> int:
        """Run until shutdown or the first required loop exits."""
        health = RuntimeHealthServer(port=self._health_port, readiness=lambda: self._ready)
        tasks: tuple[asyncio.Task[None], ...] = ()
        stop_task: asyncio.Task[bool] | None = None
        failure: BaseException | None = None
        try:
            for check in self._runtime.startup_checks:
                await check()
            await health.start()
            tasks = (
                asyncio.create_task(
                    self._runtime.worker_service.run(),
                    name="document-audit-consumer",
                ),
                asyncio.create_task(
                    self._runtime.worker_service.run_index_commands(),
                    name="document-index-consumer",
                ),
                asyncio.create_task(
                    self._runtime.worker_service.reconcile(),
                    name="document-reconciler",
                ),
            )
            self._loop_tasks = tasks
            stop_event = stop or install_shutdown_signals()
            stop_task = asyncio.create_task(stop_event.wait(), name="ingestion-worker-stop")
            self._ready = True
            done, _pending = await asyncio.wait(
                {*tasks, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
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
                    _LOGGER.error(
                        "ingestion_worker_shutdown_failed",
                        exc_info=result,
                    )
                    if failure is None:
                        failure = result
            self._loop_tasks = ()
        if failure is not None:
            raise RuntimeError("ingestion worker runtime failed") from failure
        return 0


async def _run() -> int:
    runtime = build_prod_runtime(role=IngestionDeploymentRole.WORKER)
    raw_port = os.environ.get("FDAI_INGESTION_WORKER_HEALTH_PORT", "8000").strip()
    try:
        health_port = int(raw_port)
    except ValueError as exc:
        raise ProdIngestionConfigError(
            "FDAI_INGESTION_WORKER_HEALTH_PORT MUST be an integer"
        ) from exc
    return await IngestionWorkerSupervisor(runtime=runtime, health_port=health_port).run()


def main() -> int:
    """Run the standalone worker process until SIGTERM or SIGINT."""
    return run_main(_run)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "IngestionWorkerRuntime",
    "IngestionWorkerSupervisor",
    "WorkerLoopService",
    "main",
]
