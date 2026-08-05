from __future__ import annotations

from fdai.delivery.operator_api.production.catalog_search import (
    build_production_catalog_search,
)


async def test_inventory_semantics_can_reuse_embedder_when_catalog_search_is_disabled() -> None:
    built = build_production_catalog_search(
        env={
            "FDAI_CATALOG_SEARCH_ENABLED": "0",
            "FDAI_INVENTORY_SEMANTIC_ENABLED": "1",
            "FDAI_EMBEDDING_ENDPOINT": "https://example.openai.azure.com",
            "FDAI_EMBEDDING_DEPLOYMENT": "embedding-example",
            "IDENTITY_ENDPOINT": "http://127.0.0.1:40342/metadata/identity/oauth2/token",
            "IDENTITY_HEADER": "synthetic-test-header",
        },
        dsn="postgresql://example.invalid/fdai",
    )

    try:
        assert built.index is None
        assert built.embedder is not None
    finally:
        for callback in built.shutdown_callbacks:
            await callback()


def test_both_semantic_features_can_be_disabled_without_embedding_config() -> None:
    built = build_production_catalog_search(
        env={
            "FDAI_CATALOG_SEARCH_ENABLED": "0",
            "FDAI_INVENTORY_SEMANTIC_ENABLED": "0",
        },
        dsn="postgresql://example.invalid/fdai",
    )

    assert built.index is None
    assert built.embedder is None
    assert built.shutdown_callbacks == ()
