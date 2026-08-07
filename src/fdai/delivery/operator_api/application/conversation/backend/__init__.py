"""Request-local chat backend contracts and routing coordination.

Responsibility:
Expose the provider-neutral chat backend seam and request-local routing policy.

Boundary:
Accept validated conversation inputs and return JSON-safe backend results; HTTP,
SSE, authentication, provider credentials, and provider transport stay outside.

Authority and state:
Read-only and request-local. This package cannot approve, execute, promote, or
persist conversation state and receives no executor identity.

Dependencies:
Provider-neutral application contracts and bounded in-process routing helpers.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from fdai.delivery.operator_api.application.conversation.backend.contracts import (
    ChatBackend,
    ChatBackendMetadata,
    ChatBackendUnavailableError,
    ChatContentPolicyError,
    ContentPolicyStage,
    DisabledChatBackend,
)
from fdai.delivery.operator_api.application.conversation.backend.metadata import describe_backend
from fdai.delivery.operator_api.application.conversation.backend.policy import (
    reject_direct_override,
)
from fdai.delivery.operator_api.application.conversation.backend.router import (
    LatencyRoutedChatBackend,
)

__all__ = [
    "ChatBackend",
    "ChatBackendMetadata",
    "ChatBackendUnavailableError",
    "ChatContentPolicyError",
    "ContentPolicyStage",
    "DisabledChatBackend",
    "LatencyRoutedChatBackend",
    "describe_backend",
    "reject_direct_override",
]
