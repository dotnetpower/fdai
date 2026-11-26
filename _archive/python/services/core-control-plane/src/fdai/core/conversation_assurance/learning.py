"""Subscription-scoped learning statistics and bounded failure clustering."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from fdai.core.conversation_assurance.attribution import (
    ConversationStage,
    StructuralFailureAttribution,
)
from fdai.core.conversation_assurance.models import (
    AssessmentRecord,
    AssuranceCriterion,
    AssuranceVerdict,
)


@dataclass(frozen=True, slots=True)
class AccuracyPosterior:
    alpha: float
    beta: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.alpha) or not math.isfinite(self.beta):
            raise ValueError("posterior parameters MUST be finite")
        if self.alpha <= 0.0 or self.beta <= 0.0:
            raise ValueError("posterior parameters MUST be positive")

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        total = self.alpha + self.beta
        return self.alpha * self.beta / (total * total * (total + 1.0))

    def observe(self, *, correct: bool) -> AccuracyPosterior:
        return AccuracyPosterior(
            alpha=self.alpha + int(correct),
            beta=self.beta + int(not correct),
        )


@dataclass(frozen=True, slots=True)
class FailureCluster:
    cluster_id: str
    principal_scope: str
    signature_digest: str
    failed_criteria: tuple[AssuranceCriterion, ...]
    reasons: tuple[str, ...]
    sample_count: int
    assessment_ids: tuple[str, ...]


class ImprovementReviewState(StrEnum):
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True, slots=True)
class StructuralImprovementCandidate:
    """Describe a repeated structural weakness without activating a change."""

    candidate_id: str
    root_stage: ConversationStage
    sample_count: int
    channel_kind: str | None
    locale: str | None
    route_id: str | None
    failed_rubrics: tuple[str, ...]
    reason_codes: tuple[str, ...]
    review_state: ImprovementReviewState = ImprovementReviewState.REVIEW_REQUIRED
    merge_authority: Literal[False] = False
    execution_authority: Literal[False] = False


def cluster_failures(
    records: tuple[AssessmentRecord, ...],
    *,
    min_samples: int = 3,
    max_examples: int = 8,
) -> tuple[FailureCluster, ...]:
    """Group repeated failures without using raw customer identifiers."""

    if not 2 <= min_samples <= 100:
        raise ValueError("min_samples MUST be in [2, 100]")
    if not 1 <= max_examples <= 32:
        raise ValueError("max_examples MUST be in [1, 32]")
    grouped: dict[
        tuple[str, tuple[AssuranceCriterion, ...], tuple[str, ...]],
        list[AssessmentRecord],
    ] = {}
    for record in records:
        if record.decision.verdict is not AssuranceVerdict.FAIL:
            continue
        failed = tuple(
            sorted(
                (item.criterion for item in record.decision.criteria if item.score < 3),
                key=str,
            )
        )
        key = record.principal_scope, failed, tuple(sorted(record.decision.reasons))
        grouped.setdefault(key, []).append(record)
    clusters: list[FailureCluster] = []
    for (principal_scope, failed, reasons), samples in grouped.items():
        if len(samples) < min_samples:
            continue
        material = "\0".join((principal_scope, *map(str, failed), *reasons))
        signature = hashlib.sha256(material.encode()).hexdigest()
        clusters.append(
            FailureCluster(
                cluster_id=f"assurance-cluster:{signature[:32]}",
                principal_scope=principal_scope,
                signature_digest=signature,
                failed_criteria=failed,
                reasons=reasons,
                sample_count=len(samples),
                assessment_ids=tuple(item.assessment_id for item in samples[:max_examples]),
            )
        )
    return tuple(sorted(clusters, key=lambda item: (-item.sample_count, item.cluster_id)))


def build_structural_improvement_candidates(
    attributions: tuple[StructuralFailureAttribution, ...],
    *,
    min_samples: int = 3,
    max_candidates: int = 20,
) -> tuple[StructuralImprovementCandidate, ...]:
    """Create review-only candidates from repeated content-free failure signatures."""

    if not 2 <= min_samples <= 100:
        raise ValueError("structural candidate min_samples MUST be in [2, 100]")
    if not 1 <= max_candidates <= 100:
        raise ValueError("structural candidate max_candidates MUST be in [1, 100]")
    grouped: dict[
        tuple[
            ConversationStage,
            str | None,
            str | None,
            str | None,
            tuple[str, ...],
            tuple[str, ...],
        ],
        int,
    ] = {}
    for attribution in attributions:
        if attribution.root_stage is None:
            continue
        key = (
            attribution.root_stage,
            attribution.channel_kind,
            attribution.locale,
            attribution.route_id,
            attribution.failed_rubrics,
            attribution.reason_codes,
        )
        grouped[key] = grouped.get(key, 0) + 1
    candidates: list[StructuralImprovementCandidate] = []
    for key, sample_count in grouped.items():
        if sample_count < min_samples:
            continue
        root_stage, channel_kind, locale, route_id, failed_rubrics, reason_codes = key
        material = "\0".join(
            (
                root_stage.value,
                channel_kind or "",
                locale or "",
                route_id or "",
                *failed_rubrics,
                *reason_codes,
            )
        )
        candidates.append(
            StructuralImprovementCandidate(
                candidate_id="structural-improvement:"
                + hashlib.sha256(material.encode()).hexdigest(),
                root_stage=root_stage,
                sample_count=sample_count,
                channel_kind=channel_kind,
                locale=locale,
                route_id=route_id,
                failed_rubrics=failed_rubrics,
                reason_codes=reason_codes,
            )
        )
    return tuple(
        sorted(candidates, key=lambda item: (-item.sample_count, item.candidate_id))[
            :max_candidates
        ]
    )


__all__ = [
    "AccuracyPosterior",
    "FailureCluster",
    "ImprovementReviewState",
    "StructuralImprovementCandidate",
    "build_structural_improvement_candidates",
    "cluster_failures",
]
