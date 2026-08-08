"""Frozen-corpus scoring and live-shadow promotion evidence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from fdai.rule_catalog.pipeline.distill.ontology_models import (
    ClaimDisposition,
    GateOutcome,
    ProposalState,
    stable_digest,
)
from fdai.rule_catalog.pipeline.distill.ontology_review import OntologyReviewPackage
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    proposal_fact_key,
    proposal_value_digest,
)

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ChangeRiskClass(StrEnum):
    LOW_RISK_MAPPING = "low_risk_mapping"
    GOVERNED_INTENT = "governed_intent"
    CATALOG = "catalog"
    SCHEMA = "schema"
    AUTHORITY = "authority"
    CONFLICT = "conflict"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ExpectedOntologyFact:
    claim_id: str
    fact_key: str
    value_digest: str
    critical: bool

    def __post_init__(self) -> None:
        if not self.claim_id:
            raise ValueError("expected ontology fact claim_id MUST be non-empty")
        if _SHA256.fullmatch(self.fact_key) is None or _SHA256.fullmatch(self.value_digest) is None:
            raise ValueError("expected ontology fact keys MUST be SHA-256 digests")
        if type(self.critical) is not bool:
            raise ValueError("expected ontology fact critical flag MUST be boolean")


@dataclass(frozen=True, slots=True)
class ReviewEvaluationReport:
    true_positive: int
    false_positive: int
    false_negative: int
    expected_critical_claims: int
    mapped_critical_claims: int
    semantic_review_count: int
    denied_proposals: int

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 1.0

    @property
    def critical_claim_recall(self) -> float:
        if self.expected_critical_claims == 0:
            return 1.0
        return self.mapped_critical_claims / self.expected_critical_claims


@dataclass(frozen=True, slots=True)
class NormalizedReviewProjection:
    """Format-neutral digests for claims, proposals, and graph operations."""

    claim_digest: str
    proposal_digest: str
    graph_digest: str


def normalize_review_package(package: OntologyReviewPackage) -> NormalizedReviewProjection:
    """Remove document identity and locator differences before corpus comparison."""
    claims = sorted(
        (
            claim.kind.value,
            claim.authority.value,
            claim.critical,
            claim.evidence.text_sha256,
        )
        for claim in package.claims
    )
    active = tuple(
        item.proposal for item in package.proposals if item.state is not ProposalState.DENIED
    )
    proposals = [
        (
            proposal.operation.value,
            proposal.target_kind.value,
            proposal.target_type,
            proposal.target_identity,
            proposal.authority.value,
            tuple((item.name, item.value) for item in proposal.properties),
            proposal.from_identity,
            proposal.to_identity,
        )
        for proposal in active
    ]
    proposals.sort(key=stable_digest)
    graph = sorted(
        (
            proposal.operation.value,
            proposal_fact_key(proposal),
            proposal_value_digest(proposal),
        )
        for proposal in active
    )
    return NormalizedReviewProjection(
        claim_digest=stable_digest(claims),
        proposal_digest=stable_digest(proposals),
        graph_digest=stable_digest(graph),
    )


@dataclass(frozen=True, slots=True)
class ShadowReviewOutcome:
    proposal_digest: str
    observed_day: date
    reviewed: bool
    risk_class: ChangeRiskClass
    correct: bool
    authority_violation: bool = False
    policy_escape: bool = False
    wrong_target: bool = False
    unverified_truth: bool = False

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.proposal_digest) is None:
            raise ValueError("shadow outcome proposal_digest MUST be a SHA-256 digest")
        if type(self.observed_day) is not date:
            raise ValueError("shadow outcome observed_day MUST be a date")
        flags = (
            self.reviewed,
            self.correct,
            self.authority_violation,
            self.policy_escape,
            self.wrong_target,
            self.unverified_truth,
        )
        if any(type(flag) is not bool for flag in flags):
            raise ValueError("shadow outcome flags MUST be booleans")


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    min_distinct_days: int = 30
    min_reviewed_samples: int = 500
    min_precision_lower_bound: float = 0.99

    def __post_init__(self) -> None:
        if self.min_distinct_days < 1 or self.min_reviewed_samples < 1:
            raise ValueError("promotion day and sample floors MUST be positive")
        if not 0.0 <= self.min_precision_lower_bound <= 1.0:
            raise ValueError("promotion precision lower bound MUST be in [0, 1]")


@dataclass(frozen=True, slots=True)
class PromotionAssessment:
    eligible: bool
    reviewed_samples: int
    correct_samples: int
    distinct_days: int
    precision_lower_bound: float
    reason_codes: tuple[str, ...]


def evaluate_review_package(
    package: OntologyReviewPackage,
    expected: tuple[ExpectedOntologyFact, ...],
) -> ReviewEvaluationReport:
    """Score a review package against one frozen annotation set."""
    expected_identities = [(item.fact_key, item.value_digest) for item in expected]
    if len(expected_identities) != len(set(expected_identities)):
        raise ValueError("expected ontology facts MUST be unique")
    expected_pairs = {(item.fact_key, item.value_digest) for item in expected}
    predicted_pairs = {
        (proposal_fact_key(item.proposal), proposal_value_digest(item.proposal))
        for item in package.proposals
        if item.state is not ProposalState.DENIED
    }
    mapped = {
        item.claim_id for item in package.resolutions if item.disposition is ClaimDisposition.MAPPED
    }
    expected_critical = {item.claim_id for item in expected if item.critical}
    semantic_reviews = sum(
        receipt.gate == "semantic_fidelity" and receipt.outcome is GateOutcome.REVIEW
        for item in package.proposals
        for receipt in item.receipts
    )
    return ReviewEvaluationReport(
        true_positive=len(predicted_pairs & expected_pairs),
        false_positive=len(predicted_pairs - expected_pairs),
        false_negative=len(expected_pairs - predicted_pairs),
        expected_critical_claims=len(expected_critical),
        mapped_critical_claims=len(expected_critical & mapped),
        semantic_review_count=semantic_reviews,
        denied_proposals=sum(item.state is ProposalState.DENIED for item in package.proposals),
    )


def assess_low_risk_promotion(
    outcomes: tuple[ShadowReviewOutcome, ...],
    *,
    as_of: date,
    policy: PromotionPolicy | None = None,
) -> PromotionAssessment:
    """Assess evidence only; this function never changes a promotion registry."""
    if type(as_of) is not date:
        raise ValueError("promotion assessment as_of MUST be a date")
    active_policy = policy or PromotionPolicy()
    digests = [outcome.proposal_digest for outcome in outcomes]
    if len(digests) != len(set(digests)):
        raise ValueError("shadow promotion proposal digests MUST be unique")

    future = tuple(outcome for outcome in outcomes if outcome.observed_day > as_of)
    samples = tuple(
        outcome
        for outcome in outcomes
        if outcome.reviewed
        and outcome.risk_class is ChangeRiskClass.LOW_RISK_MAPPING
        and outcome.observed_day <= as_of
    )
    correct = sum(outcome.correct for outcome in samples)
    days = len({outcome.observed_day for outcome in samples})
    lower, _ = _wilson_interval(correct, len(samples))
    reasons: list[str] = []
    if len(samples) < active_policy.min_reviewed_samples:
        reasons.append("insufficient_reviewed_samples")
    if days < active_policy.min_distinct_days:
        reasons.append("insufficient_distinct_days")
    if lower < active_policy.min_precision_lower_bound:
        reasons.append("precision_lower_bound_not_met")
    if future:
        reasons.append("future_observation")
    if any(outcome.authority_violation for outcome in outcomes):
        reasons.append("authority_violation")
    if any(outcome.policy_escape for outcome in outcomes):
        reasons.append("policy_escape")
    if any(outcome.wrong_target for outcome in outcomes):
        reasons.append("wrong_target")
    if any(outcome.unverified_truth for outcome in outcomes):
        reasons.append("unverified_truth")
    return PromotionAssessment(
        eligible=not reasons,
        reviewed_samples=len(samples),
        correct_samples=correct,
        distinct_days=days,
        precision_lower_bound=lower,
        reason_codes=tuple(reasons),
    )


def _wilson_interval(successes: int, samples: int) -> tuple[float, float]:
    if samples == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    proportion = successes / samples
    denominator = 1.0 + z * z / samples
    center = (proportion + z * z / (2.0 * samples)) / denominator
    margin = (
        z
        * math.sqrt((proportion * (1.0 - proportion) + z * z / (4.0 * samples)) / samples)
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


__all__ = [
    "ChangeRiskClass",
    "ExpectedOntologyFact",
    "NormalizedReviewProjection",
    "PromotionAssessment",
    "PromotionPolicy",
    "ReviewEvaluationReport",
    "ShadowReviewOutcome",
    "assess_low_risk_promotion",
    "evaluate_review_package",
    "normalize_review_package",
]
