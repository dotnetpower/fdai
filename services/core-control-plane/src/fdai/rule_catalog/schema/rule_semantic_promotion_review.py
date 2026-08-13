"""Deterministic review eligibility for validated Rule semantic surfaces."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from fdai.rule_catalog.schema.rule_semantic_evaluation import RetrievalEvaluationPolicy
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    SurfaceValidationReceipt,
    ValidationDecision,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,511}$")


class PromotionReviewDecision(StrEnum):
    """Review eligibility only; this is not a surface state transition."""

    ELIGIBLE_FOR_REVIEW = "eligible_for_review"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class SurfacePromotionReviewAssessment:
    """Replayable reasons for allowing or holding a separate human review."""

    decision: PromotionReviewDecision
    reason_codes: tuple[str, ...]
    review_authority: str = field(default="review_only", init=False)
    promotion_authority: bool = field(default=False, init=False)
    execution_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("promotion review reason_codes MUST be unique and ordered")
        if self.decision is PromotionReviewDecision.ELIGIBLE_FOR_REVIEW and self.reason_codes:
            raise ValueError("eligible promotion review MUST NOT carry hold reasons")
        if self.decision is PromotionReviewDecision.HOLD and not self.reason_codes:
            raise ValueError("held promotion review MUST carry reasons")


def assess_surface_promotion_review(
    receipt: SurfaceValidationReceipt,
    *,
    current_policy: RetrievalEvaluationPolicy,
    expected_surface_digest: str,
    expected_generation_digest: str,
    expected_catalog_digest: str,
    expected_dataset_digest: str,
    expected_evaluator_ref: str,
) -> SurfacePromotionReviewAssessment:
    """Return review eligibility without promoting, activating, or granting authority."""

    for name, value in (
        ("expected_surface_digest", expected_surface_digest),
        ("expected_generation_digest", expected_generation_digest),
        ("expected_catalog_digest", expected_catalog_digest),
        ("expected_dataset_digest", expected_dataset_digest),
    ):
        if _DIGEST.fullmatch(value) is None:
            raise ValueError(f"{name} MUST be a sha256 digest")
    if _IDENTIFIER.fullmatch(expected_evaluator_ref) is None:
        raise ValueError("expected_evaluator_ref MUST be a bounded ASCII identifier")

    reasons: list[str] = []
    if receipt.surface_digest != expected_surface_digest:
        reasons.append("surface-digest-mismatch")
    if receipt.generation_digest != expected_generation_digest:
        reasons.append("generation-digest-mismatch")
    if receipt.catalog_digest != expected_catalog_digest:
        reasons.append("catalog-digest-mismatch")
    if receipt.dataset_digest != expected_dataset_digest:
        reasons.append("dataset-digest-mismatch")
    if receipt.evaluator_ref != expected_evaluator_ref:
        reasons.append("evaluator-ref-mismatch")
    if receipt.evaluation_policy_digest != current_policy.digest:
        reasons.append("evaluation-policy-digest-mismatch")
    if receipt.decision is not ValidationDecision.PASS:
        reasons.append("validation-decision-not-pass")
    if receipt.failure_codes:
        reasons.append("validation-failures-present")
    if receipt.validation_authority != "validation_only":
        reasons.append("validation-authority-mismatch")
    if receipt.schema_version != "1.1.0":
        reasons.append("validation-schema-version-mismatch")

    covered_cohorts = {item.cohort for item in receipt.cohort_metrics}
    reasons.extend(
        f"required-cohort-missing:{cohort}"
        for cohort in current_policy.required_cohorts
        if cohort not in covered_cohorts
    )
    if receipt.evaluation_policy_digest == current_policy.digest:
        metric_thresholds = {
            f"recall-at-{current_policy.top_k}": current_policy.min_recall_at_k,
            "mean-reciprocal-rank": current_policy.min_mean_reciprocal_rank,
            "no-match-precision": current_policy.min_no_match_precision,
            "retrieval-success-rate": 1.0,
        }
        metrics_by_cohort = {
            cohort: {item.metric for item in receipt.cohort_metrics if item.cohort == cohort}
            for cohort in covered_cohorts
        }
        reasons.extend(
            f"unrecognized-metric:{item.cohort}:{item.metric}"
            for item in receipt.cohort_metrics
            if item.metric not in metric_thresholds
        )
        recall_metric = f"recall-at-{current_policy.top_k}"
        for cohort, metrics in metrics_by_cohort.items():
            if (recall_metric in metrics) != ("mean-reciprocal-rank" in metrics):
                missing_metric = (
                    "mean-reciprocal-rank" if recall_metric in metrics else recall_metric
                )
                reasons.append(f"required-metric-missing:{cohort}:{missing_metric}")
            if not metrics.intersection(
                {recall_metric, "mean-reciprocal-rank", "no-match-precision"}
            ):
                reasons.append(f"required-cohort-metrics-missing:{cohort}")
        reasons.extend(
            f"metric-below-current-threshold:{item.cohort}:{item.metric}"
            for item in receipt.cohort_metrics
            if (threshold := metric_thresholds.get(item.metric)) is not None
            and item.value < threshold
        )
    ordered_reasons = tuple(sorted(reasons))
    decision = (
        PromotionReviewDecision.HOLD
        if ordered_reasons
        else PromotionReviewDecision.ELIGIBLE_FOR_REVIEW
    )
    return SurfacePromotionReviewAssessment(decision=decision, reason_codes=ordered_reasons)


__all__ = [
    "PromotionReviewDecision",
    "SurfacePromotionReviewAssessment",
    "assess_surface_promotion_review",
]
