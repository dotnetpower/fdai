"""Opt-in loopback PostgreSQL evidence for knowledge leases and generation activation."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fdai_document_worker_service.adapters.postgres import (
    PostgresDocumentMetadataStore,
    PostgresWorkerConfig,
)
from fdai_document_worker_service.adapters.processing import PgvectorDocumentIndex
from fdai_ingestion_api_service.cloud_knowledge.collector import SourceState
from fdai_ingestion_api_service.cloud_knowledge.store import PostgresCloudKnowledgeStore
from fdai_service_contracts import (
    DocumentIndexState,
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentState,
    DocumentWorkerClaim,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    SourceStorageMode,
    UploadSession,
)
from fdai_service_contracts.cloud_knowledge import SourceCheckReceipt, canonical_bytes
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[3]


def _module(path: Path) -> object:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    raw = os.environ.get("FDAI_CLOUD_KNOWLEDGE_TEST_DSN", "")
    if not raw:
        pytest.skip("task-owned loopback PostgreSQL was not selected")
    parameters = conninfo_to_dict(raw)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("cloud knowledge tests require an explicit loopback database")
    database_name = "cloud_test_" + uuid4().hex
    with psycopg.connect(raw, autocommit=True) as connection:
        connection.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(database_name))
        )
    # The real Core reader deliberately clears connection options. A separate database
    # preserves that boundary and isolates every adapter without a search_path override.
    dsn = make_conninfo(raw, dbname=database_name)
    try:
        with psycopg.connect(dsn) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            migration = _module(
                ROOT / "service-migrations/branches/document-ingestion-api/versions/"
                "20260914_cloud_knowledge.py"
            )
            monkeypatch.setattr(migration, "op", SimpleNamespace(execute=connection.execute))
            migration.upgrade()
        yield dsn
    finally:
        with psycopg.connect(raw, autocommit=True) as connection:
            connection.execute(
                psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(database_name)
                )
            )


async def test_database_claims_are_exclusive_expire_and_reject_stale_completion(
    database: str,
) -> None:
    store = PostgresCloudKnowledgeStore(dsn=database)
    checkpoint = await store.get("a" * 64, "apim")
    claims = await asyncio.gather(*(store.claim("a" * 64, "apim", 0) for _ in range(3)))
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    state = SourceState(
        last_attempt=SourceCheckReceipt(
            source_id="apim",
            source_url="https://example.com/apim",
            checked_at=datetime.now(tz=UTC),
            outcome="failed",
            collector_id="test",
        )
    )
    await store.finish("a" * 64, "apim", checkpoint, winners[0], state)
    assert (await store.get("a" * 64, "apim")).revision == 1
    with pytest.raises(RuntimeError, match="lease or revision"):
        await store.finish("a" * 64, "apim", checkpoint, winners[0], state)
    checkpoint = await store.get("a" * 64, "apim")
    expired = await store.claim("a" * 64, "apim", 1)
    with psycopg.connect(database) as connection:
        connection.execute(
            "UPDATE document_knowledge_source SET lease_until = "
            "clock_timestamp() - interval '1 second'"
        )
    renewed = await store.claim("a" * 64, "apim", 1)
    assert renewed is not None and renewed != expired
    assert expired is not None
    with pytest.raises(RuntimeError):
        await store.finish("a" * 64, "apim", checkpoint, expired, state)
    with psycopg.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM document_knowledge_check").fetchone() == (
            1,
        )


async def test_database_release_high_water_is_monotonic_and_retry_exact(database: str) -> None:
    store = PostgresCloudKnowledgeStore(dsn=database)
    args = {
        "collection_id": "cloud",
        "sequence": 2,
        "digest": "b" * 64,
        "upload_id": uuid4(),
        "payload": '{"actor_id":"one"}',
    }
    assert await store.reserve_release(**args) == {"actor_id": "one"}
    assert await store.reserve_release(**(args | {"payload": '{"actor_id":"two"}'})) == {
        "actor_id": "one",
    }
    with pytest.raises(ValueError, match="different content"):
        await store.reserve_release(**(args | {"digest": "c" * 64}))
    with pytest.raises(ValueError, match="replay"):
        await store.reserve_release(**(args | {"sequence": 1}))
    assert await store.next_sequence("cloud") == 3


@pytest.mark.parametrize("tamper", ["none", "text", "provenance", "after_readback"])
@pytest.mark.parametrize("representation", ["legacy", "structured"])
async def test_cloud_generation_activation_is_atomic_and_lexical_has_no_model_call(
    database: str,
    tamper: str,
    representation: str,
) -> None:
    fixture = _module(
        ROOT / "services/document-processing-worker/tests/test_cloud_knowledge_extraction.py"
    )
    release, original_version = fixture.release_version()
    if representation == "structured":
        from fdai_service_contracts.cloud_knowledge import content_digest
        from fdai_service_contracts.cloud_knowledge_release import (
            KnowledgeStructuredReleaseManifest,
        )
        from fdai_service_contracts.cloud_knowledge_structure import (
            CloudArticleBlock,
            CloudStructuredDocument,
            excerpt_digest,
        )

        paragraphs = ("Premium only.", "Premium v2 uses other requirements.")
        text = "\n\n".join(paragraphs)
        evidence = release.documents[0].evidence.model_copy(
            update={"normalized_sha256": content_digest(text.encode())}
        )
        document = CloudStructuredDocument(
            evidence=evidence,
            title="APIM",
            text=text,
            derived_at=release.package_created_at,
            blocks=(
                CloudArticleBlock(
                    block_id="networking",
                    kind="paragraph",
                    start=0,
                    end=len(paragraphs[0]),
                    heading_path=("Networking",),
                ),
                CloudArticleBlock(
                    block_id="exception",
                    kind="paragraph",
                    start=len(paragraphs[0]) + 2,
                    end=len(text),
                    heading_path=("Exception",),
                ),
            ),
        )
        release = KnowledgeStructuredReleaseManifest.model_validate(
            release.model_dump(exclude={"schema_version", "reader_version", "documents"})
            | {"documents": (document,), "excerpt_digests": (excerpt_digest(document),)}
        )
        binding = original_version.cloud_knowledge.model_copy(
            update={
                "manifest_digest": release.digest,
                "sources": (evidence,),
                "processing_digests": (document.processing_digest,),
            }
        )
        original_version = original_version.model_copy(
            update={
                "cloud_knowledge": binding,
                "source_sha256": release.digest,
                "size_bytes": len(canonical_bytes(release)),
            }
        )
    from fdai_document_worker_service.adapters.cloud_knowledge import cloud_reference_units
    from fdai_service_contracts import DocumentEnvelope

    now = datetime.now(tz=UTC)
    version = original_version.model_copy(
        update={"state": DocumentState.INDEXING, "index_state": DocumentIndexState.BUILDING}
    )
    session = UploadSession(
        upload_id=version.upload_id,
        document_id=version.document_id,
        version_id=version.version_id,
        actor_id="requester",
        source_name=version.source_name,
        collection_id="cloud",
        object_key="quarantine/source",
        media_type_hint=version.media_type,
        expected_size=version.size_bytes,
        expected_sha256=version.source_sha256,
        state=DocumentState.INDEXING,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=version.purposes,
        access=version.access,
        retention=version.retention,
        created_at=now,
        expires_at=now + timedelta(hours=1),
        index_state=DocumentIndexState.BUILDING,
    )
    claim = DocumentWorkerClaim(
        upload_id=version.upload_id,
        stage=DocumentWorkerStage.INDEXING,
        owner="worker",
        attempt_id=uuid4(),
        revision=1,
        status=DocumentWorkerClaimStatus.ACTIVE,
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )
    with psycopg.connect(database) as connection:
        connection.execute("""
            CREATE TABLE document_upload_session (
                upload_id UUID PRIMARY KEY, document_id UUID, version_id UUID, state TEXT,
                revision BIGINT, payload JSONB, updated_at TIMESTAMPTZ);
            CREATE TABLE document_version (
                document_id UUID, version_id UUID, upload_id UUID, state TEXT, active BOOLEAN,
                revision BIGINT, payload JSONB, updated_at TIMESTAMPTZ,
                PRIMARY KEY(document_id, version_id));
            CREATE TABLE knowledge_chunk (
                chunk_id TEXT PRIMARY KEY, doc_id TEXT, text TEXT, source_ref TEXT,
                embedding vector(384), metadata JSONB);
            CREATE TABLE document_worker_claim (
                upload_id UUID, stage TEXT, owner TEXT, attempt_id UUID, revision BIGINT,
                status TEXT, lease_expires_at TIMESTAMPTZ);
            CREATE TABLE document_worker_outbox (
                event_id UUID, idempotency_key TEXT UNIQUE, topic TEXT, partition_key TEXT,
                payload JSONB, created_at TIMESTAMPTZ);
        """)
        connection.execute(
            "INSERT INTO document_upload_session VALUES (%s,%s,%s,%s,1,%s::jsonb,%s)",
            (
                session.upload_id,
                session.document_id,
                session.version_id,
                session.state.value,
                session.model_dump_json(),
                now,
            ),
        )
        connection.execute(
            "INSERT INTO document_version VALUES (%s,%s,%s,%s,false,1,%s::jsonb,%s)",
            (
                version.document_id,
                version.version_id,
                version.upload_id,
                version.state.value,
                version.model_dump_json(),
                now,
            ),
        )
        connection.execute(
            "INSERT INTO document_worker_claim VALUES (%s,%s,%s,%s,1,'active',%s)",
            (
                claim.upload_id,
                claim.stage.value,
                claim.owner,
                claim.attempt_id,
                claim.lease_expires_at,
            ),
        )

    class NoModel:
        async def embed(self, text: str) -> tuple[float, ...]:
            raise AssertionError("offline cloud indexing MUST NOT call a model")

    index = PgvectorDocumentIndex(dsn=database, embedder=NoModel(), dimension=384)
    envelope = DocumentEnvelope(
        document_id=version.document_id,
        version_id=version.version_id,
        source_sha256=version.source_sha256,
        media_type=version.media_type,
        observed_format="text",
        size_bytes=version.size_bytes,
        collection_id="cloud",
        purposes=version.purposes,
        protection_state=version.protection_state,
        access_descriptor_ref=version.access.reference,
        units=cloud_reference_units(version, canonical_bytes(release)),
        extractor_name="cloud-reference",
        extractor_version="1.0.0",
        cloud_knowledge=version.cloud_knowledge,
    )
    assert await index.commit(envelope) == 2
    with psycopg.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM knowledge_chunk WHERE embedding IS NULL "
            "AND metadata->>'retention_state' = 'building'"
        ).fetchone() == (2,)
    metadata = PostgresDocumentMetadataStore(config=PostgresWorkerConfig(dsn=database))
    ready = version.model_copy(
        update={
            "state": DocumentState.READY,
            "revision": 2,
            "active": True,
            "available": False,
            "index_state": DocumentIndexState.ACTIVE,
        }
    )
    event = DocumentLifecycleEvent(
        event_id=uuid4(),
        idempotency_key="activation_pending",
        topic="object.event",
        key=str(version.document_id),
        payload={},
        created_at=now,
    )
    arguments = {
        "claim": claim,
        "expected_upload_state": "indexing",
        "expected_upload_revision": 1,
        "expected_version_state": "indexing",
        "expected_version_revision": 1,
        "event": event,
    }
    ready_session = session.model_copy(update={"state": DocumentState.READY, "revision": 2})
    bad_expected = ready_session.model_copy(update={"supersedes_version_id": uuid4()})
    with pytest.raises(DocumentLifecycleConflictError, match="generation changed"):
        await metadata.transition_worker_stage(bad_expected, ready, **arguments)
    with psycopg.connect(database) as connection:
        assert connection.execute("SELECT active FROM document_version").fetchone() == (False,)
        assert connection.execute("SELECT count(*) FROM document_worker_outbox").fetchone() == (0,)
    await metadata.transition_worker_stage(ready_session, ready, **arguments)
    with psycopg.connect(database) as connection:
        assert connection.execute("SELECT active FROM document_version").fetchone() == (True,)
        assert connection.execute(
            "SELECT count(*) FROM knowledge_chunk WHERE metadata->>'retention_state' = 'verifying'"
        ).fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM document_worker_outbox").fetchone() == (1,)
    from fdai.delivery.persistence.postgres_governed_document_read import (
        PostgresGovernedDocumentReadConfig,
        PostgresGovernedDocumentReadStore,
    )
    from fdai_document_worker_service.adapters.cloud_index_verification import (
        PostgresCloudIndexVerifier,
    )
    from fdai_document_worker_service.cloud_activation import record_cloud_activation

    reader = PostgresGovernedDocumentReadStore(
        config=PostgresGovernedDocumentReadConfig(dsn=database)
    )
    target = release.documents[0].evidence.applicability
    pending = await reader.search_governed(
        "Premium",
        collection_id="cloud",
        allowed_access_refs=frozenset({"collection:cloud"}),
        k=5,
    )
    assert pending.hits == ()
    verifier = PostgresCloudIndexVerifier(dsn=database)

    def event_factory(current_session, current_version, action, extra):
        return DocumentLifecycleEvent(
            event_id=uuid4(),
            idempotency_key=action,
            topic="object.event",
            key=str(current_version.document_id),
            payload={"record": {"action": action, **extra}},
            created_at=now,
        )

    finish = dict(
        metadata=metadata,
        session=ready_session,
        version=ready,
        claim=claim,
        observed_at=now,
        event_factory=event_factory,
    )
    if tamper in {"text", "provenance"}:
        with psycopg.connect(database) as connection:
            if tamper == "text":
                connection.execute("UPDATE knowledge_chunk SET text = 'unapproved source'")
            else:
                connection.execute(
                    "UPDATE knowledge_chunk SET metadata = metadata - 'cloud_source'"
                )
        with pytest.raises(ValueError, match="readback"):
            await verifier.verify(ready, envelope)
        await record_cloud_activation(**finish, index_digest=None)
    else:
        digest = await verifier.verify(ready, envelope)
        if tamper == "after_readback":
            with psycopg.connect(database) as connection:
                connection.execute("UPDATE knowledge_chunk SET text = 'changed after readback'")
            with pytest.raises(DocumentLifecycleConflictError, match="verification changed"):
                await record_cloud_activation(**finish, index_digest=digest)
            await record_cloud_activation(**finish, index_digest=None)
        else:
            await record_cloud_activation(**finish, index_digest=digest)
    with psycopg.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM document_worker_outbox").fetchone() == (2,)
        assert connection.execute("SELECT active FROM document_version").fetchone() == (
            tamper == "none",
        )
    if tamper != "none":
        contained = await reader.search_governed(
            "Premium",
            collection_id="cloud",
            allowed_access_refs=frozenset({"collection:cloud"}),
            k=5,
        )
        assert contained.hits == ()
        return
    matched = await reader.search_applicable_governed(
        "Premium",
        collection_id="cloud",
        allowed_access_refs=frozenset({"collection:cloud"}),
        target=target,
        k=5,
    )
    assert len(matched.hits) == 2
    unmatched = await reader.search_applicable_governed(
        "Premium",
        collection_id="cloud",
        allowed_access_refs=frozenset({"collection:cloud"}),
        target=target.model_copy(update={"service_generation": "v2"}),
        k=5,
    )
    assert unmatched.hits == ()
    unknown_sku = await reader.search_applicable_governed(
        "Premium",
        collection_id="cloud",
        allowed_access_refs=frozenset({"collection:cloud"}),
        target=target.model_copy(update={"skus": ()}),
        k=5,
    )
    assert unknown_sku.hits == ()
    exact_arguments = {
        "context_source": "web_reference",
        "conversation_ref": "synthetic-conversation",
        "k": 5,
    }
    exact_match = await reader.search_applicable_governed_exact(
        "Premium",
        exact_refs=((version.document_id, version.version_id),),
        target=target,
        **exact_arguments,
    )
    assert len(exact_match.hits) == 2
    different_version = await reader.search_applicable_governed_exact(
        "Premium",
        exact_refs=((version.document_id, uuid4()),),
        target=target,
        **exact_arguments,
    )
    assert different_version.hits == ()
    wrong_generation = await reader.search_applicable_governed_exact(
        "Premium",
        exact_refs=((version.document_id, version.version_id),),
        target=target.model_copy(update={"service_generation": "v2"}),
        **exact_arguments,
    )
    assert wrong_generation.hits == ()
