"""Bounded PostgreSQL connection recovery for incident notification delivery."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fdai.delivery.persistence import postgres_incident_notification
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_incident_notification import (
    PostgresIncidentNotificationDeliveryStore,
)


async def test_connection_retries_two_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PostgresIncidentNotificationDeliveryStore(
        config=PostgresStateStoreConfig(dsn="postgresql://example.invalid/fdai")
    )
    expected = object()
    attempts = 0
    delays: list[float] = []

    async def connect(*args: Any, **kwargs: Any) -> object:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise psycopg.OperationalError("transient connection failure")
        return expected

    async def sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(
        postgres_incident_notification,
        "asyncio",
        SimpleNamespace(sleep=sleep),
        raising=False,
    )

    assert await store._connect() is expected
    assert attempts == 3
    assert delays == [0.5, 1.0]


async def test_connection_stops_after_three_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PostgresIncidentNotificationDeliveryStore(
        config=PostgresStateStoreConfig(dsn="postgresql://example.invalid/fdai")
    )
    attempts = 0

    async def connect(*args: Any, **kwargs: Any) -> object:
        nonlocal attempts
        attempts += 1
        raise psycopg.OperationalError("persistent connection failure")

    async def sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(
        postgres_incident_notification,
        "asyncio",
        SimpleNamespace(sleep=sleep),
        raising=False,
    )

    with pytest.raises(psycopg.OperationalError, match="persistent connection failure"):
        await store._connect()
    assert attempts == 3
