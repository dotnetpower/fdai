"""Loopback PostgreSQL proofs of bounded state cleanup and narrow conversation summaries."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai_operator_service.postgres_conversation_summaries import conversation_summary_sql
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

NOW = datetime(2026, 10, 30, tzinfo=UTC)
pytestmark = pytest.mark.integration


class _ValidationDsn(str):
    def __repr__(self) -> str:
        return "<isolated validation database>"


@pytest.fixture
async def storage_database() -> AsyncIterator[str]:
    raw = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("FDAI_DATABASE_URL is unset")
    dsn = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    target = conninfo_to_dict(dsn)
    if (
        target.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or str(target.get("port", "5432")) != "5433"
    ):
        pytest.fail("storage validation requires isolated loopback PostgreSQL port 5433")
    schema = f"storage_efficiency_{uuid4().hex}"
    async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
        await connection.execute("SET statement_timeout = '15s'")
        await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        await connection.execute(
            sql.SQL(
                "CREATE TABLE {}.state_kv "
                "(key TEXT PRIMARY KEY, value JSONB NOT NULL, "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            ).format(sql.Identifier(schema))
        )
        await connection.execute(
            sql.SQL("CREATE TABLE {}.deletion_batches (rows INTEGER NOT NULL)").format(
                sql.Identifier(schema)
            )
        )
        await connection.execute(
            sql.SQL(
                "CREATE FUNCTION {}.capture_deletion_batch() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN "
                "INSERT INTO {}.deletion_batches SELECT count(*) FROM removed_rows; "
                "RETURN NULL; END; $$"
            ).format(sql.Identifier(schema), sql.Identifier(schema))
        )
        await connection.execute(
            sql.SQL(
                "CREATE TRIGGER capture_deletion_batch AFTER DELETE ON {}.state_kv "
                "REFERENCING OLD TABLE AS removed_rows FOR EACH STATEMENT "
                "EXECUTE FUNCTION {}.capture_deletion_batch()"
            ).format(sql.Identifier(schema), sql.Identifier(schema))
        )
        await connection.execute(
            sql.SQL(
                "CREATE TABLE {}.conversation_record "
                "(principal_id TEXT, conversation_id TEXT, channel_id TEXT, "
                "started_at TIMESTAMPTZ, last_active TIMESTAMPTZ, status TEXT)"
            ).format(sql.Identifier(schema))
        )
        await connection.execute(
            sql.SQL(
                "CREATE TABLE {}.conversation_turn "
                "(principal_id TEXT, conversation_id TEXT, turn_id TEXT, turn_index INTEGER, "
                "role TEXT, content TEXT)"
            ).format(sql.Identifier(schema))
        )
    try:
        yield _ValidationDsn(make_conninfo(dsn, options=f"-c search_path={schema}"))
    finally:
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
            await connection.execute("SET statement_timeout = '15s'")
            await connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.mark.parametrize("field", [None, "status", "delivery.status"])
async def test_retention_removes_multiple_batches_without_crossing_its_scope(
    storage_database: str, field: str | None
) -> None:
    prefix = "example_%:"
    values = [
        (
            f"{prefix}{index:05}",
            json.dumps(
                {"index": index, "status": "published", "delivery": {"status": "published"}}
            ),
            NOW + timedelta(seconds=index),
        )
        for index in range(1209)
    ]
    values.append(("exampleXX:other", '{"status":"published"}', NOW))
    if field is not None:
        values.append(
            (prefix + "pending", '{"status":"pending","delivery":{"status":"pending"}}', NOW)
        )
    async with await psycopg.AsyncConnection.connect(storage_database) as connection:
        async with connection.cursor() as cursor:
            await cursor.executemany(
                "INSERT INTO state_kv (key,value,updated_at) VALUES (%s,%s::jsonb,%s)", values
            )
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=storage_database))
    try:
        assert (
            await store.delete_states_beyond(
                prefix, retain_newest=3, field=field, value="published" if field else None
            )
            == 1206
        )
        rows, total = await store.read_state_page(
            prefix, limit=3, field=field, value="published" if field else None
        )
        assert total == 3
        assert [row["index"] for row in rows] == [1208, 1207, 1206]
        assert await store.read_state("exampleXX:other") == {"status": "published"}
        if field is not None:
            pending = await store.read_state(prefix + "pending")
            assert pending is not None and pending["status"] == "pending"
        async with await psycopg.AsyncConnection.connect(storage_database) as connection:
            accounting = await (
                await connection.execute(
                    "SELECT max(rows), sum(rows), count(*) FROM deletion_batches"
                )
            ).fetchone()
            assert accounting == (1000, 1206, 2)
    finally:
        await store.aclose()


async def test_state_page_preserves_exact_totals_for_empty_and_offset_pages(
    storage_database: str,
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=storage_database))
    try:
        for index in range(4):
            await store.write_state(f"page:{index}", {"index": index, "body": "x" * 10000})
        rows, total = await store.read_state_page("page:", limit=2, offset=1)
        assert total == 4 and [row["index"] for row in rows] == [2, 1]
        assert await store.read_state_page("page:", limit=2, offset=20) == ((), 4)
        assert await store.read_state_page("missing:", limit=2) == ((), 0)
    finally:
        await store.aclose()


async def test_retention_does_not_delete_a_concurrently_rewritten_selected_row(
    storage_database: str,
) -> None:
    application = "retention-race-" + uuid4().hex
    store = PostgresStateStore(
        config=PostgresStateStoreConfig(
            dsn=make_conninfo(storage_database, application_name=application),
            statement_timeout_ms=5000,
        )
    )
    async with await psycopg.AsyncConnection.connect(storage_database) as connection:
        await connection.execute(
            "INSERT INTO state_kv VALUES ('race:old', '{\"revision\":1}', %s), "
            "('race:new', '{\"revision\":1}', %s)",
            (NOW, NOW + timedelta(seconds=1)),
        )
    try:
        async with (
            await psycopg.AsyncConnection.connect(storage_database) as writer,
            await psycopg.AsyncConnection.connect(storage_database, autocommit=True) as observer,
        ):
            await writer.execute(
                "UPDATE state_kv SET value='{\"revision\":2}' WHERE key='race:old'"
            )
            cleanup = asyncio.create_task(store.delete_states_beyond("race:", retain_newest=1))
            try:
                async with asyncio.timeout(5):
                    while True:
                        waiting = await (
                            await observer.execute(
                                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                                "WHERE application_name=%s AND wait_event_type='Lock')",
                                (application,),
                            )
                        ).fetchone()
                        if waiting == (True,):
                            break
                        if cleanup.done():
                            await cleanup
                            pytest.fail("retention did not wait on the selected row")
                        await asyncio.sleep(0)
                await writer.commit()
                assert await cleanup == 0
                assert await store.read_state("race:old") == {"revision": 2}
            finally:
                await writer.rollback()
                if not cleanup.done():
                    cleanup.cancel()
                    with suppress(asyncio.CancelledError):
                        await cleanup
    finally:
        await store.aclose()


async def test_conversation_summary_preserves_scope_precedence_ties_and_cursor(
    storage_database: str,
) -> None:
    requests = [
        ("old:a", "reader", "older", "first question", NOW),
        ("old:z", "reader", "older", "last question", NOW + timedelta(minutes=1)),
        ("new:a", "reader", "newer", "tie first", NOW + timedelta(hours=1)),
        ("new:z", "reader", "newer", "tie last", NOW + timedelta(hours=1)),
        ("legacy:a", "reader", "legacy", "semantic duplicate", NOW + timedelta(days=1)),
        ("foreign:a", "other", "foreign", "private question", NOW + timedelta(days=2)),
    ]
    async with await psycopg.AsyncConnection.connect(
        storage_database, row_factory=dict_row
    ) as connection:
        for key, principal, session, utterance, at in requests:
            await connection.execute(
                "INSERT INTO state_kv (key,value) VALUES (%s,%s::jsonb)",
                (
                    key,
                    json.dumps(
                        {
                            "kind": "operator.semantic_turn",
                            "principal_id": principal,
                            "accepted_at": at.isoformat(),
                            "envelope": {
                                "semantic_turn": {
                                    "session_id": session,
                                    "utterance": utterance,
                                    "turn_id": key,
                                }
                            },
                        }
                    ),
                ),
            )
        await connection.execute(
            "INSERT INTO conversation_record VALUES ('reader','legacy','web',%s,%s,'active')",
            (NOW - timedelta(days=1), NOW - timedelta(days=1)),
        )
        parameters = {"principal_id": "reader", "limit": 10}
        query = conversation_summary_sql(with_cursor=False)
        rows = await (await connection.execute(query, parameters)).fetchall()
        assert [row["conversation_id"] for row in rows] == ["newer", "older", "legacy"]
        assert rows[0]["latest_operator_turn_id"] == "new:z"
        assert rows[0]["first_operator_question"] == "tie first"
        assert rows[1]["first_operator_question"] == "first question"
        assert rows[1]["last_active"] == NOW + timedelta(minutes=1)
        assert rows[2]["channel_id"] == "web"
        later = await (
            await connection.execute(
                conversation_summary_sql(with_cursor=True),
                {
                    **parameters,
                    "before_last_active": rows[0]["last_active"],
                    "before_conversation_id": rows[0]["conversation_id"],
                },
            )
        ).fetchall()
        assert [row["conversation_id"] for row in later] == ["older", "legacy"]
        assert "ARRAY_AGG" not in query


async def test_physical_report_sql_accounts_for_an_entire_nonpublic_schema(
    storage_database: str,
) -> None:
    path = (
        Path(__file__).resolve().parents[3] / "scripts/deployment/local/report-database-growth.py"
    )
    spec = importlib.util.spec_from_file_location("storage_report_sql", path)
    assert spec is not None and spec.loader is not None
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    async with await psycopg.AsyncConnection.connect(storage_database) as connection:
        schema_row = await (await connection.execute("SELECT current_schema()")).fetchone()
        assert schema_row is not None
        rows = await (
            await connection.execute(
                sql.SQL("SELECT * FROM ({}) AS storage WHERE nspname = %s").format(
                    sql.SQL(report._TABLE_STORAGE_SQL)
                ),
                (schema_row[0],),
            )
        ).fetchall()
    assert len(rows) == 4
    for row in rows:
        table = report.table_storage(row)
        assert table["total_bytes"] == sum(
            table[field] for field in ("heap_bytes", "index_bytes", "toast_bytes")
        )
        assert table["heap_bytes"] >= 0


async def test_state_family_diagnostics_are_exact_and_do_not_disclose_identifiers(
    storage_database: str,
) -> None:
    path = (
        Path(__file__).resolve().parents[3] / "scripts/deployment/local/report-database-growth.py"
    )
    spec = importlib.util.spec_from_file_location("storage_family_sql", path)
    assert spec is not None and spec.loader is not None
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    async with await psycopg.AsyncConnection.connect(storage_database) as connection:
        rows = [
            ("pantheon/heimdall/sensing-state/buckets/00", '{"records":[]}'),
            ("pantheon/heimdall/sensing-state/episodes/private-reference", '{"history":[1]}'),
            ("pantheon/heimdall/sensing-state/readiness/private-reference", '{"ready":true}'),
            ("pantheon/saga/audit-chain/verified-head", '{"entries":[]}'),
            ("pantheon/saga/verdict-aggregate-pending", '{"groups":{}}'),
            ("measurement:control-loop:v1:private-event", '{"result":"held"}'),
            ("unreviewed-private-namespace", '{"text":"private body"}'),
        ]
        async with connection.cursor() as cursor:
            await cursor.executemany("INSERT INTO state_kv(key,value) VALUES (%s,%s::jsonb)", rows)
        observed = await (await connection.execute(report._STATE_FAMILY_SQL)).fetchall()
        assert {row[0] for row in observed} == {
            "heimdall_buckets",
            "heimdall_episodes",
            "heimdall_readiness",
            "saga_audit_checkpoint",
            "saga_verdict_aggregate",
            "control_loop_measurements",
            "other",
        }
        assert sum(row[1] for row in observed) == 7
        expected = await (
            await connection.execute("SELECT sum(pg_column_size(value)) FROM state_kv")
        ).fetchone()
        assert expected is not None and sum(row[2] for row in observed) == expected[0]
        assert "private" not in repr(observed)
