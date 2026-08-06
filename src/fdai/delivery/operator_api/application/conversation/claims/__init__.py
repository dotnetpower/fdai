"""Deterministic verification of answer claims against bounded evidence.

Responsibility:
Expose atomic claim contracts and deterministic screen-evidence verification.

Boundary:
Accept a narrator answer and validated view-context mapping; HTTP status, SSE
frames, authentication, and terminal response rendering remain route-owned.

Authority and state:
Read-only and request-local. This package cannot approve, execute, promote, or
persist claims and receives no executor identity.

Dependencies:
Process-local claim extraction, evidence collection, matching, and manifest
helpers supplied by the Operator application layer.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from fdai.delivery.operator_api.application.conversation.claims.models import (
    AtomicClaim,
    EvidenceEntry,
    EvidenceManifest,
    ScreenClaimResult,
)
from fdai.delivery.operator_api.application.conversation.claims.verifier import (
    verify_screen_claims,
)

__all__ = [
    "AtomicClaim",
    "EvidenceEntry",
    "EvidenceManifest",
    "ScreenClaimResult",
    "verify_screen_claims",
]
