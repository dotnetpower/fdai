"""Provider contracts for control-plane recovery approval verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RecoveryApprovalEvidence:
    """Bound fields an approval provider verifies before a recovery transition."""

    approval_ref: str
    actor_ref: str
    plan_id: str
    plan_revision: int
    target_state: str


@runtime_checkable
class RecoveryApprovalVerifier(Protocol):
    """Verify an authenticated approval bound to one recovery transition."""

    async def verify(self, evidence: RecoveryApprovalEvidence) -> bool:
        """Return true only when the approval is authentic and action-bound."""
        ...


__all__ = ["RecoveryApprovalEvidence", "RecoveryApprovalVerifier"]
