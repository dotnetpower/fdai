from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import psycopg
import pytest

from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.delivery.catalog_search.postgres import (
    PgvectorCatalogSemanticIndex,
    PgvectorCatalogSemanticIndexConfig,
    _content_hash,
    _search_sql,
)
from fdai.delivery.catalog_search.postgres_generation import (
    PgvectorCatalogGenerationConfig,
    _activation_lock_sql,
    _generation_search_sql,
)
from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogGenerationStaleError,
    CatalogSearchDocument,
)
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


_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64
_C = "sha256:" + "c" * 64
_D = "sha256:" + "d" * 64
_E = "sha256:" + "e" * 64


def _compatibility(
    previous_release_digest: str = _A,
    candidate_release_digest: str = _A,
) -> OntologyGenerationCompatibilityReceipt:
    return OntologyGenerationCompatibilityReceipt(
        previous_release_digest=previous_release_digest,
        candidate_release_digest=candidate_release_digest,
        checked_declarations=(),
        added_declarations=(),
    )


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
    with pytest.raises(ValueError, match="identifiers"):
        PgvectorCatalogGenerationConfig(dsn_secret="db", generation_table="bad;drop")


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


def test_generation_search_sql_pins_one_complete_generation() -> None:
    sql = _generation_search_sql("catalog_search_generation_document")

    assert "WHERE document.generation_id = %s" in sql
    assert "document.embedding <=> %s::vector" in sql
    assert "ORDER BY exact_id DESC" in sql


def test_generation_activation_uses_transaction_scoped_corpus_lock() -> None:
    assert _activation_lock_sql() == ("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))")


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


def _catalog_generation(
    generation_id: str,
    *,
    corpus: str = "active",
    ontology_release_digest: str = _A,
    state: str,
    activated_at: datetime,
) -> CatalogGenerationMetadata:
    return CatalogGenerationMetadata(
        generation_id=generation_id,
        generation_digest={"gen-a": _A, "gen-b": _B, "gen-c": _E}[generation_id],
        corpus=corpus,  # type: ignore[arg-type]
        catalog_digest=_C,
        semantic_schema_digest=_D,
        ontology_release_digest=ontology_release_digest,
        embedding_space_id="catalog-search-3",
        embedding_model_version="test-embedder:1",
        embedding_dimension=3,
        state=state,  # type: ignore[arg-type]
        validation_receipt_digest=_B,
        activated_at=activated_at,
    )


@pytest.fixture
async def catalog_generation_store() -> AsyncIterator[
    tuple[PgvectorCatalogSemanticIndex, str, str]
]:
    dsn = _requires_live_db()
    table = f"catalog_search_generation_{uuid.uuid4().hex[:8]}"
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            f"""
            CREATE TABLE {table} (
                generation_id TEXT PRIMARY KEY,
                generation_digest CHAR(71) NOT NULL,
                corpus TEXT NOT NULL,
                catalog_digest CHAR(71) NOT NULL,
                semantic_schema_digest CHAR(71) NOT NULL,
                ontology_release_digest CHAR(71) NOT NULL,
                embedding_space_id TEXT NOT NULL,
                embedding_model_version TEXT NOT NULL,
                embedding_dimension INTEGER NOT NULL,
                state TEXT NOT NULL,
                validation_receipt_digest CHAR(71),
                document_count INTEGER NOT NULL,
                activated_at TIMESTAMPTZ
            )
            """  # noqa: S608 - generated test-only identifier
        )
        await connection.execute(
            f"CREATE UNIQUE INDEX {table}_active_corpus ON {table} (corpus) "  # noqa: S608
            "WHERE state = 'active'"
        )
        await connection.commit()
    store = PgvectorCatalogSemanticIndex(
        config=PgvectorCatalogSemanticIndexConfig(
            dsn_secret="db",
            generation_table=table,
            generation_document_table=f"{table}_document",
            embedding_dim=3,
        ),
        embedder=_Embedder(),
        secrets=_StaticSecrets({"db": dsn}),
    )
    try:
        yield store, dsn, table
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(f"DROP TABLE IF EXISTS {table}")  # noqa: S608
            await connection.commit()


async def _seed_generation(
    *,
    dsn: str,
    table: str,
    metadata: CatalogGenerationMetadata,
) -> None:
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            f"""
            INSERT INTO {table} (
                generation_id, generation_digest, corpus, catalog_digest,
                semantic_schema_digest, ontology_release_digest,
                embedding_space_id, embedding_model_version, embedding_dimension,
                state, validation_receipt_digest, document_count, activated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s)
            """,  # noqa: S608 - generated test-only identifier
            (
                metadata.generation_id,
                metadata.generation_digest,
                metadata.corpus,
                metadata.catalog_digest,
                metadata.semantic_schema_digest,
                metadata.ontology_release_digest,
                metadata.embedding_space_id,
                metadata.embedding_model_version,
                metadata.embedding_dimension,
                metadata.state,
                metadata.validation_receipt_digest,
                metadata.activated_at,
            ),
        )
        await connection.commit()


async def _generation_states(*, dsn: str, table: str) -> set[tuple[str, str]]:
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        cursor = await connection.execute(
            f"SELECT generation_id, state FROM {table}"  # noqa: S608
        )
        rows = await cursor.fetchall()
    return {(str(generation_id), str(state)) for generation_id, state in rows}


