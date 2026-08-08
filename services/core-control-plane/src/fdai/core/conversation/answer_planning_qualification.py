"""Deterministic readiness evaluation for shadow answer planning evidence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.conversation.answer_planning import AnswerPlanningConfig


class PlanningEvaluationLocale(StrEnum):
    EN = "en"
    KO = "ko"


@dataclass(frozen=True, slots=True)
class AnswerPlanningEvaluationSample:
    """One frozen baseline-versus-candidate planning observation."""

    case_id: str
    locale: PlanningEvaluationLocale
    baseline_unique_evidence_count: int
    candidate_unique_evidence_count: int
    baseline_correction_required: bool
    candidate_correction_required: bool
    baseline_follow_up_required: bool
    candidate_follow_up_required: bool
    unsupported_claim_escape: bool
    authority_violation: bool
    clean_answer_regression: bool
    planning_elapsed_ms: int
    added_tokens: int

    def __post_init__(self) -> None:
        if not self.case_id.strip() or len(self.case_id) > 128:
            raise ValueError("case_id MUST contain 1-128 characters")
        counts = (
            self.baseline_unique_evidence_count,
            self.candidate_unique_evidence_count,
            self.planning_elapsed_ms,
            self.added_tokens,
        )
        if any(value < 0 for value in counts):
            raise ValueError("planning evaluation counts MUST be non-negative")


@dataclass(frozen=True, slots=True)
class AnswerPlanningEvaluationBatch:
    """Immutable version-pinned evidence supplied by an external frozen runner."""

    scenario_set_version: str
    runner_version: str
    samples: tuple[AnswerPlanningEvaluationSample, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("scenario_set_version", self.scenario_set_version),
            ("runner_version", self.runner_version),
        ):
            if not value.strip() or len(value) > 128:
                raise ValueError(f"{name} MUST contain 1-128 characters")
        case_ids = [sample.case_id for sample in self.samples]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("planning evaluation case_id values MUST be unique")

    @property
    def content_digest(self) -> str:
        payload = {
            "runner_version": self.runner_version,
            "samples": [
                {
                    "added_tokens": sample.added_tokens,
                    "authority_violation": sample.authority_violation,
                    "baseline_correction_required": sample.baseline_correction_required,
                    "baseline_follow_up_required": sample.baseline_follow_up_required,
                    "baseline_unique_evidence_count": sample.baseline_unique_evidence_count,
                    "candidate_correction_required": sample.candidate_correction_required,
                    "candidate_follow_up_required": sample.candidate_follow_up_required,
                    "candidate_unique_evidence_count": sample.candidate_unique_evidence_count,
                    "case_id": sample.case_id,
                    "clean_answer_regression": sample.clean_answer_regression,
                    "locale": sample.locale.value,
                    "planning_elapsed_ms": sample.planning_elapsed_ms,
                    "unsupported_claim_escape": sample.unsupported_claim_escape,
                }
                for sample in self.samples
            ],
            "scenario_set_version": self.scenario_set_version,
        }
        canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AnswerPlanningQualificationPolicy:
    """Frozen benefit and safety thresholds for a separate promotion review."""

    min_samples: int = 100
    min_samples_per_locale: int = 50
    max_p95_elapsed_ms: int = 1_200
    max_added_tokens: int = 800
    min_unique_evidence_gain_rate: float = 0.5

    def __post_init__(self) -> None:
        shipping = AnswerPlanningConfig()
        if self.min_samples < 2 or self.min_samples_per_locale < 1:
            raise ValueError("planning qualification sample floors MUST be positive")
        if self.min_samples_per_locale * len(PlanningEvaluationLocale) > self.min_samples:
            raise ValueError("locale sample floors MUST fit within min_samples")
        if not 1 <= self.max_p95_elapsed_ms <= shipping.max_wall_ms:
            raise ValueError("qualification latency MUST remain within the shipping budget")
        if not 1 <= self.max_added_tokens <= shipping.max_added_tokens:
            raise ValueError("qualification tokens MUST remain within the shipping budget")
        if not math.isfinite(self.min_unique_evidence_gain_rate) or not (
            0.0 < self.min_unique_evidence_gain_rate <= 1.0
        ):
            raise ValueError("unique evidence gain rate MUST be finite and in (0, 1]")


@dataclass(frozen=True, slots=True)
class AnswerPlanningQualificationReceipt:
    """Measured readiness receipt that grants no activation authority."""

    scenario_set_version: str
    runner_version: str
    evidence_digest: str
    sample_count: int
    english_samples: int
    korean_samples: int
    unsupported_claim_escapes: int
    authority_violations: int
    clean_answer_regressions: int
    p95_elapsed_ms: int
    max_added_tokens: int
    unique_evidence_gain_rate: float
    baseline_correction_rate: float
    candidate_correction_rate: float
    baseline_follow_up_rate: float
    candidate_follow_up_rate: float
    ready_for_review: bool
    gaps: tuple[str, ...]


def evaluate_answer_planning_qualification(
    batch: AnswerPlanningEvaluationBatch,
    *,
    policy: AnswerPlanningQualificationPolicy | None = None,
) -> AnswerPlanningQualificationReceipt:
    """Measure one frozen batch without changing answer or promotion state."""

    effective_policy = policy or AnswerPlanningQualificationPolicy()
    samples = batch.samples
    sample_count = len(samples)
    english_samples = sum(sample.locale is PlanningEvaluationLocale.EN for sample in samples)
    korean_samples = sum(sample.locale is PlanningEvaluationLocale.KO for sample in samples)
    unsupported_claim_escapes = sum(sample.unsupported_claim_escape for sample in samples)
    authority_violations = sum(sample.authority_violation for sample in samples)
    clean_answer_regressions = sum(sample.clean_answer_regression for sample in samples)
    elapsed = sorted(sample.planning_elapsed_ms for sample in samples)
    p95_elapsed_ms = elapsed[max(0, math.ceil(len(elapsed) * 0.95) - 1)] if elapsed else 0
    max_added_tokens = max((sample.added_tokens for sample in samples), default=0)
    unique_evidence_gains = sum(
        sample.candidate_unique_evidence_count > sample.baseline_unique_evidence_count
        for sample in samples
    )
    unique_evidence_gain_rate = _rate(unique_evidence_gains, sample_count)
    baseline_correction_rate = _rate(
        sum(sample.baseline_correction_required for sample in samples), sample_count
    )
    candidate_correction_rate = _rate(
        sum(sample.candidate_correction_required for sample in samples), sample_count
    )
    baseline_follow_up_rate = _rate(
        sum(sample.baseline_follow_up_required for sample in samples), sample_count
    )
    candidate_follow_up_rate = _rate(
        sum(sample.candidate_follow_up_required for sample in samples), sample_count
    )

    gaps: list[str] = []
    if sample_count < effective_policy.min_samples:
        gaps.append(f"sample_count={sample_count}<min_samples={effective_policy.min_samples}")
    if english_samples < effective_policy.min_samples_per_locale:
        gaps.append(
            f"english_samples={english_samples}"
            f"<min_samples_per_locale={effective_policy.min_samples_per_locale}"
        )
    if korean_samples < effective_policy.min_samples_per_locale:
        gaps.append(
            f"korean_samples={korean_samples}"
            f"<min_samples_per_locale={effective_policy.min_samples_per_locale}"
        )
    if unsupported_claim_escapes:
        gaps.append(f"unsupported_claim_escapes={unsupported_claim_escapes}")
    if authority_violations:
        gaps.append(f"authority_violations={authority_violations}")
    if clean_answer_regressions:
        gaps.append(f"clean_answer_regressions={clean_answer_regressions}")
    if p95_elapsed_ms > effective_policy.max_p95_elapsed_ms:
        gaps.append(
            f"p95_elapsed_ms={p95_elapsed_ms}"
            f">max_p95_elapsed_ms={effective_policy.max_p95_elapsed_ms}"
        )
    if max_added_tokens > effective_policy.max_added_tokens:
        gaps.append(
            f"max_added_tokens={max_added_tokens}"
            f">max_added_tokens_budget={effective_policy.max_added_tokens}"
        )
    if unique_evidence_gain_rate < effective_policy.min_unique_evidence_gain_rate:
        gaps.append(
            f"unique_evidence_gain_rate={unique_evidence_gain_rate:.3f}"
            f"<min_unique_evidence_gain_rate="
            f"{effective_policy.min_unique_evidence_gain_rate:.3f}"
        )
    if candidate_correction_rate > baseline_correction_rate:
        gaps.append(
            f"candidate_correction_rate={candidate_correction_rate:.3f}"
            f">baseline_correction_rate={baseline_correction_rate:.3f}"
        )
    if candidate_follow_up_rate > baseline_follow_up_rate:
        gaps.append(
            f"candidate_follow_up_rate={candidate_follow_up_rate:.3f}"
            f">baseline_follow_up_rate={baseline_follow_up_rate:.3f}"
        )

    return AnswerPlanningQualificationReceipt(
        scenario_set_version=batch.scenario_set_version,
        runner_version=batch.runner_version,
        evidence_digest=batch.content_digest,
        sample_count=sample_count,
        english_samples=english_samples,
        korean_samples=korean_samples,
        unsupported_claim_escapes=unsupported_claim_escapes,
        authority_violations=authority_violations,
        clean_answer_regressions=clean_answer_regressions,
        p95_elapsed_ms=p95_elapsed_ms,
        max_added_tokens=max_added_tokens,
        unique_evidence_gain_rate=unique_evidence_gain_rate,
        baseline_correction_rate=baseline_correction_rate,
        candidate_correction_rate=candidate_correction_rate,
        baseline_follow_up_rate=baseline_follow_up_rate,
        candidate_follow_up_rate=candidate_follow_up_rate,
        ready_for_review=not gaps,
        gaps=tuple(gaps),
    )


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


__all__ = [
    "AnswerPlanningEvaluationBatch",
    "AnswerPlanningEvaluationSample",
    "AnswerPlanningQualificationPolicy",
    "AnswerPlanningQualificationReceipt",
    "PlanningEvaluationLocale",
    "evaluate_answer_planning_qualification",
]
