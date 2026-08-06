"""Operator API application-service boundary.

Responsibility:
Host process-local typed use cases between transport adapters and delivery
workflows.

Boundary:
Accept validated typed inputs and return typed results without importing HTTP
framework objects or bypassing owned workflow boundaries.

Authority and state:
No approval, execution, promotion, or provider-scope authority. State remains
in injected providers and request-local records.

Dependencies:
Delivery contracts and typed callbacks supplied by composition.

Deployment:
Runs in-process within the Operator API; it introduces no network service.
"""

from fdai.delivery.operator_api.application.conversation_turn import (
    ConversationTurnApplicationService,
    ConversationTurnExecution,
    ConversationTurnInput,
    ConversationTurnResult,
    ConversationTurnTerminalStatus,
    ConversationTurnVerification,
)

__all__ = [
    "ConversationTurnApplicationService",
    "ConversationTurnExecution",
    "ConversationTurnInput",
    "ConversationTurnResult",
    "ConversationTurnTerminalStatus",
    "ConversationTurnVerification",
]
