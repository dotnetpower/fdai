"""Actual source-admission transactions and readback on isolated validation PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import psycopg
import pytest
from fdai.core.operational_context import OPERATING_INTENT_SOURCE_ADMISSION_KEY as KEY
from fdai.delivery.forecast_history_sources import ChangeWindowHistorySource
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_forecast_change_window_history import (
    PostgresForecastChangeWindowHistoryConfig,
    PostgresForecastChangeWindowHistoryReader,
)
from fdai.runtime.change_window_history import CHANGE_WINDOW_ADMISSION_HISTORY_PREFIX as PREFIX
from fdai.runtime.change_window_history import persist_change_window_admission
from fdai.shared.providers.operating_model import OperatingModelSnapshot
from psycopg.conninfo import conninfo_to_dict

from tests.persistence.test_postgres_state_store import saga_database  # noqa: F401
from tests.runtime.test_change_window_admission_history import admission, persist, retained
from tests.runtime.test_change_window_history import NOW, _window

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def validation_database_only() -> None:
    configured = os.environ.get("FDAI_DATABASE_URL")
    if not configured:
        pytest.skip("run through scripts/automation/with-local-test-database.py")
    parts = conninfo_to_dict(configured.replace("postgresql+psycopg://", "postgresql://", 1))
    if parts.get("host") not in {"127.0.0.1", "localhost", "::1"} or parts.get("port") != "5433":
        pytest.fail("admission regression requires isolated loopback validation PostgreSQL 5433")


def reader(dsn: str) -> PostgresForecastChangeWindowHistoryReader:
    return PostgresForecastChangeWindowHistoryReader(
        config=PostgresForecastChangeWindowHistoryConfig(dsn=dsn)
    )


async def test_actual_full_snapshot_re_admission_and_restart_readback(
    saga_database: str,  # noqa: F811
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        for minute, revision in enumerate(("intent-rev-1", "intent-rev-2", "intent-rev-1")):
            assert await persist(
                store,
                minute=minute,
                revision=revision,
                windows=(_window("window-1", start=0, end=30),),
            )
        current, _ = await retained(store)
        assert current["revision"] == 3
    finally:
        await store.aclose()
    restarted = reader(saga_database)
    read = await restarted.read_history(
        subject_ref="resource-example",
        start_at=NOW,
        end_at=NOW + timedelta(minutes=30),
        known_at=NOW + timedelta(minutes=40),
    )
    assert read.coverage is not None and read.coverage.watermark == current["history_ref"]
    assert len(read.rows) == 1 and read.rows[0].source_revision == "intent-rev-1"
    assert read.rows[0].recorded_at == NOW + timedelta(minutes=2)
    source_read = await ChangeWindowHistorySource(reader=restarted).read(
        subject_ref="resource-example",
        start_at=NOW,
        end_at=NOW + timedelta(minutes=30),
        known_at=NOW + timedelta(minutes=40),
    )
    assert not source_read.checkpoint.complete and not source_read.records


async def test_actual_concurrent_first_admission_has_one_winner_and_one_audit(
    saga_database: str,  # noqa: F811
) -> None:
    stores = [
        PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database)) for _ in range(2)
    ]
    try:
        results = await asyncio.gather(
            *(
                persist_change_window_admission(
                    store,
                    key=KEY,
                    admission=admission(minute=minute),
                    current=None,
                    snapshot=OperatingModelSnapshot("intent-rev-1", (), ()),
                    source_revision="intent-rev-1",
                    document_digest="sha256:" + "1" * 64,
                    recorded_at=NOW + timedelta(minutes=minute),
                )
                for store, minute in zip(stores, (1, 2), strict=True)
            )
        )
        current, _ = await retained(stores[0])
        assert current["revision"] == 1
        assert sorted(results) == [False, True]
        rows, total = await stores[0].read_state_page(PREFIX, limit=10)
        audits, _ = await stores[0].read_audit_entries(limit=10)
        assert len(rows) == total == len(audits) == current["revision"]
        assert all(item["action_kind"] == "operating_intent.source_admission" for item in audits)
        assert await stores[0].verify_chain()
    finally:
        for store in stores:
            await store.aclose()


async def test_actual_legacy_zero_revision_migrates_without_inventing_an_anchor(
    saga_database: str,  # noqa: F811
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        await store.write_state(KEY, {"status": "unavailable"})
        assert await persist(store, minute=1)
        current, entry = await retained(store)
        assert current["revision"] == 1 and entry["previous_ref"] is None
        assert entry["recorded_at"] == (NOW + timedelta(minutes=1)).isoformat()
    finally:
        await store.aclose()


async def test_actual_audit_failure_rolls_back_both_rows(
    saga_database: str,  # noqa: F811
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        assert await persist(store)
        before = await retained(store)
        async with await psycopg.AsyncConnection.connect(saga_database) as connection:
            await connection.execute(
                "CREATE FUNCTION reject_admission_audit() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN RAISE EXCEPTION 'injected audit failure'; END $$"
            )
            await connection.execute(
                "CREATE TRIGGER reject_admission BEFORE INSERT ON audit_log "
                "FOR EACH ROW EXECUTE FUNCTION reject_admission_audit()"
            )
        with pytest.raises(psycopg.Error, match="injected audit failure"):
            await persist(store, minute=1, status="quarantined")
        assert await retained(store) == before
        assert (await store.read_state_page(PREFIX, limit=10))[1] == 1
    finally:
        await store.aclose()


async def test_actual_missing_latest_entry_and_corruption_never_fall_back(
    saga_database: str,  # noqa: F811
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        assert await persist(store)
        assert await persist(store, minute=1, status="quarantined")
        current, entry = await retained(store)
        key = str(current["history_ref"])
        await store.write_state(key, {**entry, "document_digest": "tampered"})
        with pytest.raises(ValueError, match="digest"):
            await reader(saga_database).read_history(
                subject_ref="resource-example",
                start_at=NOW,
                end_at=NOW,
                known_at=NOW + timedelta(minutes=2),
            )
        assert await store.delete_state(key)
        with pytest.raises(ValueError, match="head"):
            await reader(saga_database).read_history(
                subject_ref="resource-example",
                start_at=NOW,
                end_at=NOW,
                known_at=NOW + timedelta(minutes=2),
            )
    finally:
        await store.aclose()


async def test_actual_denial_is_visible_not_an_empty_positive_snapshot(
    saga_database: str,  # noqa: F811
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        assert await persist(store, windows=(_window("window-1", start=0, end=30),))
        assert await persist(store, minute=1, status="unavailable")
        source_read = await ChangeWindowHistorySource(reader=reader(saga_database)).read(
            subject_ref="resource-example",
            start_at=NOW,
            end_at=NOW,
            known_at=NOW + timedelta(minutes=2),
        )
        assert "source_unavailable" in str(source_read.checkpoint.limitation)
        assert not source_read.checkpoint.complete and not source_read.records
    finally:
        await store.aclose()


@pytest.mark.parametrize(("minute", "status"), [(2, "admitted"), (16, "expired")])
async def test_actual_compact_revalidation_preserves_fact_time_and_handles_missing_body(
    saga_database: str,  # noqa: F811
    minute: int,
    status: str,
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        windows = (_window("window-1", start=0, end=30),)
        assert await persist(store, windows=windows)
        original, _ = await retained(store)
        assert await persist(store, minute=1, windows=windows)
        current, entry = await retained(store)
        assert entry["snapshot_ref"] == original["history_ref"]
        assert entry["windows"] is None
        result = await reader(saga_database).read_history(
            subject_ref="resource-example",
            start_at=NOW,
            end_at=NOW,
            known_at=NOW + timedelta(minutes=minute),
        )
        assert result.source_status == status
        assert result.coverage is not None
        assert result.coverage.watermark == current["history_ref"]
        assert result.coverage.recorded_at == NOW + timedelta(minutes=1)
        assert result.rows[0].recorded_at == NOW
        assert await store.delete_state(str(original["history_ref"]))
        with pytest.raises(ValueError, match="snapshot is missing"):
            await reader(saga_database).read_history(
                subject_ref="resource-example",
                start_at=NOW,
                end_at=NOW,
                known_at=NOW + timedelta(minutes=minute),
            )
    finally:
        await store.aclose()


async def test_actual_unjournalled_legacy_write_invalidates_readback(
    saga_database: str,  # noqa: F811
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        assert await persist(store)
        await store.write_state(
            KEY, {"status": "quarantined", "validated_at": (NOW + timedelta(minutes=1)).isoformat()}
        )
        with pytest.raises(ValueError, match="head"):
            await reader(saga_database).read_history(
                subject_ref="resource-example",
                start_at=NOW,
                end_at=NOW,
                known_at=NOW + timedelta(minutes=2),
            )
    finally:
        await store.aclose()


async def test_actual_changed_admission_cannot_keep_a_stale_journal_pointer(
    saga_database: str,  # noqa: F811
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        assert await persist(store)
        current, _ = await retained(store)
        await store.write_state(KEY, {**current, "status": "quarantined"})
        with pytest.raises(ValueError, match="head payload"):
            await reader(saga_database).read_history(
                subject_ref="resource-example",
                start_at=NOW,
                end_at=NOW,
                known_at=NOW + timedelta(minutes=2),
            )
    finally:
        await store.aclose()
