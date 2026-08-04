"""Catalog semantic-search delivery adapters."""

from .in_memory import InMemoryCatalogSemanticIndex
from .indexer import (
    ShippedCatalogSearchSources,
    index_shipped_catalog,
    load_shipped_catalog_search_documents,
    load_shipped_catalog_search_sources,
)
from .postgres import PgvectorCatalogSemanticIndex, PgvectorCatalogSemanticIndexConfig

__all__ = [
    "InMemoryCatalogSemanticIndex",
    "PgvectorCatalogSemanticIndex",
    "PgvectorCatalogSemanticIndexConfig",
    "ShippedCatalogSearchSources",
    "index_shipped_catalog",
    "load_shipped_catalog_search_documents",
    "load_shipped_catalog_search_sources",
]
