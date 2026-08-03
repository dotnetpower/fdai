"""Generic conformance evaluation for bound ontology Distiller providers."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fdai.rule_catalog.pipeline.distill.ontology_claims import inventory_claims
from fdai.rule_catalog.pipeline.distill.ontology_corpus_gate import (
    CorpusGateAssessment,
    CorpusGateDecision,
    CorpusGatePolicy,
    CorpusPartition,
    PartitionEvidence,
    assess_corpus_gate,
)
from fdai.rule_catalog.pipeline.distill.ontology_evaluation import ExpectedOntologyFact
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    ClaimDisposition,
    GateOutcome,
    OntologyTargetKind,
    ProposalState,
    stable_digest,
)
from fdai.rule_catalog.pipeline.distill.ontology_review import (
    OntologyReviewPackage,
    build_ontology_review_package,
)
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    VerificationContext,
    proposal_fact_key,
    proposal_value_digest,
)
from fdai.shared.providers.distiller import (
    DistillationResult,
    Distiller,
    DistillerAvailability,
    DistillerCapabilityDescriptor,
    ManualDocument,
    describe_distiller,
)

_CONFORMANCE_CONTRACT = "ontology-distiller-conformance.v1"


@dataclass(frozen=True, slots=True)
class ConformanceExpectedFact:
    claim_id: str
    fact_key: str
    value_digest: str
    target_kind: OntologyTargetKind
    critical: bool

    def as_expected_fact(self) -> ExpectedOntologyFact:
        return ExpectedOntologyFact(
            claim_id=self.claim_id,
            fact_key=self.fact_key,
            value_digest=self.value_digest,
            critical=self.critical,
        )


@dataclass(frozen=True, slots=True)
class ConformanceCase:
    case_id: str
    partition: CorpusPartition
    document: ManualDocument
    verification_context: VerificationContext
    expected_facts: tuple[ConformanceExpectedFact, ...]

    def __post_init__(self) -> None:
        if not self.case_id.strip() or len(self.case_id) > 128:
            raise ValueError("conformance case id MUST be bounded and non-empty")
        if not self.expected_facts:
            raise ValueError("conformance case expected facts MUST be non-empty")
        identities = [(item.fact_key, item.value_digest) for item in self.expected_facts]
        if len(identities) != len(set(identities)):
            raise ValueError("conformance expected facts MUST be unique")


@dataclass(frozen=True, slots=True)
class ConformanceCaseResult:
    case_id: str
    partition: CorpusPartition
    candidate_count: int
    extraction_success: bool
    abstention_reason: str | None
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
    semantic_error_count: int
    false_positive_count: int
    false_negative_count: int
    replay_match: bool
    latency_ms: float
    cost_microunits: int | None

    @property
    def mapped_critical_recall(self) -> float:
        return _ratio_or_one(
            self.mapped_critical_claim_count,
            self.expected_critical_claim_count,
        )

    @property
    def entity_precision(self) -> float:
        return _ratio_or_one(self.correct_entity_count, self.predicted_entity_count)

    @property
    def link_precision(self) -> float:
        return _ratio_or_one(self.correct_link_count, self.predicted_link_count)


@dataclass(frozen=True, slots=True)
class DistillerConformanceReport:
    descriptor: DistillerCapabilityDescriptor
    case_results: tuple[ConformanceCaseResult, ...]
    assessment: CorpusGateAssessment


@dataclass(frozen=True, slots=True)
class OntologyExtractionAvailability:
    available: bool
    reason_code: str | None
    conformance_contract: str


async def evaluate_distiller_conformance(
    distiller: Distiller,
    *,
    cases: tuple[ConformanceCase, ...],
    required_partitions: tuple[CorpusPartition, ...],
    monotonic: Callable[[], float],
    cost_microunits: Callable[[ConformanceCase, DistillationResult], int] | None = None,
    policy: CorpusGatePolicy | None = None,
) -> DistillerConformanceReport:
    """Exercise one real binding twice per case and assess partition evidence."""
    if not cases:
        raise ValueError("Distiller conformance cases MUST be non-empty")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Distiller conformance case ids MUST be unique")
    descriptor = describe_distiller(distiller)
    results = tuple(
        [
            await _evaluate_case(
                distiller,
                descriptor=descriptor,
                case=case,
                monotonic=monotonic,
                cost_microunits=cost_microunits,
            )
            for case in cases
        ]
    )
    evidence = tuple(
        _partition_evidence(partition, results)
        for partition in required_partitions
        if any(item.partition == partition for item in results)
    )
    return DistillerConformanceReport(
        descriptor=descriptor,
        case_results=results,
        assessment=assess_corpus_gate(
            evidence,
            required_partitions=required_partitions,
            policy=policy,
        ),
    )


def resolve_ontology_extraction_capability(
    descriptor: DistillerCapabilityDescriptor,
    assessment: CorpusGateAssessment | None,
) -> OntologyExtractionAvailability:
    """Resolve availability only; never alter enablement, mode, or authority."""
    if descriptor.availability is not DistillerAvailability.AVAILABLE:
        return OntologyExtractionAvailability(
            available=False,
            reason_code=descriptor.reason_code or "provider_unavailable",
            conformance_contract=_CONFORMANCE_CONTRACT,
        )
    if (
        descriptor.contract_version != _CONFORMANCE_CONTRACT
        or assessment is None
        or assessment.decision is not CorpusGateDecision.PASS
    ):
        return OntologyExtractionAvailability(
            available=False,
            reason_code="conformance_not_passed",
            conformance_contract=_CONFORMANCE_CONTRACT,
        )
    return OntologyExtractionAvailability(
        available=True,
        reason_code=None,
        conformance_contract=_CONFORMANCE_CONTRACT,
    )


async def _evaluate_case(
    distiller: Distiller,
    *,
    descriptor: DistillerCapabilityDescriptor,
    case: ConformanceCase,
    monotonic: Callable[[], float],
    cost_microunits: Callable[[ConformanceCase, DistillationResult], int] | None,
) -> ConformanceCaseResult:
    first, first_elapsed = await _timed_distill(distiller, case.document, monotonic)
    replay, replay_elapsed = await _timed_distill(distiller, case.document, monotonic)
    extraction_run_id = "conformance-" + stable_digest(
        {
            "case_id": case.case_id,
            "binding_id": descriptor.binding_id,
            "binding_version": descriptor.binding_version,
            "contract_version": descriptor.contract_version,
        }
    )
    package = build_ontology_review_package(
        document=case.document,
        result=first,
        context=case.verification_context,
        extraction_run_id=extraction_run_id,
    )
    replay_package = build_ontology_review_package(
        document=case.document,
        result=replay,
        context=case.verification_context,
        extraction_run_id=extraction_run_id,
    )
    expected = {
        (item.fact_key, item.value_digest): item.target_kind for item in case.expected_facts
    }
    predicted = {
        (proposal_fact_key(item.proposal), proposal_value_digest(item.proposal)): (
            item.proposal.target_kind
        )
        for item in package.proposals
        if item.state is not ProposalState.DENIED
    }
    mapped_claim_ids = {
        item.claim_id for item in package.resolutions if item.disposition is ClaimDisposition.MAPPED
    }
    expected_critical_claim_ids = {item.claim_id for item in case.expected_facts if item.critical}
    citation_errors = _citation_error_count(case.document, first, package)
    semantic_errors = _semantic_error_count(case.document, first, package, citation_errors)
    cost = cost_microunits(case, first) if cost_microunits is not None else None
    if cost is not None and (type(cost) is not int or cost < 0):
        raise ValueError("Distiller conformance cost MUST be a non-negative integer")
    return ConformanceCaseResult(
        case_id=case.case_id,
        partition=case.partition,
        candidate_count=len(first.candidates),
        extraction_success=bool(first.candidates),
        abstention_reason=(
            descriptor.reason_code or "zero_candidates" if not first.candidates else None
        ),
        detected_claim_count=len(package.claims),
        accounted_detected_claim_count=len(package.resolutions),
        expected_critical_claim_count=len(expected_critical_claim_ids),
        mapped_critical_claim_count=len(expected_critical_claim_ids & mapped_claim_ids),
        predicted_entity_count=sum(
            kind is OntologyTargetKind.OBJECT for kind in predicted.values()
        ),
        correct_entity_count=sum(
            kind is OntologyTargetKind.OBJECT and expected.get(pair) is kind
            for pair, kind in predicted.items()
        ),
        predicted_link_count=sum(kind is OntologyTargetKind.LINK for kind in predicted.values()),
        correct_link_count=sum(
            kind is OntologyTargetKind.LINK and expected.get(pair) is kind
            for pair, kind in predicted.items()
        ),
        citation_count=len(first.candidates),
        citation_error_count=citation_errors,
        semantic_error_count=semantic_errors,
        false_positive_count=len(set(predicted) - set(expected)),
        false_negative_count=len(set(expected) - set(predicted)),
        replay_match=package.package_digest == replay_package.package_digest,
        latency_ms=round((first_elapsed + replay_elapsed) * 1000.0, 6),
        cost_microunits=cost,
    )


async def _timed_distill(
    distiller: Distiller,
    document: ManualDocument,
    monotonic: Callable[[], float],
) -> tuple[DistillationResult, float]:
    started = monotonic()
    result = await distiller.distill(document)
    ended = monotonic()
    elapsed = ended - started
    if not math.isfinite(started) or not math.isfinite(ended) or elapsed < 0.0:
        raise ValueError("Distiller conformance clock MUST be finite and monotonic")
    return result, elapsed


def _citation_error_count(
    document: ManualDocument,
    result: DistillationResult,
    package: OntologyReviewPackage,
) -> int:
    claims = inventory_claims(document)
    valid_assertion_hashes = {claim.evidence.text_sha256 for claim in claims}
    invalid_assertions = sum(
        not isinstance(candidate.body.get("source_assertion"), str)
        or hashlib.sha256(str(candidate.body.get("source_assertion", "")).encode()).hexdigest()
        not in valid_assertion_hashes
        for candidate in result.candidates
    )
    grounding_failures = sum(
        receipt.gate == "grounding" and receipt.outcome is not GateOutcome.PASS
        for item in package.proposals
        for receipt in item.receipts
    )
    return min(len(result.candidates), invalid_assertions + grounding_failures)


def _semantic_error_count(
    document: ManualDocument,
    result: DistillationResult,
    package: OntologyReviewPackage,
    citation_error_count: int,
) -> int:
    del document
    invalid_shapes = sum(issue.reason_code == "invalid_candidate_shape" for issue in package.issues)
    semantic_receipts = sum(
        receipt.gate == "semantic_fidelity" and receipt.outcome is not GateOutcome.PASS
        for item in package.proposals
        for receipt in item.receipts
    )
    return max(0, invalid_shapes - citation_error_count) + semantic_receipts


def _partition_evidence(
    partition: CorpusPartition,
    results: Sequence[ConformanceCaseResult],
) -> PartitionEvidence:
    selected = tuple(item for item in results if item.partition == partition)
    return PartitionEvidence(
        partition=partition,
        case_count=len(selected),
        extraction_success_count=sum(item.extraction_success for item in selected),
        detected_claim_count=sum(item.detected_claim_count for item in selected),
        accounted_detected_claim_count=sum(
            item.accounted_detected_claim_count for item in selected
        ),
        expected_critical_claim_count=sum(item.expected_critical_claim_count for item in selected),
        mapped_critical_claim_count=sum(item.mapped_critical_claim_count for item in selected),
        predicted_entity_count=sum(item.predicted_entity_count for item in selected),
        correct_entity_count=sum(item.correct_entity_count for item in selected),
        predicted_link_count=sum(item.predicted_link_count for item in selected),
        correct_link_count=sum(item.correct_link_count for item in selected),
        citation_count=sum(item.citation_count for item in selected),
        citation_error_count=sum(item.citation_error_count for item in selected),
        parser_rejection_count=0,
        provider_abstention_count=sum(not item.extraction_success for item in selected),
        replay_mismatch_count=sum(not item.replay_match for item in selected),
        semantic_error_count=sum(item.semantic_error_count for item in selected),
        latency_observation_count=len(selected),
        latency_total_ms=sum(item.latency_ms for item in selected),
        cost_observation_count=sum(item.cost_microunits is not None for item in selected),
        cost_total_microunits=sum(item.cost_microunits or 0 for item in selected),
    )


def _ratio_or_one(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


__all__ = [
    "ConformanceCase",
    "ConformanceCaseResult",
    "ConformanceExpectedFact",
    "DistillerConformanceReport",
    "OntologyExtractionAvailability",
    "evaluate_distiller_conformance",
    "resolve_ontology_extraction_capability",
]
