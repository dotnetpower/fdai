"""Never-raising MSCP ceiling over the authoritative FDAI risk decision."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fdai.core.mscp_profile.profile import DEFAULT_PROFILE
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision


class MscpAuthorityCeiling(StrEnum):
    PRESERVE = "preserve"
    HUMAN_APPROVAL = "human_approval"
    HOLD = "hold"
    DENY = "deny"


class MscpAuthorityReason(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    CHECKS_PASSED = "checks_passed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    STRUCTURAL_HOLD = "structural_hold"
    POLICY_DENY = "policy_deny"


_CEILING_LEVEL = {
    MscpAuthorityCeiling.PRESERVE: AxisLevel.ENFORCE_AUTO,
    MscpAuthorityCeiling.HUMAN_APPROVAL: AxisLevel.ENFORCE_HIL,
    MscpAuthorityCeiling.HOLD: AxisLevel.SHADOW_ONLY,
    MscpAuthorityCeiling.DENY: AxisLevel.DENY,
}

_LEVEL_TO_DECISION = {
    AxisLevel.ENFORCE_AUTO: "auto",
    AxisLevel.ENFORCE_HIL: "hil",
    AxisLevel.SHADOW_ONLY: "shadow",
    AxisLevel.DENY: "deny",
}


@dataclass(frozen=True, slots=True)
class MscpAuthorityDecision:
    """Immutable combined decision that preserves the original risk evidence."""

    existing: UnifiedRiskDecision
    ceiling: MscpAuthorityCeiling
    reason: MscpAuthorityReason
    level: AxisLevel

    @property
    def decision(self) -> str:
        return _LEVEL_TO_DECISION[self.level]

    @property
    def lowered(self) -> bool:
        return self.level < self.existing.level

    def as_audit_dict(self) -> dict[str, Any]:
        return {
            "safety_profile": DEFAULT_PROFILE.profile_id,
            "existing_decision": self.existing.decision,
            "ceiling": self.ceiling.value,
            "reason": self.reason.value,
            "decision": self.decision,
            "lowered": self.lowered,
        }


def combine_mscp_authority(
    existing: UnifiedRiskDecision,
    *,
    ceiling: MscpAuthorityCeiling,
    reason: MscpAuthorityReason,
) -> MscpAuthorityDecision:
    """Apply one profile ceiling without bypassing or raising FDAI authority."""

    level = min(existing.level, _CEILING_LEVEL[ceiling])
    return MscpAuthorityDecision(
        existing=existing,
        ceiling=ceiling,
        reason=reason,
        level=level,
    )


__all__ = [
    "MscpAuthorityCeiling",
    "MscpAuthorityDecision",
    "MscpAuthorityReason",
    "combine_mscp_authority",
]
