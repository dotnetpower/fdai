"""Conversation persistence boundary.

Responsibility:
Expose principal-scoped transcript and image persistence operations.

Boundary:
Accept authenticated principal and conversation identities from routes while
keeping HTTP, SSE, authentication, status mapping, and transport outside.

Authority and state:
May write conversation records, turns, policy receipts, and image lifecycle
rows through injected stores. It has no approval or managed-resource authority.

Dependencies:
Conversation store contracts, validated vision attachments, and the bounded
user-context ontology projector.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from .history import (
    append_assistant_turn,
    append_content_policy_receipt,
    append_operator_turn,
    replay_metadata,
)
from .image_history import (
    image_turn_metadata,
    persist_conversation_images,
    persist_operator_turn_with_images,
)

__all__ = [
    "append_assistant_turn",
    "append_content_policy_receipt",
    "append_operator_turn",
    "image_turn_metadata",
    "persist_conversation_images",
    "persist_operator_turn_with_images",
    "replay_metadata",
]
