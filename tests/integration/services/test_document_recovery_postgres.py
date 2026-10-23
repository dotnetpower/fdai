"""Opt-in isolated loopback PostgreSQL evidence for repeatable document recovery."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fdai_document_worker_service.adapters.postgres import (
    PostgresDocumentMetadataStore,
    PostgresWorkerConfig,
)
from fdai_service_contracts import DocumentLifecycleEvent, DocumentWorkerStage
from psycopg.conninfo import conninfo_to_dict, make_conninfo


@pytest.fixture
def database():
    raw = os.environ.get("FDAI_DOCUMENT_RECOVERY_TEST_DSN", "")
    if not raw:
        pytest.skip("task-owned loopback PostgreSQL was not selected")
    raw = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    parameters = conninfo_to_dict(raw)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"} or parameters.get(
        "port"
    ) in {None, "5432"}:
        pytest.fail("document recovery tests require isolated loopback validation PostgreSQL")
    name = "document_recovery_test_" + uuid4().hex
    with psycopg.connect(raw, autocommit=True) as connection:
        connection.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name))
        )
    try:
        yield make_conninfo(raw, dbname=name)
    finally:
        with psycopg.connect(raw, autocommit=True) as connection:
            connection.execute(
                psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(name)
                )
            )


async def test_gated_replay_reclaims_legacy_completed_claim_and_rearms_exact_fact(database):
    with psycopg.connect(database) as connection:
        connection.execute("""
            CREATE TABLE document_worker_claim (
                upload_id UUID, stage TEXT, owner TEXT, attempt_id UUID, revision BIGINT,
                status TEXT, claimed_at TIMESTAMPTZ, lease_expires_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ, PRIMARY KEY (upload_id, stage));
            CREATE TABLE document_worker_outbox (
                event_id UUID PRIMARY KEY, idempotency_key TEXT UNIQUE, topic TEXT,
                partition_key TEXT, payload JSONB, created_at TIMESTAMPTZ,
                published_at TIMESTAMPTZ, attempt_count INTEGER DEFAULT 0,
                next_attempt_at TIMESTAMPTZ DEFAULT clock_timestamp());
        """)
    metadata = PostgresDocumentMetadataStore(config=PostgresWorkerConfig(dsn=database))
    for stage in (
        DocumentWorkerStage.RECEIVED_REPLAY,
        DocumentWorkerStage.PROTECTION_REPLAY,
        DocumentWorkerStage.INSPECTION,
        DocumentWorkerStage.INDEXING,
    ):
        upload_id = uuid4()
        claim = await metadata.claim_worker_stage(
            upload_id, stage, owner="worker", attempt_id=uuid4(), lease_seconds=30
        )
        assert claim is not None
        await metadata.complete_worker_stage(
            upload_id,
            stage,
            owner=claim.owner,
            attempt_id=claim.attempt_id,
            expected_revision=claim.revision,
        )
        replay = await metadata.claim_worker_stage(
            upload_id, stage, owner="restarted-worker", attempt_id=uuid4(), lease_seconds=30
        )
        if stage in {DocumentWorkerStage.INSPECTION, DocumentWorkerStage.INDEXING}:
            assert replay is None
            continue
        assert replay is not None and replay.revision > claim.revision
        assert (
            await metadata.claim_worker_stage(
                upload_id, stage, owner="other-replica", attempt_id=uuid4(), lease_seconds=30
            )
            is None
        )
        assert (
            await metadata.claim_worker_stage(
                upload_id,
                DocumentWorkerStage.INSPECTION,
                owner="other-replica",
                attempt_id=uuid4(),
                lease_seconds=30,
            )
            is None
        )
    event = DocumentLifecycleEvent(
        event_id=uuid4(),
        idempotency_key="document.received:example:1",
        topic="object.event",
        key=str(uuid4()),
        payload={"kind": "document_ingestion"},
        created_at=datetime.now(UTC),
    )
    await metadata.enqueue_event(event)
    with psycopg.connect(database) as connection:
        original = connection.execute("SELECT payload FROM document_worker_outbox").fetchone()[0]
        connection.execute(
            "UPDATE document_worker_outbox SET published_at = clock_timestamp(), "
            "next_attempt_at = clock_timestamp() + INTERVAL '1 day'"
        )
    await metadata.enqueue_event(event.model_copy(update={"created_at": datetime.now(UTC)}))
    with psycopg.connect(database) as connection:
        row = connection.execute(
            "SELECT payload, published_at, next_attempt_at <= clock_timestamp() "
            "FROM document_worker_outbox"
        ).fetchone()
        assert row == (original, None, True)
        connection.execute(
            "UPDATE document_worker_outbox SET next_attempt_at = "
            "clock_timestamp() + INTERVAL '1 day'"
        )
    await metadata.enqueue_event(event)
    with psycopg.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*), bool_and(next_attempt_at > clock_timestamp()) "
            "FROM document_worker_outbox"
        ).fetchone() == (1, True)
