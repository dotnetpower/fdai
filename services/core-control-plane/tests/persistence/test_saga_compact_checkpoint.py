"""Actual-role compact Saga recovery and controlled checkpoint allocation comparison."""

import importlib.util
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from fdai.agents import StateStoreAuditChainAdapter, prepare_saga_audit_migration
from fdai.agents._framework.adapters import AuditEntry, _digest
from fdai.agents._framework.audit_chain_journal import (
    AUDIT_CHECKPOINT_KEY,
    AuditJournal,
    entry_hash,
)
from fdai.agents._framework.audit_chain_rehydrate import rehydrate_audit_entries
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_audit_history import _CHAIN_WINDOW_SQL
from fdai.shared.providers.state_store import AUDIT_CHAIN_ENTRY_FIELDS
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tests.agents.test_audit_chain_migration import _checkpoint, _history
from tests.persistence.test_postgres_state_store import saga_database as _saga_database

pytestmark = pytest.mark.integration


class RedactedDSN(str):
    def __repr__(self) -> str:
        return "<isolated audit database>"


@dataclass(frozen=True)
class AuditDatabase:
    admin: str = field(repr=False)
    core: str = field(repr=False)


def _migration_statements(operation: str) -> list[str]:
    path = (
        Path(__file__).resolve().parents[4]
        / "service-migrations/branches/core-control-plane/versions"
        / "20261031_core_saga_compact_checkpoint.py"
    )
    spec = importlib.util.spec_from_file_location("saga_checkpoint_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements: list[str] = []
    module.op = SimpleNamespace(
        execute=statements.append,
        get_context=lambda: SimpleNamespace(autocommit_block=nullcontext),
    )
    getattr(module, operation)()
    return statements


@asynccontextmanager
async def _database() -> AsyncIterator[AuditDatabase]:
    generator = _saga_database.__wrapped__()
    dsn = await anext(generator)
    try:
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as conn:
            await conn.execute("SET statement_timeout='15s'")
            schema = (await (await conn.execute("SELECT current_schema()")).fetchone())[0]
            identity = (
                await (
                    await conn.execute(
                        "SELECT attidentity FROM pg_attribute "
                        "WHERE attrelid='audit_log'::regclass AND attname='seq'"
                    )
                ).fetchone()
            )[0]
            if not identity:
                await conn.execute("CREATE SEQUENCE audit_window_test_seq")
                await conn.execute(
                    "ALTER TABLE audit_log ALTER COLUMN seq "
                    "SET DEFAULT nextval('audit_window_test_seq')"
                )
            await conn.execute(
                sql.SQL(
                    "CREATE INDEX saga_window_test_idx ON audit_log ((entry->>'entry_hash')) "
                    "WHERE jsonb_exists_all(entry::jsonb,{fields}) OR "
                    "(entry->>'actor'='Saga' AND entry->>'action_kind'='audit.record')"
                ).format(fields=sql.Literal(sorted(AUDIT_CHAIN_ENTRY_FIELDS)))
            )
            await conn.execute(
                "ALTER TABLE state_kv SET (autovacuum_enabled=false, "
                "toast.autovacuum_enabled=false)"
            )
            await conn.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO fdai_core").format(sql.Identifier(schema))
            )
            await conn.execute(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON audit_log,state_kv TO fdai_core"
            )
            await conn.execute(
                sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA {} TO fdai_core").format(
                    sql.Identifier(schema)
                )
            )
        options = conninfo_to_dict(dsn).get("options", "")
        yield AuditDatabase(
            RedactedDSN(dsn),
            RedactedDSN(make_conninfo(dsn, options=options + " -c role=fdai_core")),
        )
    finally:
        await generator.aclose()


@pytest.fixture
async def audit_databases() -> AsyncIterator[tuple[AuditDatabase, AuditDatabase]]:
    async with _database() as first, _database() as second:
        yield first, second


