"""Lifecycle tests for the standalone ingestion worker role."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest

from fdai.delivery.ingestion_gateway import worker as worker_module
from fdai.delivery.ingestion_gateway.prod import (
    IngestionDeploymentRole,
    ProdIngestionConfigError,
    build_prod_runtime,
)
from fdai.delivery.ingestion_gateway.worker import IngestionWorkerSupervisor

_WORKER_ENV = {
    "FDAI_DATABASE_URL": "postgresql://user:password@db.example.com/fdai",
    "FDAI_DATABASE_ROLE": "fdai_ingestion_worker",
    "FDAI_INGESTION_DEPLOYMENT_ROLE": "worker",
    "FDAI_ADLS_ACCOUNT_NAME": "stfdaidocdev",
    "FDAI_ADLS_ACCOUNT_URL": "https://stfdaidocdev.dfs.core.windows.net",
    "FDAI_EMBEDDING_ENDPOINT": "https://example.openai.azure.com",
    "FDAI_EMBEDDING_DEPLOYMENT": "t1-embedding",
    "FDAI_KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
    "FDAI_DOCUMENT_EVENT_TOPIC": "aw.document.events",
}


class _Loops:
    def __init__(self, *, failure: RuntimeError | None = None) -> None:
        self._failure = failure
        self._started = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = 0

    async def run(self) -> None:
        await self._loop()

    async def run_index_commands(self) -> None:
        await self._loop()

    async def reconcile(self) -> None:
        await self._loop()

    async def _loop(self) -> None:
        self._started += 1
        if self._started == 3:
            self.started.set()
        try:
            await self.release.wait()
            if self._failure is not None:
                raise self._failure
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


@dataclass
class _Runtime:
    worker_service: _Loops
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...]
    startup_checks: tuple[Callable[[], Awaitable[None]], ...] = ()


class _Health:
    def __init__(self, *, port: int, readiness: Callable[[], bool]) -> None:
        self.port = port
        self.readiness = readiness
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True


def test_worker_role_requires_no_public_api_environment() -> None:
    with pytest.raises(ProdIngestionConfigError) as raised:
        build_prod_runtime({}, role=IngestionDeploymentRole.WORKER)

    message = str(raised.value)
    assert "FDAI_DATABASE_URL" in message
    assert "FDAI_ENTRA_TENANT_ID" not in message
    assert "FDAI_INGESTION_CORS_ALLOW_ORIGINS" not in message


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FDAI_DATABASE_ROLE", "fdai_ingestion_api"),
        ("FDAI_INGESTION_DEPLOYMENT_ROLE", "api"),
    ],
)
def test_worker_role_rejects_mismatched_identity_contract(name: str, value: str) -> None:
    env = {**_WORKER_ENV, name: value}

    with pytest.raises(ProdIngestionConfigError, match="process role"):
        build_prod_runtime(env, role=IngestionDeploymentRole.WORKER)


async def test_supervisor_starts_stops_and_reports_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health: _Health | None = None

    def health_factory(*, port: int, readiness: Callable[[], bool]) -> _Health:
        nonlocal health
        health = _Health(port=port, readiness=readiness)
        return health

    monkeypatch.setattr(worker_module, "RuntimeHealthServer", health_factory)
    loops = _Loops()
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    stop = asyncio.Event()
    supervisor = IngestionWorkerSupervisor(
        runtime=_Runtime(worker_service=loops, shutdown_callbacks=(close,)),
        health_port=8000,
    )
    task = asyncio.create_task(supervisor.run(stop=stop))
    await loops.started.wait()

    assert supervisor.ready is True
    assert health is not None and health.started and health.readiness()
    stop.set()
    assert await task == 0
    assert supervisor.ready is False
    assert health.closed and not health.readiness()
    assert loops.cancelled == 3
    assert closed is True


async def test_required_loop_failure_drains_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_module, "RuntimeHealthServer", _Health)
    loops = _Loops(failure=RuntimeError("broker unavailable"))
    supervisor = IngestionWorkerSupervisor(
        runtime=_Runtime(worker_service=loops, shutdown_callbacks=()),
        health_port=8000,
    )
    task = asyncio.create_task(supervisor.run(stop=asyncio.Event()))
    await loops.started.wait()
    loops.release.set()
    await asyncio.sleep(0)

    assert supervisor.ready is False

    with pytest.raises(RuntimeError, match="runtime failed"):
        await task
    assert supervisor.ready is False


async def test_startup_check_failure_starts_no_worker_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_module, "RuntimeHealthServer", _Health)
    loops = _Loops()
    closed = False

    async def reject_role() -> None:
        raise ProdIngestionConfigError("effective PostgreSQL role mismatch")

    async def close() -> None:
        nonlocal closed
        closed = True

    supervisor = IngestionWorkerSupervisor(
        runtime=_Runtime(
            worker_service=loops,
            startup_checks=(reject_role,),
            shutdown_callbacks=(close,),
        ),
        health_port=8000,
    )

    with pytest.raises(ProdIngestionConfigError, match="role mismatch"):
        await supervisor.run(stop=asyncio.Event())
    assert loops.started.is_set() is False
    assert supervisor.ready is False
    assert closed is True


def test_worker_module_exposes_no_upload_application() -> None:
    assert not hasattr(worker_module, "app")


async def test_worker_live_health_exposes_no_upload_ingress() -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])
    loops = _Loops()
    stop = asyncio.Event()
    supervisor = IngestionWorkerSupervisor(
        runtime=_Runtime(worker_service=loops, shutdown_callbacks=()),
        health_port=port,
    )
    task = asyncio.create_task(supervisor.run(stop=stop))
    await loops.started.wait()

    async def status(path: str) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        return response.split(b"\r\n", 1)[0]

    assert await status("/live") == b"HTTP/1.1 200 OK"
    assert await status("/ready") == b"HTTP/1.1 200 OK"
    assert await status("/ingestion/uploads") == b"HTTP/1.1 404 Not Found"
    stop.set()
    assert await task == 0
