"""Authority seam for dormant Rule revision promotion candidates."""

from __future__ import annotations

from typing import Protocol

from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_slots import (
    RuleDualRevisionSlotV2,
    RuleRevisionPromotionApprovalV2,
)


class RuleRevisionPromotionAuthorizer(Protocol):
    """Verify approval profile, principals, quorum, and revision evidence."""

    async def authorize(
        self,
        approval: RuleRevisionPromotionApprovalV2,
        *,
        slot: RuleDualRevisionSlotV2,
        target_revision: RuleRevisionIdentityRef,
    ) -> bool: ...


__all__ = ["RuleRevisionPromotionAuthorizer"]
