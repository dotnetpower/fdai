from __future__ import annotations

import os
import uuid
from collections.abc import Sequence

import psycopg
import pytest

from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.delivery.catalog_search.postgres import (
    PgvectorCatalogSemanticIndex,
    PgvectorCatalogSemanticIndexConfig,
    _content_hash,
    _search_sql,
)
from fdai.shared.providers.catalog_search import CatalogSearchDocument
from fdai.shared.providers.secret_provider import SecretNotFoundError, SecretProvider


class _Embedder:
    async def embed(self, text: str) -> Sequence[float]:
        lowered = text.casefold()
        if "remote desktop" in lowered or "원격 데스크톱" in lowered:
            return (1.0, 0.0, 0.0)
        if "public blob" in lowered or "공개 blob" in lowered:
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)


class _Secrets(SecretProvider):
    async def get(self, name: str) -> str:
        raise SecretNotFoundError(name)


def test_config_rejects_unsafe_values() -> None:
    with pytest.raises(ValueError, match="dsn_secret"):
        PgvectorCatalogSemanticIndexConfig(dsn_secret="")
    with pytest.raises(ValueError, match="identifier"):
        PgvectorCatalogSemanticIndexConfig(dsn_secret="db", table="bad;drop")
    with pytest.raises(ValueError, match="embedding_dim"):
        PgvectorCatalogSemanticIndexConfig(dsn_secret="db", embedding_dim=0)
    with pytest.raises(ValueError, match="statement_timeout_ms"):
        PgvectorCatalogSemanticIndexConfig(dsn_secret="db", statement_timeout_ms=0)
    with pytest.raises(ValueError, match="connect_timeout_s"):
        PgvectorCatalogSemanticIndexConfig(dsn_secret="db", connect_timeout_s=0)
    with pytest.raises(ValueError, match="ivfflat_probes"):
        PgvectorCatalogSemanticIndexConfig(dsn_secret="db", ivfflat_probes=0)


async def test_empty_operations_do_not_resolve_credentials() -> None:
    index = PgvectorCatalogSemanticIndex(
        config=PgvectorCatalogSemanticIndexConfig(dsn_secret="db", embedding_dim=3),
        embedder=_Embedder(),
        secrets=_Secrets(),
    )

    assert await index.upsert(()) == 0
    assert await index.search("", k=10) == ()
    assert await index.search("anything", k=0) == ()


def test_search_sql_carries_hybrid_and_deterministic_rank_contract() -> None:
    sql = _search_sql("catalog_search_document")

    assert "lower(document.rule_id) = lower(%s) AS exact_id" in sql
    assert "ts_rank_cd(" in sql
    assert "document.embedding <=> %s::vector" in sql
    assert "unnest(document.neighbor_ids)" in sql
    assert "similarity(neighbor_id, %s)" in sql
    assert "1.0 / (60.0 + lexical_rank)" in sql
    assert "1.0 / (60.0 + semantic_rank)" in sql
    assert "OR neighbor_score >= 0.3" in sql
    assert "ORDER BY exact_id DESC" in sql
    assert "rule_id ASC" in sql


def test_content_hash_is_stable_and_neighbor_sensitive() -> None:
    document = CatalogSearchDocument("rule.one", "Rule text", ("resource.one",))

    assert _content_hash(document) == _content_hash(document)
    assert _content_hash(document) != _content_hash(
        CatalogSearchDocument("rule.one", "Rule text", ("resource.two",))
    )


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.mark.integration
async def test_postgres_and_in_memory_top_hit_parity() -> None:
    dsn = _requires_live_db()
    table = f"catalog_search_document_{uuid.uuid4().hex[:8]}"
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await connection.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await connection.execute(
            f"""
            CREATE TABLE {table} (
                rule_id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                neighbor_ids TEXT[] NOT NULL,
                search_vector TSVECTOR NOT NULL,
                embedding vector(3) NOT NULL,
                content_hash CHAR(64) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """  # noqa: S608 - generated test-only identifier
        )
        await connection.commit()

    documents = (
        CatalogSearchDocument(
            "network.rdp.deny",
            "Block remote desktop exposure.",
            ("network.nsg", "remediate.restrict-network-access"),
        ),
        CatalogSearchDocument(
            "storage.public.deny",
            "Disable public blob access.",
            ("object-storage", "remediate.disable-public-access"),
        ),
    )
    embedder = _Embedder()
    reference = InMemoryCatalogSemanticIndex(embedder=embedder)
    adapter = PgvectorCatalogSemanticIndex(
        config=PgvectorCatalogSemanticIndexConfig(
            dsn_secret="db",
            table=table,
            embedding_dim=3,
            ivfflat_probes=100,
        ),
        embedder=embedder,
        secrets=_StaticSecrets({"db": dsn}),
    )
    try:
        assert await reference.upsert(documents) == 2
        assert await adapter.upsert(documents) == 2
        assert await adapter.upsert(documents) == 0

        for query in (
            "storage.public.deny",
            "network.nsg",
            "원격 데스크톱 노출 차단",
        ):
            expected = await reference.search(query)
            actual = await adapter.search(query)
            assert actual[0].rule_id == expected[0].rule_id
            assert actual[0].match == expected[0].match
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(f"DROP TABLE IF EXISTS {table}")  # noqa: S608
            await connection.commit()


class _StaticSecrets(SecretProvider):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    async def get(self, name: str) -> str:
        try:
            return self._values[name]
        except KeyError as exc:
            raise SecretNotFoundError(name) from exc
