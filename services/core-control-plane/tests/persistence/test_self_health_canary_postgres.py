"""Exercise the actual latest-canary SQL only in isolated validation PostgreSQL."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fdai.delivery.canary_cli import build_canary_event
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.self_health_canary import ConsumedCanarySource
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 19, tzinfo=UTC)


@pytest.fixture
async def canary_database() -> AsyncIterator[PostgresStateStore]:
    """Use the wrapper's validation database and remove only this test's schema."""
    configured = os.environ.get("FDAI_DATABASE_URL")
    if not configured:
        pytest.skip("run through scripts/automation/with-local-test-database.py")
    dsn = configured.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = conninfo_to_dict(dsn)
    if parts.get("host") not in {"127.0.0.1", "localhost", "::1"} or parts.get("port") != "5433":
        pytest.fail("canary regression requires isolated loopback validation PostgreSQL on 5433")
    schema = f"self_health_canary_test_{uuid4().hex}"
    async with await psycopg.AsyncConnection.connect(
        dsn, autocommit=True, connect_timeout=5
    ) as admin:
        await admin.execute("SET statement_timeout = '15s'")
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
            async with await psycopg.AsyncConnection.connect(scoped) as setup:
                await setup.execute(
                    "CREATE TABLE audit_log ("
                    "seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                    "action_kind TEXT NOT NULL, entry JSONB NOT NULL, "
                    "unrelated_payload TEXT NOT NULL DEFAULT 'fixture-only')"
                )
            store = PostgresStateStore(
                config=PostgresStateStoreConfig(
                    dsn=scoped, statement_timeout_ms=1250, connect_timeout_s=5
                )
            )
            try:
                yield store
            finally:
                await store.aclose()
        finally:
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            cursor = await admin.execute(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s",
                (schema,),
            )
            assert await cursor.fetchone() == (0,)


def _entry(slot: str, *, recorded_at: datetime = NOW) -> dict[str, object]:
    event = build_canary_event(slot=slot, now=recorded_at - timedelta(seconds=1))
    return {
        "event_id": str(event.event_id),
        "correlation_id": event.correlation_id,
        "idempotency_key": event.idempotency_key,
        "actor": event.source,
        "action_kind": "control_loop.canary",
        "mode": event.mode.value,
        "tier": "canary",
        "decision": "no-op",
        "outcome": "success",
        "latency_ms": 1000,
        "detected_at": event.detected_at.isoformat(),
        "recorded_at": recorded_at.isoformat(),
    }


async def _append(store: PostgresStateStore, *entries: Mapping[str, object]) -> None:
    async with store._connection() as connection:
        async with connection.transaction(), connection.cursor() as cursor:
            await cursor.executemany(
                "INSERT INTO audit_log (action_kind, entry) VALUES (%s, %s)",
                [(item["action_kind"], Jsonb(dict(item))) for item in entries],
            )


def _observe_actual_select(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Observe the real driver response without replacing SQL execution or its rows."""
    observations: list[dict[str, object]] = []
    original = psycopg.AsyncConnection.execute

    async def execute(
        connection: psycopg.AsyncConnection[Any], query: Any, params: Any = None, **kwargs: Any
    ) -> Any:
        cursor = await original(connection, query, params, **kwargs)
        if isinstance(query, str) and "SELECT entry FROM audit_log" in query:
            read_only_cursor = await original(connection, "SHOW transaction_read_only")
            read_only = await read_only_cursor.fetchone()
            timeout_cursor = await original(connection, "SHOW statement_timeout")
            timeout = await timeout_cursor.fetchone()
            observations.append(
                {
                    "sql": " ".join(query.split()),
                    "params": params,
                    "columns": tuple(column.name for column in cursor.description),
                    "rows": cursor.rowcount,
                    "read_only": read_only["transaction_read_only"],
                    "timeout": timeout["statement_timeout"],
                }
            )
        return cursor

    monkeypatch.setattr(psycopg.AsyncConnection, "execute", execute)
    return observations


async def test_latest_sequence_not_largest_timestamp_or_latest_unrelated_row(
    canary_database: PostgresStateStore,
) -> None:
    await _append(canary_database, _entry("first", recorded_at=NOW))
    latest_time = NOW - timedelta(seconds=30)
    await _append(
        canary_database,
        _entry("second", recorded_at=latest_time),
        {"action_kind": "unrelated", "recorded_at": NOW.isoformat()},
    )
    source = ConsumedCanarySource(canary_database)
    assert (await source.read(now=NOW)).recorded_at == latest_time


async def test_invalid_latest_evidence_never_falls_back(
    canary_database: PostgresStateStore,
) -> None:
    await _append(
        canary_database,
        _entry("valid"),
        {**_entry("invalid"), "outcome": "failed"},
    )
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await ConsumedCanarySource(canary_database).read(now=NOW)
    assert caught.value.reason == "source_malformed"


async def test_empty_audit_history_is_missing(
    canary_database: PostgresStateStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = _observe_actual_select(monkeypatch)
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await ConsumedCanarySource(canary_database).read(now=NOW)
    assert caught.value.reason == "source_missing"
    assert len(observations) == 1
    assert observations[0]["rows"] == 0
    assert observations[0]["columns"] == ("entry",)


async def test_large_history_fetches_one_entry_only_in_read_only_bounded_transaction(
    canary_database: PostgresStateStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _append(canary_database, _entry("old", recorded_at=NOW - timedelta(hours=1)))
    await _append(
        canary_database,
        *({"action_kind": "unrelated", "index": index} for index in range(600)),
    )
    await _append(canary_database, _entry("latest"))
    observations = _observe_actual_select(monkeypatch)
    source = ConsumedCanarySource(canary_database)
    receipt = await source.read(now=NOW)
    assert receipt.recorded_at == NOW
    assert await source.read(now=NOW) == receipt
    assert observations == [
        {
            "sql": ("SELECT entry FROM audit_log WHERE action_kind = %s ORDER BY seq DESC LIMIT 1"),
            "params": ("control_loop.canary",),
            "columns": ("entry",),
            "rows": 1,
            "read_only": "on",
            "timeout": "1250ms",
        }
    ]
