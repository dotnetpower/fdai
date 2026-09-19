"""Optional real loopback PostgreSQL evidence for connector atomicity and replay."""

import asyncio
import os
import uuid

import psycopg
import pytest
from fdai.delivery.kubernetes_connector_snapshot import ConnectorSnapshotInbox
from fdai.delivery.kubernetes_connector_spool import ConnectorSnapshotSpool
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from .test_kubernetes_connector_snapshot import Registrations
from .test_kubernetes_connector_spool import NOW, REVISION, registration, snapshot

pytestmark = pytest.mark.integration


async def test_postgres_atomic_snapshot_and_restart(tmp_path) -> None:
    __tracebackhide__ = True
    dsn = os.environ.get("FDAI_CONNECTOR_TEST_DSN")
    if not dsn:
        pytest.skip("explicit loopback connector test DSN is unset")
    parsed = conninfo_to_dict(dsn)
    if parsed.get("host") not in {"127.0.0.1", "localhost", "::1"} or parsed.get(
        "hostaddr"
    ) not in {None, "127.0.0.1", "::1"}:
        pytest.fail("connector persistence tests require a loopback-only database")
    schema = "connector_test_" + uuid.uuid4().hex
    try:
        connection = await psycopg.AsyncConnection.connect(dsn, autocommit=True, connect_timeout=3)
    except psycopg.Error:
        pytest.fail("local connector test database is unavailable", pytrace=False)
    try:
        await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        await connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        await connection.execute(
            "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        await connection.execute(
            "CREATE TABLE audit_log (seq BIGSERIAL PRIMARY KEY, event_id UUID, "
            "correlation_id TEXT, actor TEXT, action_kind TEXT, mode TEXT, "
            "entry JSONB, previous_hash TEXT, entry_hash TEXT)"
        )
        scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
        store = PostgresStateStore(
            config=PostgresStateStoreConfig(scoped, connect_timeout_s=3, statement_timeout_ms=3000)
        )
        registrations = Registrations()
        outbox = ConnectorSnapshotSpool(
            tmp_path / "spool",
            registration=registration(),
            stream_id="example",
            allow_cluster_resources=False,
        )
        pending = await outbox.enqueue(
            snapshot(), registration=registration(), producer_revision=REVISION, now=NOW
        )

        def inbox():
            return ConnectorSnapshotInbox(
                store, registrations=registrations, allow_cluster_resources=False, now=lambda: NOW
            )

        receipts = await asyncio.gather(
            *(
                inbox().accept(pending.evidence, pending.content, principal_ref="example")
                for _ in range(8)
            )
        )
        assert sum(receipt.status == "accepted" for receipt in receipts) == 1
        assert await inbox().current(principal_ref="example") == snapshot()
        await outbox.acknowledge(receipts[0])
        second = await outbox.enqueue(
            snapshot(), registration=registration(), producer_revision=REVISION, now=NOW
        )
        assert second.evidence.sequence == 2
        await inbox().accept(second.evidence, second.content, principal_ref="example")
        cursor = await connection.execute("SELECT count(*) FROM audit_log")
        assert (await cursor.fetchone())[0] == 2
        assert await store.verify_chain() is True

        await connection.execute(
            "ALTER TABLE audit_log ADD CONSTRAINT reject_next_audit CHECK (false) NOT VALID"
        )
        third = await outbox.enqueue(
            snapshot(), registration=registration(), producer_revision=REVISION, now=NOW
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            await inbox().accept(third.evidence, third.content, principal_ref="example")
        cursor = await connection.execute("SELECT value->>'revision' FROM state_kv")
        assert (await cursor.fetchone())[0] == "2"
    finally:
        await connection.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )
        await connection.close()
