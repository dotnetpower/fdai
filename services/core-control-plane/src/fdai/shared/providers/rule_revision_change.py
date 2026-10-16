"""Authority seam for one explicit Rule revision change."""

from __future__ import annotations

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


__all__ = ["RuleRevisionChangeAuthorizer"]
