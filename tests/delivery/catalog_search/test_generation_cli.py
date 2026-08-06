from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fdai.delivery.catalog_search import generation_cli
from fdai.delivery.operator_api.production.catalog_search import ProductionCatalogSearch
from fdai.shared.providers.catalog_search import CatalogGenerationMetadata

_DIGEST = "sha256:" + "a" * 64


def _metadata() -> CatalogGenerationMetadata:
    return CatalogGenerationMetadata(
        generation_id="catalog-search:active:test",
        generation_digest=_DIGEST,
        corpus="active",
        catalog_digest=_DIGEST,
        semantic_schema_digest=_DIGEST,
        ontology_release_digest=_DIGEST,
        embedding_space_id="catalog-search-384",
        embedding_model_version="embedding:test",
        embedding_dimension=384,
        state="active",
        validation_receipt_digest=_DIGEST,
        activated_at=datetime(2026, 8, 6, tzinfo=UTC),
    )


def test_main_publishes_generation_and_closes_provider(monkeypatch, capsys) -> None:
    index = AsyncMock()
    close = AsyncMock()
    publish = AsyncMock(return_value=_metadata())
    monkeypatch.setattr(
        generation_cli,
        "build_production_catalog_search",
        lambda **_kwargs: ProductionCatalogSearch(index=index, shutdown_callbacks=(close,)),
    )
    monkeypatch.setattr(generation_cli, "publish_shipped_catalog_generation", publish)
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql+psycopg://example.invalid/fdai")

    result = generation_cli.main(
        [
            "--validation-receipt-digest",
            _DIGEST,
            "--embedding-space-id",
            "catalog-search-384",
            "--embedding-model-version",
            "embedding:test",
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out)["generation_id"] == "catalog-search:active:test"
    assert publish.await_count == 1
    close.assert_awaited_once_with()


def test_main_fails_closed_when_catalog_index_is_unavailable(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        generation_cli,
        "build_production_catalog_search",
        lambda **_kwargs: ProductionCatalogSearch(index=None),
    )
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://example.invalid/fdai")

    result = generation_cli.main(
        [
            "--validation-receipt-digest",
            _DIGEST,
            "--embedding-space-id",
            "catalog-search-384",
            "--embedding-model-version",
            "embedding:test",
        ]
    )

    assert result == 4
    assert "catalog semantic index is unavailable" in capsys.readouterr().err


def test_main_rejects_missing_database_url(monkeypatch, capsys) -> None:
    monkeypatch.delenv("FDAI_DATABASE_URL", raising=False)

    result = generation_cli.main(
        [
            "--validation-receipt-digest",
            _DIGEST,
            "--embedding-space-id",
            "catalog-search-384",
            "--embedding-model-version",
            "embedding:test",
        ]
    )

    assert result == 4
    assert "FDAI_DATABASE_URL is required" in capsys.readouterr().err
