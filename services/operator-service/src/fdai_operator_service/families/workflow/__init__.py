"""Public facade for the independent Operator workflow route family.

Responsibility:
Expose workflow read contracts, proposal contracts, metadata, and route factory.

Boundary:
Render workflow projections and publish typed operator proposals.

Authority and state:
Hold no execution authority and mutate no workflow state in process.

Dependencies:
Use injected workflow read stores, authorizers, and proposal writers.

Deployment:
Run as a route family within the independently deployed Operator Service.
"""

from fdai_operator_service.families.workflow.contracts import (
    ProjectionProvenance,
    WorkflowOperation,
    WorkflowPrincipalAuthorizer,
    WorkflowProposal,
    WorkflowProposalReceipt,
    WorkflowProposalWriter,
    WorkflowReadRequest,
    WorkflowReadResult,
    WorkflowReadStore,
)
from fdai_operator_service.families.workflow.manifest import (
    WORKFLOW_FAMILY_ROUTE_MANIFEST,
    WorkflowRouteSpec,
)
from fdai_operator_service.families.workflow.routes import build_workflow_family_routes

__all__ = [
    "ProjectionProvenance",
    "WORKFLOW_FAMILY_ROUTE_MANIFEST",
    "WorkflowOperation",
    "WorkflowPrincipalAuthorizer",
    "WorkflowProposal",
    "WorkflowProposalReceipt",
    "WorkflowProposalWriter",
    "WorkflowReadRequest",
    "WorkflowReadResult",
    "WorkflowReadStore",
    "WorkflowRouteSpec",
    "build_workflow_family_routes",
]
