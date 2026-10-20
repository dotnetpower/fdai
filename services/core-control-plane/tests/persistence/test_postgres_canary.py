"""Indexed latest consumed-canary evidence on an isolated loopback Core schema."""

import asyncio
import importlib.util
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import psycopg
import pytest
from fdai.core.control_loop import _canary
from fdai.delivery.canary_cli import build_canary_event
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_canary import LATEST_CANARY_SQL
from fdai.delivery.self_health_canary import ConsumedCanaryAgeExporter
from fdai.delivery.startup_probe import StaticStartupProbe
from fdai.runtime.readiness import build_startup_readiness_runtime
from fdai.shared.providers.audit_hash import next_hash
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from fdai_service_contracts.self_health import SelfHealthSignalName, SelfHealthSignalStatus

from tests.delivery.test_self_health_canary import NOW, _produce_canary
from tests.persistence.test_postgres_state_store import saga_database as saga_database
from tests.runtime.test_self_health_sources import _catalog, _Embedding, _Validator

ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / (
    "service-migrations/branches/core-control-plane/versions/20261019_core_canary_age_index.py"
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("canary_age_index_test", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _indexes(plan: dict[str, Any]) -> set[str]:
    result = {plan["Index Name"]} if "Index Name" in plan else set()
    for child in plan.get("Plans", []):
        result.update(_indexes(child))
    return result


def _migration_sql(migration: ModuleType) -> tuple[str, str]:
    commands: list[str] = []
    blocks: list[str] = []

    def autocommit():
        blocks.append("autocommit")
        return nullcontext()

    original = migration.op
    migration.op = SimpleNamespace(
        get_context=lambda: SimpleNamespace(autocommit_block=autocommit),
        execute=commands.append,
    )
    try:
        migration.upgrade()
        migration.downgrade()
    finally:
        migration.op = original
    assert len(commands) == 2
    assert blocks == ["autocommit", "autocommit"]
    return commands[0], commands[1]


def test_canary_index_migration_owns_only_concurrent_rebuildable_index() -> None:
    migration = _migration()
    commands = _migration_sql(migration)
    assert migration.migration_owner == "core-control-plane" and migration.owned_tables == ()
    assert "CONCURRENTLY" in commands[0] and "CONCURRENTLY" in commands[1]


@pytest.mark.integration
async def test_latest_canary_query_uses_real_producer_index_and_preserves_audit_rows(
    saga_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    migration = _migration()
    upgrade_sql, downgrade_sql = _migration_sql(migration)
    backend = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    source = ConsumedCanaryAgeExporter(backend, "fdai.canary.age_seconds")
    try:
        with pytest.raises(SelfHealthExporterUnavailableError) as missing:
            await source.observe(now=NOW)
        assert missing.value.reason == "source_missing"
        async with await psycopg.AsyncConnection.connect(
            saga_database, autocommit=True
        ) as connection:
            await connection.execute(upgrade_sql)

        await _produce_canary(
            monkeypatch, backend, at=NOW - timedelta(seconds=120), slot="old-consumed"
        )
        for index in range(513):
            await backend.append_audit_entry(
                {
                    "event_id": str(uuid5(NAMESPACE_URL, f"canary-test-noise:{index}")),
                    "actor": "canary-source-test",
                    "action_kind": "test.non-canary",
                    "mode": "shadow",
                }
            )
        await _produce_canary(
            monkeypatch, backend, at=NOW - timedelta(seconds=60), slot="latest-consumed"
        )
        prefix, truncated = await backend.read_audit_entries(limit=512)
        assert len(prefix) == 512 and truncated
        assert prefix[0]["correlation_id"] == "canary:old-consumed"
        assert all(entry.get("correlation_id") != "canary:latest-consumed" for entry in prefix)
        row = await backend.read_latest_consumed_canary()
        assert row is not None and row["correlation_id"] == "canary:latest-consumed"
        assert (await source.observe(now=NOW)).value == Decimal(60)
        assert await backend.verify_chain()
        runtime = build_startup_readiness_runtime(
            state_store=backend,
            event_bus=LocalEventBus(),
            transition_event_bus=LocalEventBus(),
            event_validator=_Validator(),
            identity=LocalWorkloadIdentity(),
            embedding_model=_Embedding(),
            policy_compile_probe=StaticStartupProbe(probe_id="policy.compile", evidence_key="test"),
            environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
            self_health_catalog=_catalog(),
        )
        assert runtime.self_health_monitor is not None
        snapshot = await runtime.self_health_monitor.collect_and_persist(now=NOW)
        signals = {signal.signal: signal for signal in snapshot.self_health.signals}
        assert signals[SelfHealthSignalName.TIME_SINCE_LAST_SUCCESSFUL_CANARY].value == Decimal(60)
        assert (
            signals[SelfHealthSignalName.CANARY_RESULT].status is SelfHealthSignalStatus.UNAVAILABLE
        )
        assert signals[SelfHealthSignalName.READINESS_PROBE].status is SelfHealthSignalStatus.ALERT
        assert snapshot.execution_authority is False

        async with await psycopg.AsyncConnection.connect(
            saga_database, autocommit=True
        ) as connection:
            await connection.execute("ANALYZE audit_log")
            cursor = await connection.execute("EXPLAIN (FORMAT JSON) " + LATEST_CANARY_SQL)
            explained = await cursor.fetchone()
            assert explained is not None
            assert "audit_log_canary_success_latest_idx" in _indexes(explained[0][0]["Plan"])
            cursor = await connection.execute(
                "SELECT action_kind FROM audit_log ORDER BY seq DESC LIMIT 1"
            )
            assert await cursor.fetchone() == ("runtime.operational-state-recorded",)
            await connection.execute(downgrade_sql)
            cursor = await connection.execute(
                "SELECT to_regclass('audit_log_canary_success_latest_idx'), COUNT(*) FROM audit_log"
            )
            preserved = await cursor.fetchone()
            assert preserved == (None, 518)
    finally:
        await backend.aclose()


@pytest.mark.integration
async def test_corrupt_latest_success_is_unknown_not_a_fallback_to_older_success(
    saga_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        for age, slot in ((120, "older"), (60, "newer")):
            await _produce_canary(monkeypatch, backend, at=NOW - timedelta(seconds=age), slot=slot)
        async with await psycopg.AsyncConnection.connect(saga_database) as connection:
            await connection.execute(
                "UPDATE audit_log SET entry_hash = %s WHERE correlation_id = %s "
                "AND action_kind = 'control_loop.canary'",
                ("0" * 64, "canary:newer"),
            )
        with pytest.raises(SelfHealthExporterUnavailableError) as failure:
            await ConsumedCanaryAgeExporter(backend, "fdai.canary.age_seconds").observe(now=NOW)
        assert failure.value.reason == "source_malformed"
    finally:
        await backend.aclose()


@pytest.mark.integration
@pytest.mark.parametrize("size", [8192, 8193])
async def test_latest_record_transfer_enforces_exact_byte_limit(
    saga_database: str, monkeypatch: pytest.MonkeyPatch, size: int
) -> None:
    backend = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        await _produce_canary(monkeypatch, backend, at=NOW, slot="oversized")
        async with await psycopg.AsyncConnection.connect(saga_database) as connection:
            cursor = await connection.execute(
                "UPDATE audit_log SET entry = jsonb_set(entry, '{extra}', to_jsonb(''::text)) "
                "WHERE action_kind = 'control_loop.canary' "
                "RETURNING octet_length(entry::text)"
            )
            baseline = await cursor.fetchone()
            assert baseline is not None
            cursor = await connection.execute(
                "UPDATE audit_log SET entry = jsonb_set(entry, '{extra}', to_jsonb(%s::text)) "
                "WHERE action_kind = 'control_loop.canary' "
                "RETURNING entry, previous_hash",
                ("x" * (size - baseline[0]),),
            )
            updated = await cursor.fetchone()
            assert updated is not None
            await connection.execute(
                "UPDATE audit_log SET entry_hash = %s WHERE action_kind = 'control_loop.canary'",
                (next_hash(updated[1], updated[0]),),
            )
        row = await backend.read_latest_consumed_canary()
        assert row is not None
        source = ConsumedCanaryAgeExporter(backend, "fdai.canary.age_seconds")
        if size == 8192:
            assert row["entry"] is not None
            assert (await source.observe(now=NOW)).value == Decimal(0)
        else:
            assert row["entry"] is None
            with pytest.raises(SelfHealthExporterUnavailableError) as failure:
                await source.observe(now=NOW)
            assert failure.value.reason == "source_malformed"
    finally:
        await backend.aclose()


@pytest.mark.integration
@pytest.mark.parametrize("cancelled", [False, True])
async def test_consumed_interruption_is_independently_persisted_not_success(
    saga_database: str, cancelled: bool
) -> None:
    backend = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    error = asyncio.CancelledError() if cancelled else RuntimeError("provider detail")

    async def emit(**kwargs: Any) -> None:
        raise error

    host = SimpleNamespace(
        _event_ingest=SimpleNamespace(ingest=lambda event: event),
        _correlate_incident_id=lambda event: None,
        _emit_stage=emit,
        _audit_store=backend,
    )
    try:
        with pytest.raises(type(error)):
            await _canary.process_canary(host, build_canary_event(slot="interrupted", now=NOW))
        async with await psycopg.AsyncConnection.connect(saga_database) as connection:
            cursor = await connection.execute(
                "SELECT seq, entry FROM audit_log ORDER BY seq LIMIT 3"
            )
            rows = await cursor.fetchall()
        assert len(rows) == 2
        assert rows[0][0] < rows[1][0]
        assert [row[1]["outcome"] for row in rows] == [
            "started",
            "cancelled" if cancelled else "failure",
        ]
        assert rows[0][1]["attempt_id"] == rows[1][1]["attempt_id"]
        assert await backend.verify_chain()
        assert await backend.read_latest_consumed_canary() is None
    finally:
        await backend.aclose()
