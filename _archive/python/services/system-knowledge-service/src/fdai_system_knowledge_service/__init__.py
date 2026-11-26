"""Independent FDAI system-knowledge service."""

from fdai_system_knowledge_service.application import create_app
from fdai_system_knowledge_service.catalog import compile_reference_catalog, load_catalog
from fdai_system_knowledge_service.search import SystemKnowledgeIndex

__all__ = [
    "SystemKnowledgeIndex",
    "compile_reference_catalog",
    "create_app",
    "load_catalog",
]
