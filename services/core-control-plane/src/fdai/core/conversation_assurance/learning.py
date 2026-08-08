"""Subscription-scoped learning statistics and bounded failure clustering."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

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


__all__ = ["AccuracyPosterior", "FailureCluster", "cluster_failures"]
