"""PgvectorKnowledgeSource - offline unit tests + DB-gated parity test.

The database-touching parity test is gated on ``FDAI_DATABASE_URL`` and
mirrors the skip pattern in
``tests/persistence/test_pgvector_pattern_library.py``. The offline unit
tests exercise config validation, the vector encoder, and metadata
coercion so the adapter has coverage without a live DB.

The parity test proves the production adapter and the in-memory reference
:class:`EmbeddingKnowledgeSource` return the SAME top-K chunk ranking on a
fixed corpus + query (score may differ; order MUST match).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

import psycopg
import pytest

from fdai.delivery.pgvector.knowledge import (
    PgvectorKnowledgeConfig,
    PgvectorKnowledgeSource,
    _coerce_metadata,
    _encode_vector,
)
from fdai.shared.providers.knowledge import (
    EmbeddingKnowledgeSource,
    KnowledgeDocument,
)
from fdai.shared.providers.secret_provider import SecretNotFoundError, SecretProvider

REPO_ROOT = Path(__file__).resolve().parents[3]

_DIM = 384


class _Hash384Embedder:
    """Deterministic 384-dim embedder (network-free, reproducible).

    Each word is hashed into one of the 384 buckets and its count added,
    so cosine similarity reflects word overlap. Identical for the
    reference and the adapter, which is what makes rank parity meaningful.
    """

    async def embed(self, text: str) -> Sequence[float]:
        vec = [0.0] * _DIM
        for word in text.lower().split():
            bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % _DIM
            vec[bucket] += 1.0
        return vec


class _StaticSecrets(SecretProvider):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    async def get(self, name: str) -> str:
        try:
            return self._values[name]
        except KeyError as exc:
            raise SecretNotFoundError(name) from exc


# ---------------------------------------------------------------------------
# Offline unit tests - no database required.
# ---------------------------------------------------------------------------


def test_config_rejects_empty_dsn_secret() -> None:
    with pytest.raises(ValueError, match="dsn_secret"):
        PgvectorKnowledgeConfig(dsn_secret="")


def test_config_rejects_unsafe_table_name() -> None:
    with pytest.raises(ValueError, match="identifier"):
        PgvectorKnowledgeConfig(dsn_secret="db/dsn", table="knowledge; DROP TABLE x")


def test_config_rejects_non_ascii_table_name() -> None:
    # str.isalnum() accepts non-ASCII letters; the strict regex must not.
    with pytest.raises(ValueError, match="identifier"):
        PgvectorKnowledgeConfig(dsn_secret="db/dsn", table="테이블")
    with pytest.raises(ValueError, match="identifier"):
        PgvectorKnowledgeConfig(dsn_secret="db/dsn", table="1bad")  # leading digit


def test_config_rejects_bad_overlap() -> None:
    with pytest.raises(ValueError, match="overlap"):
        PgvectorKnowledgeConfig(dsn_secret="db/dsn", max_chars=100, overlap=100)


def test_config_rejects_zero_top_k() -> None:
    with pytest.raises(ValueError, match="top_k"):
        PgvectorKnowledgeConfig(dsn_secret="db/dsn", top_k=0)


def test_encode_vector_produces_pgvector_literal() -> None:
    vec = [0.0] * _DIM
    vec[0] = 1.0
    vec[-1] = -0.5
    encoded = _encode_vector(vec, dim=_DIM)
    assert encoded.startswith("[1,")
    assert encoded.endswith(",-0.5]")
    assert encoded.count(",") == _DIM - 1


def test_encode_vector_rejects_wrong_dimension() -> None:
    with pytest.raises(ValueError, match="embedding dim"):
        _encode_vector([0.1, 0.2, 0.3], dim=_DIM)


def test_coerce_metadata_variants() -> None:
    assert _coerce_metadata(None) == {}
    assert _coerce_metadata({"a": 1}) == {"a": "1"}
    assert _coerce_metadata('{"b": 2}') == {"b": "2"}
    with pytest.raises(RuntimeError, match="JSON object"):
        _coerce_metadata("[1, 2, 3]")
    with pytest.raises(RuntimeError, match="unexpected type"):
        _coerce_metadata(42)


@pytest.mark.asyncio
async def test_search_zero_k_returns_empty_without_db() -> None:
    source = PgvectorKnowledgeSource(
        config=PgvectorKnowledgeConfig(dsn_secret="db/dsn"),
        embedder=_Hash384Embedder(),
        secrets=_StaticSecrets({"db/dsn": "postgresql://placeholder"}),
    )
    assert await source.search("anything", k=0) == ()


# ---------------------------------------------------------------------------
# Integration parity test - requires a live Postgres+pgvector.
# ---------------------------------------------------------------------------


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


_CORPUS = [
    ("doc-disk", "disk-runbook", "the disk is full clear old logs to free space"),
    ("doc-cpu", "cpu-runbook", "cpu throttle high load scale the node pool out"),
    ("doc-net", "net-runbook", "network latency spike check the load balancer probes"),
]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_topk_rank_parity_with_reference() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)

    embedder = _Hash384Embedder()
    # Namespace doc ids per-run so the shared table does not collide.
    prefix = uuid.uuid4().hex[:8]
    docs = [
        KnowledgeDocument(doc_id=f"{prefix}-{doc_id}", text=text, source_ref=ref)
        for doc_id, ref, text in _CORPUS
    ]

    async def clean_corpus() -> None:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM knowledge_chunk WHERE source_ref = ANY(%s)",
                ([source_ref for _, source_ref, _ in _CORPUS],),
            )

    await clean_corpus()

    reference = EmbeddingKnowledgeSource(embedder=embedder)
    await reference.ingest(docs)

    adapter = PgvectorKnowledgeSource(
        config=PgvectorKnowledgeConfig(dsn_secret="db/dsn", ivfflat_probes=100),
        embedder=embedder,
        secrets=_StaticSecrets({"db/dsn": dsn}),
    )
    try:
        added = await adapter.ingest(docs)
        assert added == len(docs)  # one chunk per short doc

        query = "disk full free space"
        ref_hits = await reference.search(query, k=3)
        adapter_hits = await adapter.search(query, k=3)

        # Top hit is deterministic. CPU and network have the same score for this
        # query, so PostgreSQL may return that tied pair in either order.
        assert adapter_hits[0].chunk_id == ref_hits[0].chunk_id
        assert {c.chunk_id for c in adapter_hits[1:]} == {c.chunk_id for c in ref_hits[1:]}
        assert adapter_hits[0].doc_id == f"{prefix}-doc-disk"
    finally:
        await clean_corpus()
