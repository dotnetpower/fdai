"""Catalog semantic-search delivery adapters."""

from .in_memory import InMemoryCatalogSemanticIndex
from .indexer import (
    ShippedCatalogReferenceSources,
    ShippedCatalogSearchSources,
    index_shipped_catalog,
    load_shipped_catalog_reference_sources,
    load_shipped_catalog_search_documents,
    load_shipped_catalog_search_sources,
    publish_shipped_catalog_generation,
)
from .postgres import PgvectorCatalogSemanticIndex, PgvectorCatalogSemanticIndexConfig

__all__ = [
    "InMemoryCatalogSemanticIndex",
    "PgvectorCatalogSemanticIndex",
    "PgvectorCatalogSemanticIndexConfig",
    "ShippedCatalogReferenceSources",
    "ShippedCatalogSearchSources",
    "index_shipped_catalog",
    "load_shipped_catalog_reference_sources",
    "load_shipped_catalog_search_documents",
    "load_shipped_catalog_search_sources",
    "publish_shipped_catalog_generation",
]
