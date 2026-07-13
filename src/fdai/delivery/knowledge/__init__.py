"""Knowledge Base delivery adapters (file ingestion loaders).

The persistent :class:`~fdai.delivery.pgvector.knowledge.PgvectorKnowledgeSource`
store lives under ``delivery/pgvector``; this package holds the ingestion-side
file loaders that turn local documents into
:class:`~fdai.shared.providers.knowledge.KnowledgeDocument` records.
"""

from __future__ import annotations

from fdai.delivery.knowledge.loader import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TEXT_SUFFIXES,
    documents_from_files,
    load_knowledge_documents,
)

__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TEXT_SUFFIXES",
    "documents_from_files",
    "load_knowledge_documents",
]
