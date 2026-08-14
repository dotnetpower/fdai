"""Service-local HTTP family for bounded operational reads and proposals.

Responsibility:
Expose operational projections, replay reads, and typed proposal routes.

Boundary:
Read authoritative projections and submit requests through injected ports.

Authority and state:
Perform no direct effects and own no cross-service mutable state.

Dependencies:
Use projection readers, proposal writers, replay readers, and webhook verifiers.

Deployment:
Run as a route family within the independently deployed Operator Service.
"""

from fdai_operator_service.families.operations.contracts import (
    DurableReplayReader,
    EventProposal,
    EventProposalWriter,
    ProjectionQuery,
    ProjectionReader,
    ProjectionUnavailableError,
    ProposalConflictError,
    ProposalReceipt,
    ReplayBatch,
    ReplayEvent,
    ReplayQuery,
    ReportPdfEncoder,
    ReportPdfEncodingError,
    WebhookVerifier,
)
from fdai_operator_service.families.operations.factory import PanelRoute, build_operations_routes
from fdai_operator_service.families.operations.manifest import (
    OPERATIONS_ROUTE_MANIFEST,
    OperationRoute,
)

__all__ = [
    "OPERATIONS_ROUTE_MANIFEST",
    "DurableReplayReader",
    "EventProposal",
    "EventProposalWriter",
    "OperationRoute",
    "PanelRoute",
    "ProjectionQuery",
    "ProjectionReader",
    "ProjectionUnavailableError",
    "ReportPdfEncoder",
    "ReportPdfEncodingError",
    "ProposalConflictError",
    "ProposalReceipt",
    "ReplayBatch",
    "ReplayEvent",
    "ReplayQuery",
    "WebhookVerifier",
    "build_operations_routes",
]
