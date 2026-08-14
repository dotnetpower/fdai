"""Time-consistent operating context for governed decisions."""

from .console_projection import SecuredContextResult, project_context_snapshot
from .evidence_bundle import (
    bind_citation,
    bind_evidence_item_source,
    build_operational_evidence_bundle,
)
from .evidence_bundle_models import (
    CatalogEvidenceItem,
    CitationBinding,
    CitationManifestEntry,
    ClaimRecord,
    DocumentEvidenceExcerpt,
    EvidenceConflict,
    EvidenceLane,
    OntologyEvidenceItem,
    OperationalEvidenceBundle,
    StateEvidenceItem,
)
from .evidence_bundle_prompt import render_untrusted_document_evidence
from .evidence_bundle_sources import EvidenceTemporalScope, VerifiedEvidenceSourceReceipt
from .materializer import OperationalContextMaterializer
from .models import (
    OperationalContextEvidenceLink,
    OperationalContextEvidencePath,
    OperationalContextSnapshot,
    SourceFreshness,
)
from .projector import OperatingModelProjectionResult, OperatingModelProjector

__all__ = [
    "CatalogEvidenceItem",
    "CitationBinding",
    "CitationManifestEntry",
    "ClaimRecord",
    "DocumentEvidenceExcerpt",
    "EvidenceConflict",
    "EvidenceLane",
    "EvidenceTemporalScope",
    "OntologyEvidenceItem",
    "OperationalContextMaterializer",
    "SecuredContextResult",
    "project_context_snapshot",
    "OperationalContextEvidenceLink",
    "OperationalContextEvidencePath",
    "OperationalContextSnapshot",
    "OperationalEvidenceBundle",
    "OperatingModelProjectionResult",
    "OperatingModelProjector",
    "SourceFreshness",
    "StateEvidenceItem",
    "VerifiedEvidenceSourceReceipt",
    "bind_citation",
    "bind_evidence_item_source",
    "build_operational_evidence_bundle",
    "render_untrusted_document_evidence",
]
