"""Concrete narrator provider adapters and startup composition.

Responsibility:
Construct and expose Azure and OpenAI-compatible conversation backends.

Boundary:
Implement the application chat backend contract; request authentication, JSON
and SSE delivery, conversation history, and routing policy remain outside.

Authority and state:
Performs read-only model calls and request metering. It cannot approve,
execute, promote, select managed-resource scope, or own durable state.

Dependencies:
Application backend contracts, Azure workload identity, HTTP transport, model
endpoint configuration, and injected metering providers.

Deployment:
Runs in-process within the Operator API and creates no network boundary beyond
the configured provider calls.
"""

from fdai.delivery.operator_api.adapters.conversation.azure import AzureAdChatBackend
from fdai.delivery.operator_api.adapters.conversation.factory import backend_from_env
from fdai.delivery.operator_api.adapters.conversation.openai import (
    OpenAiCompatibleChatBackend,
    OpenAiCompatibleChatBackendConfig,
)

__all__ = [
    "AzureAdChatBackend",
    "OpenAiCompatibleChatBackend",
    "OpenAiCompatibleChatBackendConfig",
    "backend_from_env",
]
