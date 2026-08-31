"""Time-consistent operating context for governed decisions."""

from .console_projection import SecuredContextResult, project_context_snapshot
from .evidence_bundle import (
    bind_citation,
    bind_evidence_item_source,
    build_operational_evidence_bundle,
    operational_state_scope_digest,
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
from .evidence_read import (
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadResult,
    OperationalEvidenceReadService,
    OperationalEvidenceSource,
    project_operational_evidence_read_result,
)
from .materializer import OperationalContextMaterializer
from .models import (
    OperationalContextEvidenceLink,
    OperationalContextEvidencePath,
    OperationalContextSnapshot,
    SourceFreshness,
)
from .operating_scope import (
    UNMAPPED_SERVICE_REF,
    OperatingScopeCoverage,
    ResourceScopeCoverage,
    project_operating_scope,
)
from .principal_context import (
    AuthenticatedPrincipalContext,
    OperationalEvidencePrincipalContextProvider,
)
from .projector import OperatingModelProjectionResult, OperatingModelProjector

__all__ = [
    "UNMAPPED_SERVICE_REF",
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
    "AuthenticatedPrincipalContext",
    "OperationalEvidenceBundle",
    "OperationalEvidenceMaterial",
    "OperationalEvidenceReadRequest",
    "OperationalEvidenceReadResult",
    "OperationalEvidenceReadService",
    "OperationalEvidenceSource",
    "OperationalEvidencePrincipalContextProvider",
    "OperatingModelProjectionResult",
    "OperatingModelProjector",
    "OperatingScopeCoverage",
    "ResourceScopeCoverage",
    "SourceFreshness",
    "StateEvidenceItem",
    "VerifiedEvidenceSourceReceipt",
    "bind_citation",
    "bind_evidence_item_source",
    "build_operational_evidence_bundle",
    "operational_state_scope_digest",
    "project_operating_scope",
    "project_operational_evidence_read_result",
    "render_untrusted_document_evidence",
]
