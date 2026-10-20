"""Actual PostgreSQL recovery preserves logs and resumes the existing Saga adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fdai.agents import StateStoreAuditChainAdapter
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_saga_migration import migrate_saga_audit_chain

from tests.agents.test_audit_chain_migration import _checkpoint, _history
from tests.persistence.test_postgres_state_store import saga_database as saga_database

pytestmark = pytest.mark.integration
_KEY = "pantheon/saga/audit-chain/verified-head"


async def _seed(store: PostgresStateStore):
    main = _history(520)
    records = [*_history(2, name="detached"), *main]
    for record in records:
        await store.append_audit_entry(record)
    checkpoint = _checkpoint(main, length=510)
    await store.write_state(_KEY, checkpoint)
    return checkpoint, records


async def test_reviewed_migration_preserves_history_and_resumes_saga(saga_database):
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        checkpoint, _ = await _seed(store)
        plan = await migrate_saga_audit_chain(store)
        assert plan.source_count == 522
        assert plan.detached_count == 2
        assert plan.journal.length == 520
        assert await store.read_state(_KEY) == checkpoint
        for options, reason in (
            ({}, "stop legacy"),
            ({"legacy_writers_quiesced": True}, "acknowledge"),
            (
                {
                    "legacy_writers_quiesced": True,
                    "preserve_detached_histories": True,
                    "expected_plan_digest": "0" * 64,
                },
                "plan changed",
            ),
        ):
            with pytest.raises(ValueError, match=reason):
                await migrate_saga_audit_chain(
                    store, **{"expected_plan_digest": plan.plan_digest, **options}
                )
            assert await store.read_state(_KEY) == checkpoint
        await migrate_saga_audit_chain(
            store,
            expected_plan_digest=plan.plan_digest,
            legacy_writers_quiesced=True,
            preserve_detached_histories=True,
        )
        chain = StateStoreAuditChainAdapter(store)
        entry = await chain.append(
            principal="Saga",
            topic="object.event",
            correlation_id="recovered",
            payload={"observed": True},
        )
        assert entry.seq == 520
        assert entry.prev_hash == plan.journal.head_hash
        chain.verify()
        assert await store.verify_chain()
        async with store._connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT COUNT(*) AS count FROM audit_log WHERE action_kind = 'audit.record'"
                )
            ).fetchone()
            assert row["count"] == 523
            row = await (
                await connection.execute(
                    "SELECT COUNT(*) AS count FROM audit_log "
                    "WHERE action_kind = 'audit.chain.migrated' "
                    "AND actor = 'saga-audit-migration' "
                    "AND entry->>'owner_agent' = 'Saga' "
                    "AND entry->>'execution_authority' = 'false'"
                )
            ).fetchone()
            assert row["count"] == 1
    finally:
        await store.aclose()


async def test_migration_receipt_failure_rolls_back_checkpoint(saga_database, monkeypatch):
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        checkpoint, _ = await _seed(store)
        plan = await migrate_saga_audit_chain(store)
        monkeypatch.setattr(
            store,
            "_append_audit_in_transaction",
            AsyncMock(side_effect=RuntimeError("unavailable")),
        )
        with pytest.raises(RuntimeError, match="unavailable"):
            await migrate_saga_audit_chain(
                store,
                expected_plan_digest=plan.plan_digest,
                legacy_writers_quiesced=True,
                preserve_detached_histories=True,
            )
        assert await store.read_state(_KEY) == checkpoint
        assert await store.verify_chain()
    finally:
        await store.aclose()


async def test_overlapping_migrations_apply_only_once(saga_database):
    stores = [
        PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database)) for _ in range(2)
    ]
    try:
        await _seed(stores[0])
        plan = await migrate_saga_audit_chain(stores[0])
        results = await asyncio.gather(
            *(
                migrate_saga_audit_chain(
                    store,
                    expected_plan_digest=plan.plan_digest,
                    legacy_writers_quiesced=True,
                    preserve_detached_histories=True,
                )
                for store in stores
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, BaseException) for result in results) == 1
        assert sum(isinstance(result, RuntimeError) for result in results) == 1
        assert await stores[0].verify_chain()
    finally:
        for store in stores:
            await store.aclose()
