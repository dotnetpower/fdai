"""Time-consistent operating context for governed decisions."""

from .evidence_bundle import build_operational_evidence_bundle
from .evidence_bundle_models import (
    CatalogEvidenceItem,
    CitationManifestEntry,
    ClaimRecord,
    DocumentEvidenceExcerpt,
    EvidenceConflict,
    EvidenceLane,
    EvidenceSourceMetadata,
    OntologyEvidenceItem,
    OperationalEvidenceBundle,
    StateEvidenceItem,
)
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
    "CitationManifestEntry",
    "ClaimRecord",
    "DocumentEvidenceExcerpt",
    "EvidenceConflict",
    "EvidenceLane",
    "EvidenceSourceMetadata",
    "OntologyEvidenceItem",
    "OperationalContextMaterializer",
    "OperationalContextEvidenceLink",
    "OperationalContextEvidencePath",
    "OperationalContextSnapshot",
    "OperationalEvidenceBundle",
    "OperatingModelProjectionResult",
    "OperatingModelProjector",
    "SourceFreshness",
    "StateEvidenceItem",
    "build_operational_evidence_bundle",
]
