"""Public service-local API for the Operator conversation route family.

Responsibility:
Expose conversation contracts, route metadata, and the family factory.

Boundary:
Translate authenticated operator requests into read queries or typed proposals.

Authority and state:
Perform no managed-resource effects and retain no shared mutable workflow state.

Dependencies:
Use injected projection, authorization, event-stream, and outbox ports.

Deployment:
Run only inside the independently deployed Operator Service process.
"""

from fdai_operator_service.families.conversation.contracts import (
    ConversationAuthorizer,
    ConversationBoundaryError,
    ConversationEventStream,
    ConversationProjectionReader,
    ConversationProposal,
    ConversationProposalOutbox,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamReader,
    ConversationStreamRequest,
    ConversationUnavailableError,
    JsonObject,
    OutboxReceipt,
    PrincipalScope,
    StreamEvent,
)
from fdai_operator_service.families.conversation.factory import (
    ConversationFamilyDependencies,
    build_conversation_routes,
)
from fdai_operator_service.families.conversation.manifest import (
    CONVERSATION_ROUTE_MANIFEST,
    ConversationRouteSpec,
)

__all__ = [
    "CONVERSATION_ROUTE_MANIFEST",
    "ConversationAuthorizer",
    "ConversationBoundaryError",
    "ConversationEventStream",
    "ConversationFamilyDependencies",
    "ConversationProjectionReader",
    "ConversationProposal",
    "ConversationProposalOutbox",
    "ConversationQuery",
    "ConversationResponse",
    "ConversationRouteSpec",
    "ConversationStreamReader",
    "ConversationStreamRequest",
    "ConversationUnavailableError",
    "JsonObject",
    "OutboxReceipt",
    "PrincipalScope",
    "StreamEvent",
    "build_conversation_routes",
]
