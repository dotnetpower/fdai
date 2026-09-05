"""Focused checks for ACL-filtered hybrid document retrieval."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fdai_ingestion_api_service.adapters.postgres import (
    PostgresApiConfig,
    PostgresDocumentSearch,
    _vector,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
_DIMENSION = 384


class _QueryEmbedder:
    async def embed(self, text: str) -> Sequence[float]:
        del text
        return (1.0,) + (0.0,) * (_DIMENSION - 1)


async def test_search_uses_one_acl_filtered_relation_for_both_rankers(
    monkeypatch: pytest.MonkeyPatch,
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
        embedder=_QueryEmbedder(),
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
        _vector((1.0,) + (0.0,) * (_DIMENSION - 1), _DIMENSION),
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


@pytest.mark.integration
async def test_live_search_filters_acl_before_hybrid_ranking() -> None:
    url = _requires_live_db()
    _upgrade_head(url)
    dsn = _plain_dsn(url)
    prefix = f"hybrid-{uuid.uuid4().hex[:12]}"
    rows = (
        (
            f"{prefix}-both",
            "needle recovery guide",
            _embedding(0.9, 0.1),
            "shared",
            "collection:shared",
        ),
        (
            f"{prefix}-semantic",
            "capacity recovery guide",
            _embedding(1.0, 0.0),
            "shared",
            "collection:shared",
        ),
        (
            f"{prefix}-lexical",
            "needle operator runbook",
            _embedding(0.0, 1.0),
            "shared",
            "collection:shared",
        ),
        (
            f"{prefix}-restricted",
            "needle restricted runbook",
            _embedding(1.0, 0.0),
            "shared",
            "collection:restricted",
        ),
        (
            f"{prefix}-other",
            "needle other collection",
            _embedding(1.0, 0.0),
            "other",
            "collection:shared",
        ),
    )
    doc_ids = [row[0] for row in rows]

    async def clean() -> None:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM knowledge_chunk WHERE doc_id = ANY(%s)",
                (doc_ids,),
            )

    await clean()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        for doc_id, text, embedding, collection_id, access_ref in rows:
            await connection.execute(
                "INSERT INTO knowledge_chunk "
                "(chunk_id, doc_id, text, source_ref, embedding, metadata) "
                "VALUES (%s, %s, %s, %s, %s::vector, %s::jsonb)",
                (
                    f"{doc_id}#0",
                    doc_id,
                    text,
                    f"source:{doc_id}",
                    embedding,
                    json.dumps(
                        {
                            "governed_document": "true",
                            "collection_id": collection_id,
                            "access_descriptor_ref": access_ref,
                        }
                    ),
                ),
            )

    search = PostgresDocumentSearch(
        config=PostgresApiConfig(dsn=dsn),
        embedder=_QueryEmbedder(),
        dimension=_DIMENSION,
    )
    try:
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
    finally:
        await clean()
