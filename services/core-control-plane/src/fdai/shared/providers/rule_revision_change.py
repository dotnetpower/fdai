"""Authority seam for one explicit Rule revision change."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from fdai_service_contracts.rule_activation_revision_change import (
    RuleRevisionChangeApprovalV2,
    RuleRevisionChangeProposalV2,
)


class RuleRevisionChangeAuthorizer(Protocol):
    """Verify the active approval profile and exact reviewed revision proposal."""

    async def authorize_revision_change(
        self,
        approval: RuleRevisionChangeApprovalV2,
        *,
        proposal: RuleRevisionChangeProposalV2,
    ) -> bool: ...


class RuleRollbackEligibilityVerifier(Protocol):
    """Verify one retained rollback closure and return its authority deadline."""

    async def rollback_eligibility_expires_at(
        self,
        proposal: RuleRevisionChangeProposalV2,
    ) -> datetime | None: ...


__all__ = ["RuleRevisionChangeAuthorizer", "RuleRollbackEligibilityVerifier"]
