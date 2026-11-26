from __future__ import annotations

import hashlib
import os
import runpy
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fdai.core.detection.forecast_history import (
    ForecastHistoryBinding,
    StateTransitionForecastHistoryCollector,
)
from fdai.core.detection.forecast_history_producer import ForecastHistoryProducer
from fdai.delivery.forecast_history_sources import (
    FORECAST_LIFECYCLE_HISTORY_SOURCE_IDENTITY,
    FORECAST_LIFECYCLE_HISTORY_SOURCE_REVISION,
    IncarnationLifecycleHistorySource,
)
from fdai.delivery.persistence.postgres_forecast_lifecycle_history import (
    PostgresForecastLifecycleHistoryConfig,
    PostgresForecastLifecycleHistoryReader,
)
from fdai.delivery.persistence.postgres_state_transitions import (
    PostgresStateTransitionStore,
    PostgresStateTransitionStoreConfig,
)

from tests.core.detection import test_forecast_history_producer as core

pytestmark = pytest.mark.skipif(
    not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset"
)
NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
TARGET = core.TARGET
_MIGRATIONS = (
    "20260822_core_operational_archive.py",
    "20260902_core_operational_state_transitions.py",
    "20260905_core_inventory_observation_journal.py",
    "20260906_core_operational_history_lifecycle.py",
)