async def test_core_role_restores_the_full_window_and_ignores_detached_sequence_collisions(
    audit_databases: tuple[AuditDatabase, AuditDatabase],
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=audit_databases[0].core))
    main, detached = _history(600), _history(2, name="detached")
    try:
        for record in [*detached, *main]:
            await store.append_audit_entry(record)
        plan = prepare_saga_audit_migration(_checkpoint(main), [*detached, *main])
        await store.write_state(AUDIT_CHECKPOINT_KEY, plan.checkpoint())
        chain = StateStoreAuditChainAdapter(store)
        appended = await chain.append(
            principal="Saga", topic="object.event", correlation_id="resumed", payload={"ok": True}
        )
        assert appended.seq == 600
        checkpoint = await store.read_state(AUDIT_CHECKPOINT_KEY)
        assert checkpoint is not None
        assert checkpoint["schema_version"] == "3.0.0"
        assert len(checkpoint["entries"]) == 1
        assert len(chain.entries) == 512
        assert await rehydrate_audit_entries(store) == chain.entries
        assert await store.verify_chain()
        async with store._connection() as conn:
            role = await (await conn.execute("SELECT current_user")).fetchone()
            count = await (await conn.execute("SELECT count(*) AS n FROM audit_log")).fetchone()
        assert role["current_user"] == "fdai_core"
        assert count["n"] == 603
    finally:
        await store.aclose()


async def test_exact_migration_index_supports_bounded_ancestry_and_downgrades(
    audit_databases: tuple[AuditDatabase, AuditDatabase],
) -> None:
    async with await psycopg.AsyncConnection.connect(
        audit_databases[0].admin, autocommit=True, connect_timeout=5
    ) as conn:
        await conn.execute("DROP INDEX saga_window_test_idx")
        for statement in _migration_statements("upgrade"):
            await conn.execute(statement)
        row = await (
            await conn.execute(
                "SELECT indisvalid,indisready FROM pg_index "
                "WHERE indexrelid='audit_log_saga_entry_hash_idx'::regclass"
            )
        ).fetchone()
        assert row == (True, True)
        await conn.execute("SET enable_seqscan=off")
        plan = await (
            await conn.execute(
                sql.SQL("EXPLAIN (FORMAT JSON) ") + _CHAIN_WINDOW_SQL, ("0" * 64, 1, 2)
            )
        ).fetchone()
        assert "audit_log_saga_entry_hash_idx" in json.dumps(plan[0])
        for statement in _migration_statements("downgrade"):
            await conn.execute(statement)
        row = await (
            await conn.execute("SELECT to_regclass('audit_log_saga_entry_hash_idx')")
        ).fetchone()
        assert row == (None,)


async def test_identical_canonical_stream_reduces_actual_checkpoint_allocation(
    audit_databases: tuple[AuditDatabase, AuditDatabase],
) -> None:
    measurements = []
    for compact, database in zip((False, True), audit_databases, strict=True):
        store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=database.core))
        journal = AuditJournal(1, 0, "0" * 64, ())
        try:
            await store.write_state(AUDIT_CHECKPOINT_KEY, journal.encode())
            for index in range(600):
                payload = {"event": index}
                entry = AuditEntry(
                    index,
                    journal.head_hash,
                    "",
                    "Saga",
                    "object.event",
                    f"c-{index}",
                    _digest(payload),
                )
                entry = replace(entry, entry_hash=entry_hash(entry))
                advanced = journal.advanced(entry)
                assert await store.compare_and_set_state_with_audit(
                    AUDIT_CHECKPOINT_KEY,
                    advanced.encode(compact=compact),
                    expected_revision=journal.revision,
                    audit_entry={
                        **asdict(entry),
                        "actor": "Saga",
                        "action_kind": "audit.record",
                        "payload": payload,
                    },
                )
                journal = advanced
            async with store._connection() as conn:
                row = await (
                    await conn.execute(
                        "SELECT pg_total_relation_size('state_kv') AS bytes,"
                        "(SELECT count(*) FROM audit_log) AS records"
                    )
                ).fetchone()
            restored = await rehydrate_audit_entries(store)
            assert tuple(restored) == journal.entries
            assert row["records"] == 600
            measurements.append({"checkpoint_relation_bytes": row["bytes"], "audit_records": 600})
        finally:
            await store.aclose()
    assert (
        measurements[1]["checkpoint_relation_bytes"] * 4
        < measurements[0]["checkpoint_relation_bytes"]
    )
    print(
        json.dumps(
            {"saga_compact_checkpoint": {"legacy": measurements[0], "compact": measurements[1]}}
        )
    )
