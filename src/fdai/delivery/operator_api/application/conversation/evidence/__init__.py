"""Read-only evidence coordination for Operator conversations.

Responsibility:
Expose request-local evidence provenance and coordination helpers.

Boundary:
Accept validated conversation values and evidence mappings; HTTP status, JSON
envelopes, SSE sequencing, authentication, cancellation, and history remain
route-owned.

Authority and state:
Read-only and request-local. This package cannot approve, execute, promote, or
persist conversation state and receives no executor identity.

Dependencies:
Process-local evidence resolvers and bounded Operator API read helpers.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from fdai.delivery.operator_api.application.conversation.evidence.branches import (
    BranchProgressObserver,
    EvidenceBranchKind,
    EvidenceBranchResult,
    EvidenceBranchSpec,
    EvidenceBranchStatus,
    resolve_evidence_branches,
)
from fdai.delivery.operator_api.application.conversation.evidence.enrichment import (
    AgentChatDelegate,
    ChatBehaviorEvidenceResolver,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    PlannedChatToolResolver,
)
from fdai.delivery.operator_api.application.conversation.evidence.operational import (
    OperationalEvidenceResolver,
    needs_operational_evidence,
)
from fdai.delivery.operator_api.application.conversation.evidence.pipeline import (
    has_bound_incident_analysis_context,
    has_screen_incident_analysis_context,
    resolve_parallel_chat_evidence,
)

__all__ = [
    "AgentChatDelegate",
    "BranchProgressObserver",
    "ChatBehaviorEvidenceResolver",
    "ChatToolResolver",
    "ChatWebSearchEvidenceResolver",
    "EvidenceBranchKind",
    "EvidenceBranchResult",
    "EvidenceBranchSpec",
    "EvidenceBranchStatus",
    "OperationalEvidenceResolver",
    "OperationalEvidenceResolverProtocol",
    "PlannedChatToolResolver",
    "has_bound_incident_analysis_context",
    "has_screen_incident_analysis_context",
    "needs_operational_evidence",
    "resolve_evidence_branches",
    "resolve_parallel_chat_evidence",
]
