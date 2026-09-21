"""Compatibility facade for document processing adapters."""

from fdai_document_worker_service.adapters.processing_azure import (
    AzureDocumentIntelligenceOcr,
    AzureDocumentOcrConfig,
    AzureEmbeddingConfig,
    AzureEmbeddingModel,
    EmbeddingModel,
    UnavailableImageOcr,
)
from fdai_document_worker_service.adapters.processing_extraction import (
    BoundedDocumentExtractor,
    SignatureProtectionInspector,
)
from fdai_document_worker_service.adapters.processing_extraction_support import (
    _pdf_inspection as _pdf_inspection,
)
from fdai_document_worker_service.adapters.processing_extraction_support import (
    _read_bounded as _read_bounded,
)
from fdai_document_worker_service.adapters.processing_index import (
    PgvectorDocumentIndex,
)
from fdai_document_worker_service.adapters.processing_malware import (
    ClamAvMalwareScanner,
    ClamAvScannerConfig,
)

__all__ = [
    "AzureDocumentIntelligenceOcr",
    "AzureDocumentOcrConfig",
    "AzureEmbeddingConfig",
    "AzureEmbeddingModel",
    "BoundedDocumentExtractor",
    "ClamAvMalwareScanner",
    "ClamAvScannerConfig",
    "EmbeddingModel",
    "PgvectorDocumentIndex",
    "SignatureProtectionInspector",
    "UnavailableImageOcr",
]
