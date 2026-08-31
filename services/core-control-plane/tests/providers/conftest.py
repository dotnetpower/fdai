"""Lifecycle-managed fake and loopback provider-contract fixtures."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from aiokafka.admin import AIOKafkaAdminClient  # type: ignore[import-untyped]
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.shared.providers import EventBus, EventEnvelope, StateStore
from fdai.shared.providers.testing import InMemoryEventBus, InMemoryStateStore
from psycopg import sql

_ROOT = Path(__file__).resolve().parents[4]
_COMPOSE_FILE = _ROOT / "infra" / "local" / "docker-compose.yml"
_REAL_BACKEND_ENV = "FDAI_PROVIDER_CONTRACT_BACKENDS"
_DATABASE_ENV = "FDAI_DATABASE_URL"
_KAFKA_ENV = "FDAI_KAFKA_BOOTSTRAP_SERVERS"


def _real_enabled() -> bool:
    value = os.environ.get(_REAL_BACKEND_ENV, "").strip()
    if value not in {"", "real"}:
        raise pytest.UsageError(f"{_REAL_BACKEND_ENV} must be empty or 'real'")
    return value == "real"


def _loopback_host(host: str | None, field: str) -> str:
    if not host:
        raise pytest.UsageError(f"{field} must include a host")
    if host == "localhost":
        return host
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise pytest.UsageError(f"{field} must use a loopback host") from exc
    if not address.is_loopback:
        raise pytest.UsageError(f"{field} must use a loopback host")
    return host


def _database_urls() -> tuple[str, str, str]:
    raw = os.environ.get(_DATABASE_ENV, "").strip()
    if not raw:
        raise pytest.UsageError(f"{_DATABASE_ENV} is required for the real provider matrix")
    normalized = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlsplit(normalized)
    _loopback_host(parsed.hostname, _DATABASE_ENV)
    database_name = f"fdai_provider_{uuid.uuid4().hex}"
    admin_url = urlunsplit(parsed._replace(path="/postgres"))
    test_url = urlunsplit(parsed._replace(path=f"/{database_name}"))
    return admin_url, test_url, database_name


def _kafka_endpoint() -> str:
    endpoint = os.environ.get(_KAFKA_ENV, "").strip()
    if not endpoint or "," in endpoint:
        raise pytest.UsageError(f"{_KAFKA_ENV} must declare one loopback host:port")
    host, separator, port = endpoint.rpartition(":")
    _loopback_host(host, _KAFKA_ENV)
    if not separator or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise pytest.UsageError(f"{_KAFKA_ENV} must declare one loopback host:port")
    return endpoint


@pytest.fixture(autouse=True)
def no_cloud_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject any Python DNS or socket attempt outside loopback."""
    original = socket.getaddrinfo

    def guarded(host: str | bytes | None, *args: Any, **kwargs: Any) -> Any:
        decoded = host.decode("ascii") if isinstance(host, bytes) else host
        _loopback_host(decoded, "provider contract network")
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)


@pytest.fixture(scope="session")
def provider_contract_postgres_dsn() -> Iterator[str | None]:
    """Create and drop one exact temporary database for the real matrix."""
    if not _real_enabled():
        yield None
        return
    admin_url, test_url, database_name = _database_urls()
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    environment = {**os.environ, _DATABASE_ENV: test_url}
    migration = subprocess.run(  # noqa: S603 - fixed local module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if migration.returncode != 0:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))
        pytest.fail(f"provider contract database migration failed: {migration.stderr}")
    try:
        yield test_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def _state_backends() -> tuple[str, ...]:
    return ("fake", "postgres") if _real_enabled() else ("fake",)


@pytest.fixture(params=_state_backends())
def state_store(
    request: pytest.FixtureRequest,
    provider_contract_postgres_dsn: str | None,
) -> StateStore:
    """Return one fake or isolated PostgreSQL StateStore."""
    if request.param == "fake":
        return InMemoryStateStore()
    if provider_contract_postgres_dsn is None:
        pytest.fail("real StateStore matrix selected without an isolated database")
    return PostgresStateStore(
        config=PostgresStateStoreConfig(
            dsn=provider_contract_postgres_dsn,
            statement_timeout_ms=5_000,
            connect_timeout_s=5,
        )
    )


@dataclass(slots=True)
class EventBusHarness:
    """Bound one EventBus to finite assertions and exact cleanup identities."""

    bus: EventBus
    prefix: str
    real: bool
    topics: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)

    def topic(self, suffix: str) -> str:
        topic = f"{self.prefix}.{suffix}"
        self.topics.add(topic)
        return topic

    def group(self, suffix: str) -> str:
        group = f"{self.prefix}.{suffix}"
        self.groups.add(group)
        return group

    async def collect(
        self,
        topic: str,
        group: str,
        *,
        expected_count: int,
    ) -> tuple[EventEnvelope, ...]:
        self.topics.add(topic)
        self.groups.add(group)
        if not self.real:
            return tuple([envelope async for envelope in self.bus.subscribe(topic, group)])
        stream = self.bus.subscribe(topic, group)
        collected: list[EventEnvelope] = []
        try:
            for _ in range(expected_count):
                collected.append(await asyncio.wait_for(anext(stream), timeout=10))
            try:
                collected.append(await asyncio.wait_for(anext(stream), timeout=0.5))
            except (StopAsyncIteration, TimeoutError):
                pass
        finally:
            close = getattr(stream, "aclose", None)
            if callable(close):
                await close()
        return tuple(collected)


def _event_backends() -> tuple[str, ...]:
    return ("fake", "redpanda") if _real_enabled() else ("fake",)


async def _delete_redpanda_state(
    endpoint: str,
    topics: set[str],
    groups: set[str],
) -> None:
    for group in sorted(groups):
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "compose",
                "-f",
                str(_COMPOSE_FILE),
                "exec",
                "-T",
                "redpanda",
                "rpk",
                "group",
                "delete",
                group,
                "-X",
                "brokers=redpanda:29092",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Redpanda group cleanup failed for {group}: {result.stderr}")
    if topics:
        admin = AIOKafkaAdminClient(bootstrap_servers=endpoint, client_id="fdai-provider-cleanup")
        await admin.start()
        try:
            await admin.delete_topics(sorted(topics))
        finally:
            await admin.close()


@pytest.fixture(params=_event_backends())
async def event_bus_harness(request: pytest.FixtureRequest) -> AsyncIterator[EventBusHarness]:
    """Return one fake or loopback Redpanda bus with bounded cleanup."""
    prefix = f"fdai-provider-{uuid.uuid4().hex}"
    if request.param == "fake":
        yield EventBusHarness(bus=InMemoryEventBus(), prefix=prefix, real=False)
        return
    endpoint = _kafka_endpoint()
    bus = EventHubsKafkaBus(
        identity=None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=endpoint,
            security_protocol="PLAINTEXT",
            client_id=prefix,
            auto_offset_reset="earliest",
            session_timeout_ms=10_000,
            heartbeat_interval_ms=3_000,
            commit_max_records=1,
        ),
    )
    harness = EventBusHarness(bus=bus, prefix=prefix, real=True)
    try:
        yield harness
    finally:
        await bus.close()
        await _delete_redpanda_state(endpoint, harness.topics, harness.groups)
