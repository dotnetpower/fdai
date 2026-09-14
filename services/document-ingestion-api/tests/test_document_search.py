"""Focused checks for ACL-filtered hybrid document retrieval."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fdai_ingestion_api_service.adapters.postgres import (
    PostgresApiConfig,
    PostgresDocumentSearch,
    _vector,
)
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentDisposition,
    DocumentIndexState,
    DocumentPurpose,
    DocumentRetentionState,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
    SourceStorageMode,
    UploadSession,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
_DIMENSION = 384


class _QueryEmbedder:
    async def embed(self, text: str) -> Sequence[float]:
        del text
        return (1.0,) + (0.0,) * (_DIMENSION - 1)


@pytest.mark.parametrize("lexical", [False, True])
async def test_search_uses_one_acl_filtered_relation_for_both_rankers(
    monkeypatch: pytest.MonkeyPatch,
    lexical: bool,
) -> None:
    statements: list[tuple[str, object]] = []
    rows = [
        {
            "doc_id": "doc-visible",
            "chunk_id": "doc-visible#0",
            "text": "visible text",
            "source_ref": "source:visible",
            "metadata": {"collection_id": "shared"},
            "score": 0.75,
        }
    ]

    class Cursor:
        async def fetchall(self) -> list[dict[str, Any]]:
            return rows

    class Connection:
        async def __aenter__(self) -> Connection:
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        def transaction(self) -> Connection:
            return self

        async def execute(self, statement: str, parameters: object = None) -> Cursor:
            statements.append((statement, parameters))
            return Cursor()

    class AsyncConnection:
        @staticmethod
        async def connect(*args: object, **kwargs: object) -> Connection:
            del args, kwargs
            return Connection()

    monkeypatch.setattr(
        "fdai_ingestion_api_service.adapters.postgres.psycopg.AsyncConnection",
        AsyncConnection,
    )
    search = PostgresDocumentSearch(
        config=PostgresApiConfig(
            dsn="postgresql://placeholder",
            statement_timeout_ms=3210,
        ),
        embedder=None if lexical else _QueryEmbedder(),
        dimension=_DIMENSION,
    )

    hits = await search.search(
        "disk saturation",
        collection_id="shared",
        allowed_access_refs=frozenset({"collection:shared", "group:operators"}),
        k=2,
    )

    assert tuple(hit.chunk_id for hit in hits) == ("doc-visible#0",)
    assert statements[0] == ("SET LOCAL statement_timeout = 3210", None)
    query, parameters = statements[1]
    assert "authorized AS MATERIALIZED" in query
    assert "COALESCE(chunk.metadata->>'disposition', 'governed_knowledge')" in query
    assert "COALESCE(chunk.metadata->>'retention_state', 'live') = 'live'" in query
    assert "(chunk.metadata->>'expires_at')::timestamptz > NOW()" in query
    assert query.count("FROM authorized") == 2
    assert "WHERE lexical_match" in query
    assert "ORDER BY semantic_score DESC, chunk_id ASC" in query
    assert "ORDER BY lexical_score DESC, chunk_id ASC" in query
    assert "ORDER BY score DESC, fused.chunk_id ASC" in query
    assert parameters == (
        None if lexical else _vector((1.0,) + (0.0,) * (_DIMENSION - 1), _DIMENSION),
        "disk saturation",
        60.0,
        "shared",
        ["collection:shared", "group:operators"],
        20,
        20,
        2,
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_search_rejects_nonfinite_query_embeddings(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        _vector((value,) * _DIMENSION, _DIMENSION)


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_VALIDATION_DATABASE_URL") or os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_VALIDATION_DATABASE_URL and FDAI_DATABASE_URL are unset")
    return url


def _upgrade_head(validation_url: str) -> None:
    result = subprocess.run(  # noqa: S603 - controlled repository command
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**os.environ, "FDAI_DATABASE_URL": validation_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _embedding(first: float, second: float) -> str:
    return _vector((first, second) + (0.0,) * (_DIMENSION - 2), _DIMENSION)


def _search_lifecycle_records(
    doc_id: str,
    text: str,
    collection_id: str,
    access_ref: str,
    *,
    state: DocumentState,
    active: bool,
    available: bool,
) -> tuple[UploadSession, DocumentVersion]:
    """Arrange validated synthetic snapshots, not worker activation evidence."""
    document_id = uuid.uuid5(uuid.NAMESPACE_URL, f"fdai:test:document-search:{doc_id}")
    created_at = datetime(2026, 9, 14, tzinfo=UTC)
    content = text.encode("utf-8")
    version = DocumentVersion(
        document_id=document_id,
        version_id=uuid.uuid5(document_id, "version"),
        upload_id=uuid.uuid5(document_id, "upload"),
        source_name=f"{doc_id}.txt",
        source_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        media_type="text/plain",
        observed_format="text",
        state=state,
        protection_state=ProtectionState.NONE,
        access=AccessDescriptor(reference=access_ref, collection_id=collection_id),
        retention=RetentionPolicy(policy_version="hybrid-search-fixture-v1"),
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id="document-search-fixture",
        created_at=created_at,
        updated_at=created_at,
        active=active,
        available=available,
        disposition=DocumentDisposition.GOVERNED_KNOWLEDGE,
        index_state=(
            DocumentIndexState.BUILDING
            if state is DocumentState.INDEXING
            else DocumentIndexState.ACTIVE
        ),
        retention_state=DocumentRetentionState.LIVE,
    )
    session = UploadSession(
        upload_id=version.upload_id,
        document_id=version.document_id,
        version_id=version.version_id,
        actor_id=version.uploader_id,
        source_name=version.source_name,
        collection_id=version.access.collection_id,
        object_key=f"quarantine/{doc_id}/source",
        media_type_hint=version.media_type,
        expected_size=version.size_bytes,
        expected_sha256=version.source_sha256,
        state=version.state,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=version.purposes,
        access=version.access,
        retention=version.retention,
        created_at=version.created_at,
        expires_at=version.created_at + timedelta(minutes=15),
        disposition=version.disposition,
        index_state=version.index_state,
        retention_state=version.retention_state,
    )
    return session, version


@pytest.mark.integration
async def test_live_search_filters_acl_before_hybrid_ranking() -> None:
    url = _requires_live_db()
    _upgrade_head(url)
    dsn = _plain_dsn(url)
    prefix = "hybrid-document-search"
    rows = (
        (
            f"{prefix}-both",
            "needle recovery guide",
            _embedding(0.9, 0.1),
            "shared",
            "collection:shared",
            DocumentState.READY,
            True,
            True,
        ),
        (
            f"{prefix}-semantic",
            "capacity recovery guide",
            _embedding(1.0, 0.0),
            "shared",
            "collection:shared",
            DocumentState.READY,
            True,
            True,
        ),
        (
            f"{prefix}-lexical",
            "needle operator runbook",
            _embedding(0.0, 1.0),
            "shared",
            "collection:shared",
            DocumentState.READY,
            True,
            True,
        ),
        (
            f"{prefix}-restricted",
            "needle needle needle restricted runbook",
            _embedding(1.0, 0.0),
            "shared",
            "collection:restricted",
            DocumentState.READY,
            True,
            True,
        ),
        (
            f"{prefix}-other",
            "needle needle needle other collection",
            _embedding(1.0, 0.0),
            "other",
            "collection:shared",
            DocumentState.READY,
            True,
            True,
        ),
        (
            f"{prefix}-inactive",
            "needle needle needle inactive runbook",
            _embedding(1.0, 0.0),
            "shared",
            "collection:shared",
            DocumentState.READY,
            False,
            True,
        ),
        (
            f"{prefix}-notready",
            "needle needle needle indexing runbook",
            _embedding(1.0, 0.0),
            "shared",
            "collection:shared",
            DocumentState.INDEXING,
            True,
            True,
        ),
        (
            f"{prefix}-available-false",
            "needle needle needle unavailable runbook",
            _embedding(1.0, 0.0),
            "shared",
            "collection:shared",
            DocumentState.READY,
            True,
            False,
        ),
    )
    doc_ids = [row[0] for row in rows]
    eligible_doc_ids = frozenset(doc_ids[:3])
    records = tuple(
        _search_lifecycle_records(
            doc_id,
            text,
            collection_id,
            access_ref,
            state=state,
            active=active,
            available=available,
        )
        for (
            doc_id,
            text,
            _embedding_value,
            collection_id,
            access_ref,
            state,
            active,
            available,
        ) in rows
    )

    async def clean() -> None:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM knowledge_chunk WHERE doc_id = ANY(%s)",
                (doc_ids,),
            )
            for session, version in records:
                await connection.execute(
                    "DELETE FROM document_version WHERE document_id = %s "
                    "AND version_id = %s AND upload_id = %s",
                    (version.document_id, version.version_id, version.upload_id),
                )
                await connection.execute(
                    "DELETE FROM document_upload_session WHERE upload_id = %s "
                    "AND document_id = %s AND version_id = %s",
                    (session.upload_id, session.document_id, session.version_id),
                )

    try:
        await clean()
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            for row, (session, version) in zip(rows, records, strict=True):
                doc_id, text, embedding, *_ = row
                # Use the legacy columns installed by _upgrade_head. Service-owned
                # migrations later add revision columns with a default of 1.
                await connection.execute(
                    "INSERT INTO document_upload_session "
                    "(upload_id, document_id, version_id, state, payload, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        session.upload_id,
                        session.document_id,
                        session.version_id,
                        session.state.value,
                        session.model_dump_json(),
                        session.created_at,
                        session.created_at,
                    ),
                )
                await connection.execute(
                    "INSERT INTO document_version "
                    "(document_id, version_id, upload_id, state, active, payload, "
                    "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        version.document_id,
                        version.version_id,
                        version.upload_id,
                        version.state.value,
                        version.active,
                        version.model_dump_json(),
                        version.created_at,
                        version.updated_at,
                    ),
                )
                metadata = json.dumps(
                    {
                        "governed_document": "true",
                        "document_id": str(version.document_id),
                        "version_id": str(version.version_id),
                        "collection_id": version.access.collection_id,
                        "access_descriptor_ref": version.access.reference,
                        "disposition": version.disposition.value,
                        "retention_state": version.retention_state.value,
                    }
                )
                # Each excluded document alone exceeds the 20-candidate budget for
                # k=3 and outranks eligible chunks lexically and by semantic tie-break.
                for ordinal in range(1 if doc_id in eligible_doc_ids else 21):
                    await connection.execute(
                        "INSERT INTO knowledge_chunk "
                        "(chunk_id, doc_id, text, source_ref, embedding, metadata) "
                        "VALUES (%s, %s, %s, %s, %s::vector, %s::jsonb)",
                        (
                            f"{doc_id}#{ordinal}",
                            doc_id,
                            text,
                            f"source:{doc_id}",
                            embedding,
                            metadata,
                        ),
                    )

        search = PostgresDocumentSearch(
            config=PostgresApiConfig(dsn=dsn),
            embedder=_QueryEmbedder(),
            dimension=_DIMENSION,
        )
        hits = await search.search(
            "needle",
            collection_id="shared",
            allowed_access_refs=frozenset({"collection:shared"}),
            k=3,
        )
        replay_hits = await search.search(
            "needle",
            collection_id="shared",
            allowed_access_refs=frozenset({"collection:shared"}),
            k=3,
        )
        assert {hit.doc_id for hit in hits} == {
            f"{prefix}-both",
            f"{prefix}-semantic",
            f"{prefix}-lexical",
        }
        assert tuple(hit.chunk_id for hit in replay_hits) == tuple(hit.chunk_id for hit in hits)
        assert all(0.0 <= hit.score <= 1.0 for hit in hits)
        # Pin both ranks so filtering only after ranking cannot hide shifted scores.
        both_hit = next(hit for hit in hits if hit.doc_id == f"{prefix}-both")
        assert both_hit.score == pytest.approx((1.0 / 62.0 + 1.0 / 61.0) / (2.0 / 61.0))
    finally:
        primary_error = sys.exception()
        try:
            await clean()
        except Exception as cleanup_error:
            if primary_error is None:
                raise
            primary_error.add_note(
                f"Exact document-search fixture cleanup also failed: {type(cleanup_error).__name__}"
            )
            raise primary_error from cleanup_error