@pytest.fixture
async def database() -> AsyncIterator[str]:
    """Apply the owning Core migrations in a private loopback schema and verify cleanup."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    dsn = os.environ["FDAI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    if conninfo_to_dict(dsn).get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("forecast history integration requires a loopback database")
    root = Path(__file__).resolve().parents[4] / "service-migrations/branches/core-control-plane"
    statements: list[str] = []
    with patch("alembic.op.execute", side_effect=statements.append):
        for name in _MIGRATIONS:
            runpy.run_path(str(root / "versions" / name))["upgrade"]()
    schema = f"forecast_history_test_{uuid4().hex}"
    async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
        await connection.execute("SET statement_timeout = '15s'")
        await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
        async with await psycopg.AsyncConnection.connect(scoped, connect_timeout=5) as connection:
            for statement in statements:
                await connection.execute(str(statement).replace("TO fdai_core", "TO CURRENT_USER"))
        yield scoped
    finally:
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
            await connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
            cursor = await connection.execute(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (schema,)
            )
            assert await cursor.fetchone() == (0,)


def _observation(name: str) -> str:
    return "sha256:" + hashlib.sha256(name.encode()).hexdigest()


async def _journal(connection, name: str, *, kind: str, mutation: str, at: datetime) -> str:  # type: ignore[no-untyped-def]
    observation = _observation(name)
    await connection.execute(
        "INSERT INTO inventory_observation_journal (observation_id, content_digest, "
        "schema_version, idempotency_key, subject_kind, observation_kind, mutation_kind, "
        "subject_ref, subject_type, properties, properties_complete, links_complete, "
        "tombstone_confirmed, scope_ref, source_identity, source_event_id, source_revision, "
        "effective_at, observed_at, evidence_cutoff, recorded_at) VALUES (%s, %s, '1.0.0', %s, "
        "'object', %s, %s, %s, 'compute.vm', '{}'::jsonb, %s, TRUE, %s, 'scope-example', "
        "'fdai.delivery.azure.arg_resource_changes', %s, 'revision-1', %s, %s, %s, %s)",
        (
            observation,
            observation,
            name,
            kind,
            mutation,
            TARGET,
            kind == "full",
            kind != "full",
            name,
        )
        + (at,) * 4,
    )
    return observation


async def _incarnation(connection, name: str, opened: str, at: datetime, closed=None):  # type: ignore[no-untyped-def]
    identity = _observation("incarnation:" + name)
    closed_at, closing = closed if closed is not None else (None, None)
    await connection.execute(
        "INSERT INTO inventory_resource_incarnation (incarnation_id, resource_ref, "
        "resource_type, provider_identity, lifecycle_boundary_ref, opened_at, closed_at, "
        "opening_observation_id, closing_observation_id, record) "
        "VALUES (%s, %s, 'compute.vm', %s, 'revision-1', %s, %s, %s, %s, '{}'::jsonb)",
        (identity, TARGET, "provider:" + name, at, closed_at, opened, closing),
    )


def _lifecycle_history() -> ForecastHistoryBinding:
    return core.history("resource_lifecycle").model_copy(
        update={
            "source_identity": FORECAST_LIFECYCLE_HISTORY_SOURCE_IDENTITY,
            "source_revision": FORECAST_LIFECYCLE_HISTORY_SOURCE_REVISION,
        }
    )


async def test_lifecycle_ledger_round_trips_confirmed_recreation_and_restart(database: str) -> None:
    import psycopg

    async with await psycopg.AsyncConnection.connect(database, autocommit=True) as connection:
        first = await _journal(
            connection, "open-a", kind="full", mutation="upsert", at=NOW - timedelta(hours=3)
        )
        gone = await _journal(
            connection,
            "gone-a",
            kind="tombstone",
            mutation="delete",
            at=NOW - timedelta(minutes=50),
        )
        back = await _journal(
            connection, "open-b", kind="full", mutation="upsert", at=NOW - timedelta(minutes=30)
        )
        await _incarnation(
            connection, "a", first, NOW - timedelta(hours=3), (NOW - timedelta(minutes=50), gone)
        )
        await _incarnation(connection, "b", back, NOW - timedelta(minutes=30))
    store = PostgresStateTransitionStore(config=PostgresStateTransitionStoreConfig(dsn=database))

    def build() -> ForecastHistoryProducer:
        reader = PostgresForecastLifecycleHistoryReader(
            config=PostgresForecastLifecycleHistoryConfig(dsn=database)
        )
        return ForecastHistoryProducer(
            binding=core.binding("resource_lifecycle"),
            history=_lifecycle_history(),
            source=IncarnationLifecycleHistorySource(reader=reader),
            store=store,
        )

    request = core.request(as_of=NOW)
    reader = PostgresForecastLifecycleHistoryReader(
        config=PostgresForecastLifecycleHistoryConfig(dsn=database)
    )
    ledger = await IncarnationLifecycleHistorySource(reader=reader).read(
        subject_ref=TARGET,
        start_at=request.horizon_started_at - timedelta(hours=1),
        end_at=request.horizon_ended_at,
        known_at=NOW,
    )
    assert ledger.checkpoint.initial_state == "present" and ledger.exhausted
    assert [item.source_state for item in ledger.records] == ["deleted", "present"]
    assert ledger.checkpoint.limitation == "reconciliation_checkpoint_unverified"
    receipt = await build().produce(request)
    assert receipt.transition_count == 0 and receipt.appended
    assert receipt.limitation == "reconciliation_checkpoint_unverified" and not receipt.complete
    restart = await build().produce(core.request(as_of=NOW + timedelta(minutes=1)))
    assert restart.transition_count == 0 and restart.appended
    read = await store.read(
        subject_refs=(TARGET,),
        state_types=("forecast.resource_lifecycle",),
        to_states=None,
        start_at=request.horizon_started_at - timedelta(hours=1),
        end_at=request.horizon_ended_at,
        known_at=NOW + timedelta(minutes=1),
        limit=64,
    )
    assert read.transitions == ()
    assert read.complete is False and "reconciliation_checkpoint_unverified" in (
        read.limitation or ""
    )
    async with await psycopg.AsyncConnection.connect(database, autocommit=True) as connection:
        await connection.execute(
            "INSERT INTO inventory_observation_pending_tombstone (resource_id, resource_type, "
            "scope_ref, observation_id, observed_at, recorded_at) "
            "VALUES (%s, 'compute.vm', 'scope-example', %s, %s, %s)",
            (TARGET, gone, NOW - timedelta(minutes=40), NOW - timedelta(minutes=40)),
        )
    pending = await build().produce(core.request(as_of=NOW + timedelta(minutes=2)))
    assert "pending_tombstone" in (pending.limitation or "").split("+")


async def test_positive_checkpoints_round_trip_through_the_real_store_and_collector(
    database: str,
) -> None:
    store = PostgresStateTransitionStore(config=PostgresStateTransitionStoreConfig(dsn=database))
    request = core.request(as_of=NOW)
    receipts = await core.produce_all(store, core.sources(), request)  # type: ignore[arg-type]
    assert all(item.complete for item in receipts.values())
    collector = StateTransitionForecastHistoryCollector(
        store=store, bindings=tuple(core.history(kind) for kind in core.KINDS)
    )
    slices = await collector.collect(request)
    assert slices["resource_lifecycle"]["resource_deleted"] is True
    assert len(slices["changes"]["intervention_refs"]) == 2
    replay = await core.produce_all(
        store, core.sources(), core.request(as_of=NOW + timedelta(seconds=30))
    )  # type: ignore[arg-type]
    assert all(item.transition_count == 0 and item.complete for item in replay.values())
    changed = await core.producer(
        store,
        core.sources()["changes"],
        **{"full:upsert": "modified", "tombstone:delete": "changed"},
    ).produce(  # type: ignore[arg-type]
        core.request(as_of=NOW + timedelta(minutes=1))
    )
    assert changed.limitation == "conflicting_retained_record"
    gone = core.record("gone", "deleted", 20)
    withdrawn = await core.producer(
        store, core.Source("resource_lifecycle", (gone,), initial="present")
    ).produce(core.request(as_of=NOW + timedelta(minutes=2)))
    assert withdrawn.limitation == "retained_record_withdrawn"
    assert withdrawn.transition_count == 0
