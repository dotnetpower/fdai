"""Operator API application services.

Responsibility: host process-local typed use-case boundaries between transport
adapters and existing delivery workflows. Authority: none; application
services cannot approve, execute, promote, select provider scope, or receive an
executor identity. State remains in injected providers and request-local
records. Dependencies are delivery contracts and typed callbacks. Deployment
role: in-process within the Operator API; no network service is introduced.
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
