"""Held-out evaluation for proposal-only Rule semantic surfaces."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    CohortMetric,
    RuleSemanticSurface,
    SurfaceValidationReceipt,
    ValidationDecision,
    query_digest,
)

_COHORT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")


class EvaluationQueryOrigin(StrEnum):
    USER = "user"
    PROBE_GENERATED = "probe_generated"
    ASSURANCE_GENERATED = "assurance_generated"


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationCase:
    """One generic frozen query with an exact Rule oracle or explicit no-match."""

    case_id: str
    query: str
    cohort: str
    expected_rule_refs: tuple[str, ...]
    origin: EvaluationQueryOrigin
    generator_ref: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("case_id", self.case_id), ("cohort", self.cohort)):
            if not value.strip() or len(value) > 256:
                raise ValueError(f"{name} MUST be bounded and non-empty")
        if (
            not self.query.strip()
            or len(self.query) > 4096
            or any(ord(character) < 32 for character in self.query)
        ):
            raise ValueError("evaluation query MUST be bounded text without control characters")
        if self.expected_rule_refs != tuple(sorted(set(self.expected_rule_refs))):
            raise ValueError("expected Rule refs MUST be unique and ordered")
        if self.origin is not EvaluationQueryOrigin.USER and not self.generator_ref:
            raise ValueError("generated evaluation query MUST identify its generator")

    @property
    def digest(self) -> str:
        return query_digest(self.query)


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationPolicy:
    """Measured promotion thresholds supplied by configuration."""

    top_k: int
    min_recall_at_k: float
    min_mean_reciprocal_rank: float
    min_no_match_precision: float
    required_cohorts: tuple[str, ...]
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not 1 <= self.top_k <= 100:
            raise ValueError("top_k MUST be in [1, 100]")
        for name, value in (
            ("min_recall_at_k", self.min_recall_at_k),
            ("min_mean_reciprocal_rank", self.min_mean_reciprocal_rank),
            ("min_no_match_precision", self.min_no_match_precision),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} MUST be finite and in [0, 1]")
        if (
            not self.required_cohorts
            or len(self.required_cohorts) > 256
            or self.required_cohorts != tuple(sorted(set(self.required_cohorts)))
            or any(_COHORT.fullmatch(item) is None for item in self.required_cohorts)
        ):
            raise ValueError("required_cohorts MUST be bounded, unique, and ordered")
        if self.schema_version != "1.0.0":
            raise ValueError("unsupported retrieval evaluation policy schema_version")

    @property
    def digest(self) -> str:
        """Return the canonical identity of the governed threshold configuration."""

        payload = {
            "schema_version": self.schema_version,
            "top_k": self.top_k,
            "min_recall_at_k": self.min_recall_at_k,
            "min_mean_reciprocal_rank": self.min_mean_reciprocal_rank,
            "min_no_match_precision": self.min_no_match_precision,
            "required_cohorts": self.required_cohorts,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class RuleSemanticRetriever(Protocol):
    async def search(self, query: str, *, k: int) -> Sequence[str]: ...


async def evaluate_semantic_surface(
    surface: RuleSemanticSurface,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    retriever: RuleSemanticRetriever,
    policy: RetrievalEvaluationPolicy,
    evaluator_ref: str,
    generation_digest: str,
    catalog_digest: str,
) -> SurfaceValidationReceipt:
    """Evaluate held-out cohorts and return fail-closed validation-only evidence.

    Retrieval failures produce a HOLD receipt. Failed positive cases count as misses,
    while failed no-match cases never receive precision credit.
    """

    if not cases:
        raise ValueError("semantic surface evaluation cases MUST be non-empty")
    case_ids = tuple(item.case_id for item in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("semantic surface evaluation case ids MUST be unique")
    training_digests = tuple(sorted(query_digest(item) for item in surface.training_queries))
    evaluation_digests = tuple(sorted(item.digest for item in cases))
    if set(training_digests).intersection(evaluation_digests):
        raise ValueError("held-out evaluation query MUST NOT occur in surface training data")
    if not any(item.expected_rule_refs for item in cases) or not any(
        not item.expected_rule_refs for item in cases
    ):
        raise ValueError("evaluation dataset MUST include positive and explicit no-match cases")

    observed: dict[str, list[tuple[float, float, float | None]]] = defaultdict(list)
    retrieval_success: dict[str, list[float]] = defaultdict(list)
    retrieval_failures: set[str] = set()
    for case in cases:
        try:
            results = tuple(await retriever.search(case.query, k=policy.top_k))[: policy.top_k]
        except Exception:
            retrieval_success[case.cohort].append(0.0)
            retrieval_failures.add(f"{case.cohort}-retrieval-error")
            if case.expected_rule_refs:
                observed[case.cohort].append((0.0, 0.0, None))
            continue
        retrieval_success[case.cohort].append(1.0)
        if case.expected_rule_refs:
            expected = set(case.expected_rule_refs)
            recall = len(expected.intersection(results)) / len(expected)
            reciprocal_rank = next(
                (
                    1.0 / rank
                    for rank, rule_ref in enumerate(results, start=1)
                    if rule_ref in expected
                ),
                0.0,
            )
            observed[case.cohort].append((recall, reciprocal_rank, None))
        else:
            observed[case.cohort].append((0.0, 0.0, 1.0 if not results else 0.0))

    metrics: list[CohortMetric] = []
    failures = list(retrieval_failures)
    for cohort in sorted(retrieval_success):
        rows = observed[cohort]
        positives = tuple(row for row in rows if row[2] is None)
        negative_scores = tuple(row[2] for row in rows if row[2] is not None)
        success_scores = retrieval_success[cohort]
        if any(score < 1.0 for score in success_scores):
            metrics.append(
                CohortMetric(
                    cohort,
                    "retrieval-success-rate",
                    sum(success_scores) / len(success_scores),
                    len(success_scores),
                )
            )
        if positives:
            recall = sum(row[0] for row in positives) / len(positives)
            reciprocal_rank = sum(row[1] for row in positives) / len(positives)
            metrics.extend(
                (
                    CohortMetric(cohort, f"recall-at-{policy.top_k}", recall, len(positives)),
                    CohortMetric(cohort, "mean-reciprocal-rank", reciprocal_rank, len(positives)),
                )
            )
            if recall < policy.min_recall_at_k:
                failures.append(f"{cohort}-recall-below-threshold")
            if reciprocal_rank < policy.min_mean_reciprocal_rank:
                failures.append(f"{cohort}-mrr-below-threshold")
        if negative_scores:
            precision = sum(negative_scores) / len(negative_scores)
            metrics.append(
                CohortMetric(cohort, "no-match-precision", precision, len(negative_scores))
            )
            if precision < policy.min_no_match_precision:
                failures.append(f"{cohort}-no-match-below-threshold")

    return SurfaceValidationReceipt(
        surface_digest=surface.validation_subject_digest,
        generation_digest=generation_digest,
        catalog_digest=catalog_digest,
        dataset_digest=_dataset_digest(cases),
        evaluator_ref=evaluator_ref,
        evaluation_policy_digest=policy.digest,
        training_query_digests=training_digests,
        evaluation_query_digests=evaluation_digests,
        cohort_metrics=tuple(sorted(metrics, key=lambda item: (item.cohort, item.metric))),
        failure_codes=tuple(sorted(failures)),
        decision=ValidationDecision.HOLD if failures else ValidationDecision.PASS,
    )


def _dataset_digest(cases: Sequence[RetrievalEvaluationCase]) -> str:
    payload = [
        {
            "case_id": item.case_id,
            "query_digest": item.digest,
            "cohort": item.cohort,
            "expected_rule_refs": item.expected_rule_refs,
            "origin": item.origin.value,
            "generator_ref": item.generator_ref,
        }
        for item in sorted(cases, key=lambda candidate: candidate.case_id)
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "EvaluationQueryOrigin",
    "RetrievalEvaluationCase",
    "RetrievalEvaluationPolicy",
    "RuleSemanticRetriever",
    "evaluate_semantic_surface",
]
