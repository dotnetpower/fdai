"""Typed, partition-preserving release gates for ontology corpus evidence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum

_PARTITION_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,63}$")


class CorpusGateDecision(StrEnum):
    PASS = "pass"  # noqa: S105 - release decision, not a credential
    REVIEW = "review"
    DENY = "deny"


@dataclass(frozen=True, slots=True, order=True)
class CorpusPartition:
    source_format: str
    language: str

    def __post_init__(self) -> None:
        if _PARTITION_TOKEN.fullmatch(self.source_format) is None:
            raise ValueError("corpus source_format MUST be a bounded lowercase token")
        if _PARTITION_TOKEN.fullmatch(self.language) is None:
            raise ValueError("corpus language MUST be a bounded lowercase token")

    @property
    def key(self) -> str:
        return f"{self.source_format}:{self.language}"


@dataclass(frozen=True, slots=True)
class PartitionEvidence:
    partition: CorpusPartition
    case_count: int
    extraction_success_count: int
    detected_claim_count: int
    accounted_detected_claim_count: int
    expected_critical_claim_count: int
    mapped_critical_claim_count: int
    predicted_entity_count: int
    correct_entity_count: int
    predicted_link_count: int
    correct_link_count: int
    citation_count: int
    citation_error_count: int
    parser_rejection_count: int
    provider_abstention_count: int
    replay_mismatch_count: int
    semantic_error_count: int
    latency_observation_count: int
    latency_total_ms: float
    cost_observation_count: int
    cost_total_microunits: int

    def __post_init__(self) -> None:
        counts = (
            self.case_count,
            self.extraction_success_count,
            self.detected_claim_count,
            self.accounted_detected_claim_count,
            self.expected_critical_claim_count,
            self.mapped_critical_claim_count,
            self.predicted_entity_count,
            self.correct_entity_count,
            self.predicted_link_count,
            self.correct_link_count,
            self.citation_count,
            self.citation_error_count,
            self.parser_rejection_count,
            self.provider_abstention_count,
            self.replay_mismatch_count,
            self.semantic_error_count,
            self.latency_observation_count,
            self.cost_observation_count,
            self.cost_total_microunits,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("corpus evidence counts MUST be non-negative integers")
        if self.case_count < 1:
            raise ValueError("corpus partition case_count MUST be positive")
        if self.expected_critical_claim_count < 1:
            raise ValueError("corpus partition MUST contain expected critical claims")
        bounded_counts = (
            (self.extraction_success_count, self.case_count, "extraction success count"),
            (
                self.accounted_detected_claim_count,
                self.detected_claim_count,
                "accounted detected claim count",
            ),
            (
                self.mapped_critical_claim_count,
                self.expected_critical_claim_count,
                "mapped critical claim count",
            ),
            (self.correct_entity_count, self.predicted_entity_count, "correct entity count"),
            (self.correct_link_count, self.predicted_link_count, "correct link count"),
            (self.citation_error_count, self.citation_count, "citation error count"),
            (self.parser_rejection_count, self.case_count, "parser rejection count"),
            (self.provider_abstention_count, self.case_count, "provider abstention count"),
            (self.replay_mismatch_count, self.case_count, "replay mismatch count"),
            (self.latency_observation_count, self.case_count, "latency observation count"),
            (self.cost_observation_count, self.case_count, "cost observation count"),
        )
        for value, ceiling, label in bounded_counts:
            if value > ceiling:
                raise ValueError(f"corpus {label} MUST NOT exceed its denominator")
        if not math.isfinite(self.latency_total_ms) or self.latency_total_ms < 0.0:
            raise ValueError("corpus latency total MUST be finite and non-negative")


@dataclass(frozen=True, slots=True)
class PartitionMetrics:
    extraction_success_rate: float
    detected_claim_accounting: float
    mapped_critical_recall: float
    entity_precision: float
    link_precision: float
    citation_error_rate: float
    citation_error_count: int
    parser_rejection_count: int
    provider_abstention_count: int
    replay_mismatch_count: int
    semantic_error_count: int
    latency_observation_count: int
    latency_total_ms: float
    cost_observation_count: int
    cost_total_microunits: int


@dataclass(frozen=True, slots=True)
class CorpusGatePolicy:
    min_detected_claim_accounting: float = 1.0
    min_mapped_critical_recall: float = 0.98
    min_entity_precision: float = 0.98
    min_link_precision: float = 0.98
    max_citation_error_rate: float = 0.0
    max_citation_error_count: int = 0
    require_latency_evidence: bool = True
    require_cost_evidence: bool = True

    def __post_init__(self) -> None:
        rates = (
            self.min_detected_claim_accounting,
            self.min_mapped_critical_recall,
            self.min_entity_precision,
            self.min_link_precision,
            self.max_citation_error_rate,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in rates):
            raise ValueError("corpus gate rates MUST be finite values in [0, 1]")
        if type(self.max_citation_error_count) is not int or self.max_citation_error_count < 0:
            raise ValueError("maximum citation error count MUST be a non-negative integer")
        if type(self.require_latency_evidence) is not bool:
            raise ValueError("latency evidence requirement MUST be boolean")
        if type(self.require_cost_evidence) is not bool:
            raise ValueError("cost evidence requirement MUST be boolean")


@dataclass(frozen=True, slots=True)
class PartitionGateAssessment:
    partition: CorpusPartition
    decision: CorpusGateDecision
    reason_codes: tuple[str, ...]
    metrics: PartitionMetrics | None


@dataclass(frozen=True, slots=True)
class CorpusGateAssessment:
    decision: CorpusGateDecision
    reason_codes: tuple[str, ...]
    partitions: tuple[PartitionGateAssessment, ...]
    review_only: bool = field(default=True, init=False)
    authority_neutral: bool = field(default=True, init=False)


def assess_corpus_gate(
    evidence: tuple[PartitionEvidence, ...],
    *,
    required_partitions: tuple[CorpusPartition, ...],
    policy: CorpusGatePolicy | None = None,
) -> CorpusGateAssessment:
    """Assess every required partition without deriving execution authority."""
    if not required_partitions:
        raise ValueError("required corpus partitions MUST be non-empty")
    if len(required_partitions) != len(set(required_partitions)):
        raise ValueError("required corpus partitions MUST be unique")
    evidence_by_partition = {item.partition: item for item in evidence}
    if len(evidence_by_partition) != len(evidence):
        raise ValueError("corpus partition evidence MUST be unique")

    active_policy = policy or CorpusGatePolicy()
    partitions = tuple(
        _assess_partition(partition, evidence_by_partition.get(partition), active_policy)
        for partition in required_partitions
    )
    reason_codes = tuple(
        f"{item.partition.key}:{reason}" for item in partitions for reason in item.reason_codes
    )
    return CorpusGateAssessment(
        decision=_combined_decision(tuple(item.decision for item in partitions)),
        reason_codes=reason_codes,
        partitions=partitions,
    )


def _assess_partition(
    partition: CorpusPartition,
    evidence: PartitionEvidence | None,
    policy: CorpusGatePolicy,
) -> PartitionGateAssessment:
    if evidence is None:
        return PartitionGateAssessment(
            partition=partition,
            decision=CorpusGateDecision.REVIEW,
            reason_codes=("missing_partition",),
            metrics=None,
        )

    metrics = _metrics(evidence)
    review_reasons: list[str] = []
    deny_reasons: list[str] = []
    if evidence.extraction_success_count == 0:
        review_reasons.append("no_extraction_success")
    if evidence.extraction_success_count and evidence.citation_count == 0:
        review_reasons.append("no_citations")
    if evidence.extraction_success_count and not (
        evidence.predicted_entity_count or evidence.predicted_link_count
    ):
        review_reasons.append("no_ontology_predictions")
    if metrics.detected_claim_accounting < policy.min_detected_claim_accounting:
        review_reasons.append("detected_claim_accounting_below_threshold")
    if metrics.mapped_critical_recall < policy.min_mapped_critical_recall:
        review_reasons.append("critical_recall_below_threshold")
    if evidence.predicted_entity_count and metrics.entity_precision < policy.min_entity_precision:
        deny_reasons.append("entity_precision_below_threshold")
    if evidence.predicted_link_count and metrics.link_precision < policy.min_link_precision:
        deny_reasons.append("link_precision_below_threshold")
    if (
        metrics.citation_error_count > policy.max_citation_error_count
        or metrics.citation_error_rate > policy.max_citation_error_rate
    ):
        deny_reasons.append("citation_error")
    if evidence.parser_rejection_count:
        review_reasons.append("parser_rejection")
    if evidence.provider_abstention_count:
        review_reasons.append("provider_abstention")
    if evidence.replay_mismatch_count:
        deny_reasons.append("replay_mismatch")
    if evidence.semantic_error_count:
        deny_reasons.append("semantic_error")
    if policy.require_latency_evidence and evidence.latency_observation_count == 0:
        review_reasons.append("missing_latency_evidence")
    if policy.require_cost_evidence and evidence.cost_observation_count == 0:
        review_reasons.append("missing_cost_evidence")

    ordered_reasons = _ordered_reasons(review_reasons, deny_reasons)
    decision = CorpusGateDecision.DENY if deny_reasons else CorpusGateDecision.REVIEW
    if not ordered_reasons:
        decision = CorpusGateDecision.PASS
    return PartitionGateAssessment(partition, decision, ordered_reasons, metrics)


def _metrics(evidence: PartitionEvidence) -> PartitionMetrics:
    return PartitionMetrics(
        extraction_success_rate=evidence.extraction_success_count / evidence.case_count,
        detected_claim_accounting=_ratio_or_one(
            evidence.accounted_detected_claim_count,
            evidence.detected_claim_count,
        ),
        mapped_critical_recall=_ratio_or_one(
            evidence.mapped_critical_claim_count,
            evidence.expected_critical_claim_count,
        ),
        entity_precision=_ratio_or_one(
            evidence.correct_entity_count,
            evidence.predicted_entity_count,
        ),
        link_precision=_ratio_or_one(
            evidence.correct_link_count,
            evidence.predicted_link_count,
        ),
        citation_error_rate=_ratio_or_zero(
            evidence.citation_error_count,
            evidence.citation_count,
        ),
        citation_error_count=evidence.citation_error_count,
        parser_rejection_count=evidence.parser_rejection_count,
        provider_abstention_count=evidence.provider_abstention_count,
        replay_mismatch_count=evidence.replay_mismatch_count,
        semantic_error_count=evidence.semantic_error_count,
        latency_observation_count=evidence.latency_observation_count,
        latency_total_ms=evidence.latency_total_ms,
        cost_observation_count=evidence.cost_observation_count,
        cost_total_microunits=evidence.cost_total_microunits,
    )


def _ordered_reasons(review_reasons: list[str], deny_reasons: list[str]) -> tuple[str, ...]:
    reason_order = (
        "no_extraction_success",
        "no_citations",
        "no_ontology_predictions",
        "detected_claim_accounting_below_threshold",
        "critical_recall_below_threshold",
        "entity_precision_below_threshold",
        "link_precision_below_threshold",
        "citation_error",
        "parser_rejection",
        "provider_abstention",
        "replay_mismatch",
        "semantic_error",
        "missing_latency_evidence",
        "missing_cost_evidence",
    )
    reasons = set(review_reasons) | set(deny_reasons)
    return tuple(reason for reason in reason_order if reason in reasons)


def _combined_decision(decisions: tuple[CorpusGateDecision, ...]) -> CorpusGateDecision:
    if CorpusGateDecision.DENY in decisions:
        return CorpusGateDecision.DENY
    if CorpusGateDecision.REVIEW in decisions:
        return CorpusGateDecision.REVIEW
    return CorpusGateDecision.PASS


def _ratio_or_one(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _ratio_or_zero(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


__all__ = [
    "CorpusGateAssessment",
    "CorpusGateDecision",
    "CorpusGatePolicy",
    "CorpusPartition",
    "PartitionEvidence",
    "PartitionGateAssessment",
    "PartitionMetrics",
    "assess_corpus_gate",
]
