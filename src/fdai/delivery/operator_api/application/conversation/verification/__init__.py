"""Deterministic terminal answer verification for Operator conversations.

Responsibility:
Own request-local answer verification and canonical terminal answer results.

Boundary:
Accept validated conversation evidence and plain typed values; HTTP status,
JSON envelopes, SSE sequencing, authentication, and cancellation stay route-owned.

Authority and state:
Read-only and request-local. This package cannot approve, execute, promote, or
persist conversation state and receives no executor identity.

Dependencies:
Conversation claim verification plus bounded evidence and presentation helpers
supplied by the Operator API delivery layer.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from fdai.delivery.operator_api.application.conversation.verification.models import (
    VerificationStatus,
)
from fdai.delivery.operator_api.application.conversation.verification.verifier import (
    AnswerVerification,
    verify_answer,
)

__all__ = [
    "AnswerVerification",
    "VerificationStatus",
    "verify_answer",
]
