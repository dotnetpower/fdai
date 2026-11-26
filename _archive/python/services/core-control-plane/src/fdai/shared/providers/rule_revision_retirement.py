"""Authority seam for Rule revision retirement."""

from __future__ import annotations

from typing import Protocol

from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_retention import (
    RuleRevisionRetirementApprovalV2,
    RuleRevisionRetirementProposalV2,
)


class RuleRevisionRetirementAuthorizer(Protocol):
    """Verify the active approval profile and exact zero-reference retirement."""

    async def authorize_retirement(
        self,
        approval: RuleRevisionRetirementApprovalV2,
        *,
        proposal: RuleRevisionRetirementProposalV2,
    ) -> bool: ...


class RuleRevisionRegistryReader(Protocol):
    """Report whether the reviewed retained closure exists for one revision."""

    def has_retained_closure(self, revision: RuleRevisionIdentityRef) -> bool: ...


__all__ = ["RuleRevisionRegistryReader", "RuleRevisionRetirementAuthorizer"]
