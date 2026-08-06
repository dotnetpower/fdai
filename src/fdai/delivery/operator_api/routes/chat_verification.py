"""Compatibility facade for the owned conversation verification package.

The capability catalog still names this source path. Runtime and test consumers
must import the application package directly; no verification implementation is
owned by the route namespace.
"""

from fdai.delivery.operator_api.application.conversation.verification import (
    AnswerVerification,
    VerificationStatus,
    verify_answer,
)

__all__ = [
    "AnswerVerification",
    "VerificationStatus",
    "verify_answer",
]
