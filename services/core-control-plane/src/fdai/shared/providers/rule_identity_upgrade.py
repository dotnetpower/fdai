"""Authority seam for the Rule activation identity cutover."""

from __future__ import annotations

from typing import Protocol

from fdai_service_contracts.rule_activation_upgrade import (
    RuleIdentityUpgradeApprovalV2,
    RuleIdentityUpgradeProposalV2,
    RuleReviewedPolicyBaselineV2,
)


class RuleIdentityUpgradeAuthorizer(Protocol):
    """Verify the active approval profile and exact reviewed upgrade evidence."""

    async def authorize_identity_upgrade(
        self,
        approval: RuleIdentityUpgradeApprovalV2,
        *,
        proposal: RuleIdentityUpgradeProposalV2,
        baseline: RuleReviewedPolicyBaselineV2,
    ) -> bool: ...


__all__ = ["RuleIdentityUpgradeAuthorizer"]
