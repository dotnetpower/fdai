from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock

import pytest
from fdai.delivery.catalog_search.postgres import (
    PostgresCatalogSemanticIndex,
    PostgresCatalogSemanticIndexConfig,
)
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    CatalogSemanticIndex,
    build_document_digest_manifest,
    catalog_generation_digest,
    catalog_search_document_digest,
)
from psycopg.conninfo import conninfo_to_dict


@pytest.mark.parametrize("interrupted", [False, True])
def test_isolated_catalog_harness_never_migrates_or_cleans_shared_tables(
    interrupted: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.delivery.catalog_search import test_postgres_integration as integration

    monkeypatch.setenv(
        "FDAI_ONTOLOGY_SNAPSHOT_TEST_DSN", "host=127.0.0.1 dbname=example user=example"
    )
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = (True,)
    monkeypatch.setattr(integration.psycopg, "connect", Mock(return_value=connection))
    monkeypatch.setattr(integration.uuid, "uuid4", lambda: Mock(hex="1" * 32))
    iterator = integration.isolated_local_catalog.__wrapped__(monkeypatch)
    next(iterator)
    assert (
        conninfo_to_dict(integration._dsn())["options"]
        == "-c search_path=test_catalog_" + "1" * 32 + ",public"
    )
    assert integration._upgrade() is None
    if interrupted:
        with pytest.raises(RuntimeError, match="example interruption"):
            iterator.throw(RuntimeError("example interruption"))
    else:
        with pytest.raises(StopIteration):
            next(iterator)
    statements = [
        call.args[0] if isinstance(call.args[0], str) else call.args[0].as_string()
        for call in connection.execute.call_args_list
    ]
    assert sum(statement.startswith("CREATE SCHEMA") for statement in statements) == 1
    assert sum(statement.startswith("CREATE TABLE") for statement in statements) == 2
    assert statements[-1] == 'DROP SCHEMA "test_catalog_' + "1" * 32 + '" CASCADE'
    assert not any(
        statement.startswith(("DELETE", "UPDATE", "DROP TABLE", "CREATE EXTENSION"))
        for statement in statements
    )


class _Embedder:
    async def embed(self, text: str) -> tuple[float, ...]:
        return (float(bool(text)),) * 384


def test_postgres_catalog_index_config_and_protocol() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresCatalogSemanticIndexConfig(dsn="")

    index = PostgresCatalogSemanticIndex(
        config=PostgresCatalogSemanticIndexConfig(dsn="postgresql://example.invalid/fdai"),
        embedder=_Embedder(),
    )

    assert isinstance(index, CatalogSemanticIndex)


async def test_postgres_catalog_index_rejects_metadata_dimension_before_io() -> None:
    documents = (
        CatalogSearchDocument(
            rule_id="rule-a",
            text="rule a",
            neighbor_ids=(),
        ),
    )
    manifest = build_document_digest_manifest(
        tuple(catalog_search_document_digest(item) for item in documents)
    )
    catalog_digest = "sha256:" + ("a" * 64)
    schema_digest = "sha256:" + ("b" * 64)
    release_digest = "sha256:" + ("c" * 64)
    generation_digest = catalog_generation_digest(
        corpus="active",
        catalog_digest=catalog_digest,
        semantic_schema_digest=schema_digest,
        ontology_release_digest=release_digest,
        embedding_space_id="test-v1",
        embedding_model_version="test-v1",
        embedding_dimension=1,
        document_digest_manifest=manifest,
    )
    metadata = CatalogGenerationMetadata(
        generation_id="generation-a",
        generation_digest=generation_digest,
        corpus="active",
        catalog_digest=catalog_digest,
        semantic_schema_digest=schema_digest,
        ontology_release_digest=release_digest,
        embedding_space_id="test-v1",
        embedding_model_version="test-v1",
        embedding_dimension=1,
        document_digest_manifest=manifest,
        validation_receipt_digest="sha256:" + ("d" * 64),
    )
    index = PostgresCatalogSemanticIndex(
        config=PostgresCatalogSemanticIndexConfig(dsn="postgresql://example.invalid/fdai"),
        embedder=_Embedder(),
    )

    with pytest.raises(ValueError, match="embedding dimension mismatch"):
        await index.stage_generation(metadata, documents)


@pytest.mark.parametrize(
    ("expected_id", "expected_digest"),
    (("generation-a", None), (None, "sha256:" + ("a" * 64))),
)
async def test_postgres_catalog_index_rejects_partial_active_identity_before_io(
    expected_id: str | None,
    expected_digest: str | None,
) -> None:
    index = PostgresCatalogSemanticIndex(
        config=PostgresCatalogSemanticIndexConfig(dsn="postgresql://example.invalid/fdai"),
        embedder=_Embedder(),
    )

    with pytest.raises(ValueError, match="supplied together"):
        await index.activate_generation(
            "generation-b",
            expected_generation_digest="sha256:" + ("b" * 64),
            expected_active_generation_id=expected_id,
            expected_active_generation_digest=expected_digest,
            activated_at=datetime(2026, 8, 13, tzinfo=UTC),
        )
