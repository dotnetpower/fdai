from __future__ import annotations

from datetime import UTC, datetime

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
