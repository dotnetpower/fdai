"""Generic conformance evaluation for bound ontology Distiller providers."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Sequence
from datetime import datetime

from fdai.rule_catalog.pipeline.distill.ontology_claims import inventory_claims
from fdai.rule_catalog.pipeline.distill.ontology_conformance_models import (
    CONFORMANCE_CONTRACT,
    PRODUCTION_REQUIRED_PARTITIONS,
    ConformanceCase,
    ConformanceCaseResult,
    ConformanceCostContext,
    ConformanceCostEvidence,
    ConformanceCostEvidenceProvider,
    ConformanceCostEvidenceVerifier,
    ConformanceEvidenceClass,
    ConformanceExpectedFact,
    ConformanceSourceEvidence,
    ConformanceSourceEvidenceVerifier,
    DistillerConformanceReport,
    OntologyExtractionAvailability,
    distiller_descriptor_digest,
)
from fdai.rule_catalog.pipeline.distill.ontology_corpus_gate import (
    CorpusGateDecision,
    CorpusGatePolicy,
    CorpusPartition,
    PartitionEvidence,
    assess_corpus_gate,
)
from fdai.rule_catalog.pipeline.distill.ontology_council import OntologyAwareDistiller
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


async def evaluate_distiller_conformance(
    distiller: Distiller | OntologyAwareDistiller,
    *,
    cases: tuple[ConformanceCase, ...],
    required_partitions: tuple[CorpusPartition, ...],
    monotonic: Callable[[], float],
    evaluated_at: datetime,
    source_evidence_verifier: ConformanceSourceEvidenceVerifier,
    cost_evidence: ConformanceCostEvidenceProvider | None = None,
    cost_evidence_verifier: ConformanceCostEvidenceVerifier | None = None,
    policy: CorpusGatePolicy | None = None,
) -> DistillerConformanceReport:
    """Exercise one real binding twice per case and assess partition evidence."""
    if not cases:
        raise ValueError("Distiller conformance cases MUST be non-empty")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Distiller conformance case ids MUST be unique")
    if evaluated_at.tzinfo is None:
        raise ValueError("Distiller conformance evaluated_at MUST be timezone-aware")
    if any(not source_evidence_verifier.verify(case) for case in cases):
        raise ValueError("Distiller conformance source evidence verification failed")
    descriptor = describe_distiller(distiller)
    descriptor_digest = distiller_descriptor_digest(descriptor)
    results = tuple(
        [
            await _evaluate_case(
                distiller,
                descriptor=descriptor,
                descriptor_digest=descriptor_digest,
                case=case,
                monotonic=monotonic,
                evaluated_at=evaluated_at,
                cost_evidence=cost_evidence,
                cost_evidence_verifier=cost_evidence_verifier,
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
        required_partitions=required_partitions,
        descriptor_digest=descriptor_digest,
    )


def resolve_ontology_extraction_capability(
    report: DistillerConformanceReport | None,
) -> OntologyExtractionAvailability:
    """Resolve availability only; never alter enablement, mode, or authority."""
    if report is None:
        return OntologyExtractionAvailability(
            available=False,
            reason_code="conformance_not_passed",
            conformance_contract=CONFORMANCE_CONTRACT,
        )
    descriptor = report.descriptor
    if descriptor.availability is not DistillerAvailability.AVAILABLE:
        return OntologyExtractionAvailability(
            available=False,
            reason_code=descriptor.reason_code or "provider_unavailable",
            conformance_contract=CONFORMANCE_CONTRACT,
        )
    if (
        descriptor.contract_version != CONFORMANCE_CONTRACT
        or report.descriptor_digest != distiller_descriptor_digest(descriptor)
        or report.required_partitions != PRODUCTION_REQUIRED_PARTITIONS
        or report.assessment.required_partitions != PRODUCTION_REQUIRED_PARTITIONS
        or report.assessment.decision is not CorpusGateDecision.PASS
        or not report.assessment.policy.require_independent_source_evidence
        or not report.assessment.policy.require_cost_evidence
        or not report.assessment.policy.require_verified_cost_evidence
    ):
        return OntologyExtractionAvailability(
            available=False,
            reason_code="conformance_not_passed",
            conformance_contract=CONFORMANCE_CONTRACT,
        )
    return OntologyExtractionAvailability(
        available=True,
        reason_code=None,
        conformance_contract=CONFORMANCE_CONTRACT,
    )


async def _evaluate_case(
    distiller: Distiller | OntologyAwareDistiller,
    *,
    descriptor: DistillerCapabilityDescriptor,
    descriptor_digest: str,
    case: ConformanceCase,
    monotonic: Callable[[], float],
    evaluated_at: datetime,
    cost_evidence: ConformanceCostEvidenceProvider | None,
    cost_evidence_verifier: ConformanceCostEvidenceVerifier | None,
) -> ConformanceCaseResult:
    first, first_elapsed = await _timed_distill(
        distiller,
        case.document,
        case.verification_context,
        monotonic,
    )
    replay, replay_elapsed = await _timed_distill(
        distiller,
        case.document,
        case.verification_context,
        monotonic,
    )
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
    cost_context = ConformanceCostContext(
        case_id=case.case_id,
        binding_digest=descriptor_digest,
        source_digest=case.source_evidence.source_digest,
        first_package_digest=package.package_digest,
        replay_package_digest=replay_package.package_digest,
        usage_digest=_usage_digest(first, replay),
        first_result=first,
        replay_result=replay,
    )
    cost_receipt = cost_evidence(cost_context) if cost_evidence is not None else None
    cost_verified = bool(
        cost_receipt is not None
        and cost_receipt.valid_for(cost_context, evaluated_at)
        and cost_evidence_verifier is not None
        and cost_evidence_verifier.verify(cost_context, cost_receipt)
    )
    cost = cost_receipt.total_microunits if cost_verified and cost_receipt is not None else None
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
        independently_authored=case.source_evidence.independently_authored,
        cost_verified=cost_verified,
        source_evidence_digest=case.source_evidence.content_digest,
        cost_evidence_digest=(
            cost_receipt.content_digest if cost_receipt is not None and cost_verified else None
        ),
        cost_verification_receipt_digest=(
            cost_receipt.verification_receipt_digest
            if cost_receipt is not None and cost_verified
            else None
        ),
        cost_currency=(
            cost_receipt.currency if cost_receipt is not None and cost_verified else None
        ),
    )


async def _timed_distill(
    distiller: Distiller | OntologyAwareDistiller,
    document: ManualDocument,
    context: VerificationContext,
    monotonic: Callable[[], float],
) -> tuple[DistillationResult, float]:
    started = monotonic()
    if isinstance(distiller, OntologyAwareDistiller):
        result = await distiller.distill_ontology(document, context)
    else:
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
    claims = inventory_claims(
        document,
        source_ranges=tuple(candidate.source_lines for candidate in result.candidates),
    )
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
    del document, result
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
    currencies = {item.cost_currency for item in selected if item.cost_currency is not None}
    if len(currencies) > 1:
        raise ValueError("Distiller conformance partition cost currencies MUST match")
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
        independent_source_case_count=sum(item.independently_authored for item in selected),
        verified_cost_observation_count=sum(item.cost_verified for item in selected),
        cost_currency=next(iter(currencies), None),
    )


def _usage_digest(first: DistillationResult, replay: DistillationResult) -> str:
    def material(result: DistillationResult) -> list[dict[str, object]]:
        return [
            {
                "initial": [
                    {
                        "completion_tokens": item.completion_tokens,
                        "model_digest": item.model_digest,
                        "prompt_tokens": item.prompt_tokens,
                    }
                    for item in receipt.initial_invocations
                ],
                "models": receipt.model_digests,
                "policy_digest": receipt.policy_digest,
                "revised": [
                    {
                        "completion_tokens": item.completion_tokens,
                        "model_digest": item.model_digest,
                        "prompt_tokens": item.prompt_tokens,
                    }
                    for item in receipt.revised_invocations
                ],
            }
            for receipt in result.council_receipts
        ]

    return stable_digest({"first": material(first), "replay": material(replay)})


__all__ = [
    "ConformanceCase",
    "ConformanceCaseResult",
    "ConformanceCostContext",
    "ConformanceCostEvidence",
    "ConformanceCostEvidenceProvider",
    "ConformanceCostEvidenceVerifier",
    "ConformanceEvidenceClass",
    "ConformanceExpectedFact",
    "ConformanceSourceEvidence",
    "ConformanceSourceEvidenceVerifier",
    "DistillerConformanceReport",
    "OntologyExtractionAvailability",
    "PRODUCTION_REQUIRED_PARTITIONS",
    "evaluate_distiller_conformance",
    "resolve_ontology_extraction_capability",
]