@pytest.mark.integration
async def test_postgres_generation_rollback_is_atomic_and_idempotent(
    catalog_generation_store: tuple[PgvectorCatalogSemanticIndex, str, str],
) -> None:
    store, dsn, table = catalog_generation_store
    activated_at = datetime(2026, 8, 6, tzinfo=UTC)
    for metadata in (
        _catalog_generation("gen-a", state="retired", activated_at=activated_at),
        _catalog_generation(
            "gen-b",
            ontology_release_digest=_C,
            state="active",
            activated_at=activated_at,
        ),
    ):
        await _seed_generation(dsn=dsn, table=table, metadata=metadata)
    rolled_back_at = datetime(2026, 8, 7, tzinfo=UTC)
    rollback = {
        "expected_active_generation_id": "gen-b",
        "expected_active_generation_digest": _B,
        "expected_target_generation_digest": _A,
        "expected_validation_receipt_digest": _B,
        "ontology_compatibility_receipt": _compatibility(_A, _C),
        "rolled_back_at": rolled_back_at,
    }

    first = await store.rollback_generation("gen-a", **rollback)  # type: ignore[arg-type]
    duplicate = await store.rollback_generation("gen-a", **rollback)  # type: ignore[arg-type]

    assert duplicate == first
    assert first.reactivated_generation.activated_at == rolled_back_at
    assert await _generation_states(dsn=dsn, table=table) == {
        ("gen-a", "active"),
        ("gen-b", "retired"),
    }


@pytest.mark.integration
async def test_postgres_generation_rollback_rejects_stale_active_revision(
    catalog_generation_store: tuple[PgvectorCatalogSemanticIndex, str, str],
) -> None:
    store, dsn, table = catalog_generation_store
    activated_at = datetime(2026, 8, 6, tzinfo=UTC)
    for metadata in (
        _catalog_generation("gen-a", state="retired", activated_at=activated_at),
        _catalog_generation("gen-b", state="retired", activated_at=activated_at),
        _catalog_generation("gen-c", state="active", activated_at=activated_at),
    ):
        await _seed_generation(dsn=dsn, table=table, metadata=metadata)

    with pytest.raises(CatalogGenerationStaleError, match="stale"):
        await store.rollback_generation(
            "gen-a",
            expected_active_generation_id="gen-b",
            expected_active_generation_digest=_B,
            expected_target_generation_digest=_A,
            expected_validation_receipt_digest=_B,
            ontology_compatibility_receipt=_compatibility(),
            rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
        )

    assert await _generation_states(dsn=dsn, table=table) == {
        ("gen-a", "retired"),
        ("gen-b", "retired"),
        ("gen-c", "active"),
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    ("current", "expected_error"),
    (
        (
            _catalog_generation(
                "gen-b",
                corpus="discovery",
                state="active",
                activated_at=datetime(2026, 8, 6, tzinfo=UTC),
            ),
            "share one corpus",
        ),
        (
            _catalog_generation(
                "gen-b",
                ontology_release_digest=_C,
                state="active",
                activated_at=datetime(2026, 8, 6, tzinfo=UTC),
            ),
            "ontology compatibility receipt mismatch",
        ),
    ),
)
async def test_postgres_generation_rollback_rejects_incompatible_generation(
    catalog_generation_store: tuple[PgvectorCatalogSemanticIndex, str, str],
    current: CatalogGenerationMetadata,
    expected_error: str,
) -> None:
    store, dsn, table = catalog_generation_store
    target = _catalog_generation(
        "gen-a",
        state="retired",
        activated_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    for metadata in (target, current):
        await _seed_generation(dsn=dsn, table=table, metadata=metadata)

    with pytest.raises(ValueError, match=expected_error):
        await store.rollback_generation(
            "gen-a",
            expected_active_generation_id="gen-b",
            expected_active_generation_digest=_B,
            expected_target_generation_digest=_A,
            expected_validation_receipt_digest=_B,
            ontology_compatibility_receipt=_compatibility(),
            rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
        )

    assert await _generation_states(dsn=dsn, table=table) == {
        ("gen-a", "retired"),
        ("gen-b", "active"),
    }


@pytest.mark.integration
async def test_postgres_generation_rollback_rejects_validation_receipt_mismatch(
    catalog_generation_store: tuple[PgvectorCatalogSemanticIndex, str, str],
) -> None:
    store, dsn, table = catalog_generation_store
    activated_at = datetime(2026, 8, 6, tzinfo=UTC)
    for metadata in (
        _catalog_generation("gen-a", state="retired", activated_at=activated_at),
        _catalog_generation("gen-b", state="active", activated_at=activated_at),
    ):
        await _seed_generation(dsn=dsn, table=table, metadata=metadata)

    with pytest.raises(ValueError, match="validation receipt mismatch"):
        await store.rollback_generation(
            "gen-a",
            expected_active_generation_id="gen-b",
            expected_active_generation_digest=_B,
            expected_target_generation_digest=_A,
            expected_validation_receipt_digest=_D,
            ontology_compatibility_receipt=_compatibility(),
            rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
        )

    assert await _generation_states(dsn=dsn, table=table) == {
        ("gen-a", "retired"),
        ("gen-b", "active"),
    }


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
