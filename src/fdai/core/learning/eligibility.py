"""Deterministic eligibility policy for off-path turn review."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.learning.models import (
    EligibilityDecision,
    EligibilityReason,
    PostTurnReviewInput,
)
from fdai.core.operator_memory.sanitizer import detect_injection_markers


@dataclass(frozen=True, slots=True)
class PostTurnEligibilityPolicyConfig:
    min_tool_receipts: int = 5
    repeated_procedure_threshold: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.min_tool_receipts <= 64:
            raise ValueError("min_tool_receipts MUST be in [1, 64]")
        if not 2 <= self.repeated_procedure_threshold <= 100:
            raise ValueError("repeated_procedure_threshold MUST be in [2, 100]")


class PostTurnEligibilityPolicy:
    """Admit only consented, safe turns with an observable learning signal."""

    def __init__(self, config: PostTurnEligibilityPolicyConfig | None = None) -> None:
        self._config = config or PostTurnEligibilityPolicyConfig()

    def evaluate(self, review_input: PostTurnReviewInput) -> EligibilityDecision:
        if not review_input.body_shared:
            return EligibilityDecision(False, (EligibilityReason.OPTED_OUT,))
        bodies = (
            review_input.operator_body or "",
            review_input.assistant_body or "",
            *review_input.explicit_corrections,
        )
        if any(detect_injection_markers(body) for body in bodies):
            return EligibilityDecision(False, (EligibilityReason.UNSAFE_CONTENT,))

        reasons: list[EligibilityReason] = []
        if len(review_input.tool_receipts) >= self._config.min_tool_receipts:
            reasons.append(EligibilityReason.ELIGIBLE_COMPLEX)
        if review_input.explicit_corrections:
            reasons.append(EligibilityReason.ELIGIBLE_CORRECTION)
        if review_input.failure_recovered:
            reasons.append(EligibilityReason.ELIGIBLE_RECOVERED_FAILURE)
        if (
            review_input.procedure_fingerprint is not None
            and review_input.repeated_procedure_count >= self._config.repeated_procedure_threshold
        ):
            reasons.append(EligibilityReason.ELIGIBLE_REPEATED_PROCEDURE)
        if not reasons:
            reasons.append(EligibilityReason.INELIGIBLE)
        return EligibilityDecision(reasons[0] is not EligibilityReason.INELIGIBLE, tuple(reasons))


__all__ = ["PostTurnEligibilityPolicy", "PostTurnEligibilityPolicyConfig"]
