"""Content-free admission and promotion decisions for prompt optimizations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fdai_service_contracts.ontology_query import content_digest

_DIGEST_PREFIX = "sha256:"
MIN_REVIEWED_PROMPT_COHORT_CASES = 100


class PromptPromotionAction(StrEnum):
    """Allowed terminal actions for one exact profile comparison."""

    PROMOTE = "promote"
    RETAIN = "retain"
    ROLLBACK = "rollback"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class PromptCohortEvidence:
    """Content-free measurements for one exact profile arm."""

    profile_id: str
    profile_digest: str
    model_binding_digest: str
    cohort_digest: str
    sample_count: int
    quality_passed: int
    safety_passed: int
    prompt_tokens: int
    completion_tokens: int
    planning_shapes_digest: str

    def __post_init__(self) -> None:
        for label, value in (
            ("profile_digest", self.profile_digest),
            ("model_binding_digest", self.model_binding_digest),
            ("cohort_digest", self.cohort_digest),
            ("planning_shapes_digest", self.planning_shapes_digest),
        ):
            if not _valid_digest(value):
                raise ValueError(f"{label} MUST be one sha256 digest")
        if not self.profile_id or len(self.profile_id) > 128:
            raise ValueError("profile_id MUST be non-empty and bounded")
        for label, value in (
            ("sample_count", self.sample_count),
            ("quality_passed", self.quality_passed),
            ("safety_passed", self.safety_passed),
            ("prompt_tokens", self.prompt_tokens),
            ("completion_tokens", self.completion_tokens),
        ):
            if type(value) is not int:
                raise TypeError(f"{label} MUST be one integer")
        if not 0 <= self.quality_passed <= self.sample_count:
            raise ValueError("quality_passed MUST be within the cohort")
        if not 0 <= self.safety_passed <= self.sample_count:
            raise ValueError("safety_passed MUST be within the cohort")
        if min(self.prompt_tokens, self.completion_tokens) < 0:
            raise ValueError("cohort token counts MUST NOT be negative")

    @property
    def digest(self) -> str:
        return content_digest(
            {
                "profile_id": self.profile_id,
                "profile_digest": self.profile_digest,
                "model_binding_digest": self.model_binding_digest,
                "cohort_digest": self.cohort_digest,
                "sample_count": self.sample_count,
                "quality_passed": self.quality_passed,
                "safety_passed": self.safety_passed,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "planning_shapes_digest": self.planning_shapes_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class PromptPromotionDecision:
    """Replayable no-authority decision over baseline and treatment evidence."""

    baseline_evidence_digest: str
    treatment_evidence_digest: str
    action: PromptPromotionAction
    reason_codes: tuple[str, ...]
    decided_at: datetime
    expires_at: datetime
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.action, PromptPromotionAction):
            raise TypeError("promotion action MUST be one PromptPromotionAction")
        if type(self.execution_authority) is not bool:
            raise TypeError("execution_authority MUST be one boolean")
        if not _valid_digest(self.baseline_evidence_digest) or not _valid_digest(
            self.treatment_evidence_digest
        ):
            raise ValueError("promotion evidence digests MUST be sha256 values")
        if self.decided_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("promotion decision timestamps MUST be timezone-aware")
        if self.expires_at <= self.decided_at:
            raise ValueError("promotion decision expiry MUST follow its decision time")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("promotion reason codes MUST be sorted and unique")
        if self.execution_authority:
            raise ValueError("prompt promotion evidence cannot grant execution authority")

    @property
    def digest(self) -> str:
        return content_digest(
            {
                "baseline_evidence_digest": self.baseline_evidence_digest,
                "treatment_evidence_digest": self.treatment_evidence_digest,
                "action": self.action.value,
                "reason_codes": self.reason_codes,
                "decided_at": self.decided_at.astimezone(UTC).isoformat(),
                "expires_at": self.expires_at.astimezone(UTC).isoformat(),
                "execution_authority": False,
            }
        )


def evaluate_prompt_promotion(
    *,
    baseline: PromptCohortEvidence,
    treatment: PromptCohortEvidence,
    decided_at: datetime,
    expires_at: datetime,
) -> PromptPromotionDecision:
    """Promote only exact, reviewed, safe, non-regressing, token-saving evidence."""

    reasons: set[str] = set()
    if baseline.model_binding_digest != treatment.model_binding_digest:
        reasons.add("model_binding_mismatch")
    if baseline.cohort_digest != treatment.cohort_digest:
        reasons.add("cohort_mismatch")
    if baseline.sample_count != treatment.sample_count:
        reasons.add("sample_count_mismatch")
    if min(baseline.sample_count, treatment.sample_count) < MIN_REVIEWED_PROMPT_COHORT_CASES:
        reasons.add("cohort_too_small")
    if treatment.safety_passed != treatment.sample_count:
        reasons.add("safety_regression")
    if treatment.quality_passed < baseline.quality_passed:
        reasons.add("quality_regression")
    if treatment.planning_shapes_digest != baseline.planning_shapes_digest:
        reasons.add("planning_shape_regression")
    if treatment.prompt_tokens >= baseline.prompt_tokens:
        reasons.add("no_prompt_token_reduction")
    action = (
        PromptPromotionAction.PROMOTE
        if not reasons
        else PromptPromotionAction.ROLLBACK
        if reasons & {"safety_regression", "quality_regression", "planning_shape_regression"}
        else PromptPromotionAction.HOLD
    )
    return PromptPromotionDecision(
        baseline_evidence_digest=baseline.digest,
        treatment_evidence_digest=treatment.digest,
        action=action,
        reason_codes=tuple(sorted(reasons)),
        decided_at=decided_at,
        expires_at=expires_at,
    )


def _valid_digest(value: str) -> bool:
    return (
        value.startswith(_DIGEST_PREFIX)
        and len(value) == len(_DIGEST_PREFIX) + 64
        and all(character in "0123456789abcdef" for character in value[len(_DIGEST_PREFIX) :])
    )


__all__ = [
    "MIN_REVIEWED_PROMPT_COHORT_CASES",
    "PromptCohortEvidence",
    "PromptPromotionAction",
    "PromptPromotionDecision",
    "evaluate_prompt_promotion",
]
