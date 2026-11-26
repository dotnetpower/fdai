"""Read-only source admission required before Core can accept handover evidence."""

from __future__ import annotations

from typing import Literal, Protocol


class GoalEvidenceAdmission(Protocol):
    """Resolve current immutable document admission and ACL for the named human.

    An unbound reader makes acceptance unavailable. Goal state, a reference, or an existing
    approval is never a substitute for current source admission. Implementations receive no
    membership, catalog, or execution authority from this port.
    """

    async def verify_subject(self, *, subject_ref: str, assignment_case_id: str) -> bool:
        """Require the active assignment's provider-qualified human, even for all-exempt goals."""
        ...

    async def verify(
        self, *, subject_ref: str, evidence_ref: str, digest: str, reviewer_ref: str
    ) -> bool: ...


class GoalReviewerEligibility(Protocol):
    """Read current active-person roles and, for backups, exact agent/scope duty eligibility."""

    async def may_review(
        self,
        *,
        reviewer_ref: str,
        agent_name: str,
        scope_ref: str,
        role: Literal["owner", "backup"],
    ) -> bool: ...


__all__ = ["GoalEvidenceAdmission", "GoalReviewerEligibility"]
