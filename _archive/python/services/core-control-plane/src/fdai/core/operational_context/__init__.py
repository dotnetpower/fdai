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
from .operating_intent_admission import (
    MAX_ADMITTED_OBJECT_IDS,
    MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS,
    OPERATING_INTENT_SOURCE_ADMISSION_KEY,
    OperatingIntentAdmission,
    OperatingIntentAdmissionExpectation,
    OperatingIntentAdmissionStatus,
    StateStoreOperatingIntentAdmissionReader,
    evaluate_operating_intent_admission,
)
from .operating_intent_source import (
    OperatingIntentSourceBinding,
    OperatingIntentSourceError,
    validate_operating_intent_source_document,
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
    "MAX_ADMITTED_OBJECT_IDS",
    "MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS",
    "OPERATING_INTENT_SOURCE_ADMISSION_KEY",
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
    "OperatingIntentAdmission",
    "OperatingIntentAdmissionExpectation",
    "OperatingIntentAdmissionStatus",
    "OperatingIntentSourceBinding",
    "OperatingIntentSourceError",
    "OperatingModelProjectionResult",
    "OperatingModelProjector",
    "OperatingScopeCoverage",
    "ResourceScopeCoverage",
    "SourceFreshness",
    "StateEvidenceItem",
    "StateStoreOperatingIntentAdmissionReader",
    "VerifiedEvidenceSourceReceipt",
    "bind_citation",
    "bind_evidence_item_source",
    "build_operational_evidence_bundle",
    "evaluate_operating_intent_admission",
    "operational_state_scope_digest",
    "project_operating_scope",
    "project_operational_evidence_read_result",
    "render_untrusted_document_evidence",
    "validate_operating_intent_source_document",
]
