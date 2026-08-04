from __future__ import annotations

import pytest

from fdai.delivery.catalog_search import PgvectorCatalogSemanticIndex
from fdai.delivery.operator_api.production.catalog_search import (
    build_production_catalog_search,
)
from fdai.delivery.operator_api.production.config import ProdOperatorApiConfigError


def test_production_search_is_unavailable_when_embedding_capability_is_absent() -> None:
    result = build_production_catalog_search(env={}, dsn="postgresql://example")

    assert result.index is None
    assert result.shutdown_callbacks == ()


def test_production_search_can_be_explicitly_disabled() -> None:
    result = build_production_catalog_search(
        env={
            "FDAI_CATALOG_SEARCH_ENABLED": "0",
            "FDAI_EMBEDDING_ENDPOINT": "https://example.com",
        },
        dsn="postgresql://example",
    )

    assert result.index is None


def test_production_search_rejects_partial_embedding_configuration() -> None:
    with pytest.raises(ProdOperatorApiConfigError, match="configured together"):
        build_production_catalog_search(
            env={"FDAI_EMBEDDING_ENDPOINT": "https://example.com"},
            dsn="postgresql://example",
        )


def test_production_search_builds_pgvector_adapter_when_available() -> None:
    result = build_production_catalog_search(
        env={
            "FDAI_EMBEDDING_ENDPOINT": "https://example.com",
            "FDAI_EMBEDDING_DEPLOYMENT": "embedding-small",
            "FDAI_EMBEDDING_DIM": "384",
            "IDENTITY_ENDPOINT": "http://127.0.0.1/identity",
            "IDENTITY_HEADER": "test-header",
        },
        dsn="postgresql://example",
    )

    assert isinstance(result.index, PgvectorCatalogSemanticIndex)
    assert len(result.shutdown_callbacks) == 1
