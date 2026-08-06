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
from .ontology_function import (
    build_catalog_query_function_registry,
    catalog_query_function_type,
    project_catalog_retrieval_receipt,
)
from .postgres import PgvectorCatalogSemanticIndex, PgvectorCatalogSemanticIndexConfig

__all__ = [
    "InMemoryCatalogSemanticIndex",
    "build_catalog_query_function_registry",
    "catalog_query_function_type",
    "PgvectorCatalogSemanticIndex",
    "PgvectorCatalogSemanticIndexConfig",
    "ShippedCatalogReferenceSources",
    "ShippedCatalogSearchSources",
    "index_shipped_catalog",
    "load_shipped_catalog_reference_sources",
    "load_shipped_catalog_search_documents",
    "load_shipped_catalog_search_sources",
    "publish_shipped_catalog_generation",
    "project_catalog_retrieval_receipt",
]
