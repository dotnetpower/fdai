"""Cancellation safety for Operator PostgreSQL family queries."""

from __future__ import annotations

import logging
import os

import anyio
import psycopg
import pytest
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)


class _CancelledConnection:
    def __init__(self) -> None:
        self.closed = False
        self.started = anyio.Event()
        self.cancel_count = 0
        self.close_count = 0

    async def execute(self, statement: str, parameters: object) -> object:
        del parameters
        if "set_config" in statement:
            return object()
        self.started.set()
        await anyio.sleep_forever()
        raise AssertionError("cancelled query resumed")

    async def cancel_safe(self, *, timeout: float) -> None:
        assert timeout == 10.0
        self.cancel_count += 1

    async def close(self) -> None:
        self.closed = True
        self.close_count += 1


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


async def test_cancelled_family_query_shields_connection_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _CancelledConnection()

    async def connect(*args: object, **kwargs: object) -> _CancelledConnection:
        del args
        assert kwargs.get("autocommit") is True
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    async def query() -> None:
        await store._fetch_all("SELECT pg_sleep(30) AS slept", {})

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(query)
        await connection.started.wait()
        task_group.cancel_scope.cancel()

    assert connection.cancel_count == 1
    assert connection.close_count == 1
    assert connection.closed is True


@pytest.mark.integration
async def test_cancelled_family_query_does_not_race_transaction_rollback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = PostgresFamilyStore(
        PostgresFamilyStoreConfig(
            dsn=_dsn(),
            statement_timeout_ms=30_000,
        )
    )

    async def query() -> None:
        await store._fetch_all("SELECT pg_sleep(30) AS slept", {})

    with caplog.at_level(logging.WARNING):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(query)
            await anyio.sleep(0.2)
            task_group.cancel_scope.cancel()
        await anyio.sleep(0.2)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "another command is already in progress" not in messages
    assert "error ignored in rollback" not in messages
