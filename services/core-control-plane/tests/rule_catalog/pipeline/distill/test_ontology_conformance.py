"""Tests for real Distiller conformance and capability resolution."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.rule_catalog.pipeline.distill.ontology_claims import inventory_claims
from fdai.rule_catalog.pipeline.distill.ontology_conformance import (
    PRODUCTION_REQUIRED_PARTITIONS,
    ConformanceCase,
    ConformanceCostContext,
    ConformanceCostEvidence,
    ConformanceEvidenceClass,
    ConformanceExpectedFact,
    ConformanceSourceEvidence,
    OntologyExtractionAvailability,
    evaluate_distiller_conformance,
    resolve_ontology_extraction_capability,
)
from fdai.rule_catalog.pipeline.distill.ontology_corpus_gate import (
    CorpusGateDecision,
    CorpusGatePolicy,
    CorpusPartition,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    OntologyTargetKind,
    stable_digest,
)
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    EntityRecord,
    SourceAuthorityPolicy,
    VerificationContext,
)
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistillationResult,
    DistilledCandidate,
    DistillerAvailability,
    DistillerCapabilityDescriptor,
    ManualDocument,
    describe_distiller,
)

_PARTITION = CorpusPartition("markdown", "en")
_REQUIRED_SYNTHETIC_PARTITIONS = (
    CorpusPartition("pdf", "en"),
    CorpusPartition("ooxml", "en"),
    CorpusPartition("pdf", "ko"),
    CorpusPartition("ooxml", "ko"),
    CorpusPartition("ocr", "ko"),
)
_TEXT = "Checkout service is owned by Platform team."
_DIGEST = hashlib.sha256(_TEXT.encode()).hexdigest()
_EVALUATED_AT = datetime(2026, 9, 16, 12, tzinfo=UTC)


def _source_evidence(
    document: ManualDocument,
    evidence_class: ConformanceEvidenceClass = ConformanceEvidenceClass.LICENSED_PUBLIC,
) -> ConformanceSourceEvidence:
    return ConformanceSourceEvidence(
        evidence_class=evidence_class,
        source_digest=document.content_sha,
        manifest_digest="b" * 64,
        parser_receipt_digest="c" * 64,
        license_digest=(
            "d" * 64 if evidence_class is ConformanceEvidenceClass.LICENSED_PUBLIC else None
        ),
    )


def _cost_evidence(context: ConformanceCostContext) -> ConformanceCostEvidence:
    return ConformanceCostEvidence(
        context_digest=context.context_digest,
        first_microunits=len(context.first_result.candidates),
        replay_microunits=len(context.replay_result.candidates),
        currency="USD",
        pricing_source_digest="e" * 64,
        pricing_verified_at=_EVALUATED_AT - timedelta(days=1),
        pricing_expires_at=_EVALUATED_AT + timedelta(days=1),
        verification_receipt_digest="f" * 64,
    )


class StaticSourceEvidenceVerifier:
    def __init__(self, verified: bool = True) -> None:
        self._verified = verified

    def verify(self, case: ConformanceCase) -> bool:
        return self._verified and case.source_evidence.source_digest == case.document.content_sha


class StaticCostEvidenceVerifier:
    def verify(
        self,
        context: ConformanceCostContext,
        evidence: ConformanceCostEvidence,
    ) -> bool:
        return (
            evidence.context_digest == context.context_digest
            and evidence.first_microunits == len(context.first_result.candidates)
            and evidence.replay_microunits == len(context.replay_result.candidates)
        )


_SOURCE_VERIFIER = StaticSourceEvidenceVerifier()
_COST_VERIFIER = StaticCostEvidenceVerifier()


def _document() -> ManualDocument:
    return ManualDocument(
        doc_id="service-map",
        text=_TEXT,
        source_ref="doc:service-map",
        content_sha=_DIGEST,
        metadata={
            "access_policy_ref": "access:public-corpus",
            "revision": "rev-1",
            "source_format": "markdown",
        },
    )


def _context() -> VerificationContext:
    return VerificationContext(
        ontology_release="a" * 64,
        current_graph_revision="graph-1",
        object_types=frozenset({"BusinessService"}),
        links=(),
        entities=(EntityRecord("service:checkout", "BusinessService"),),
        source_policies=(
            SourceAuthorityPolicy(
                "doc:service-map",
                frozenset({AuthorityClass.DECLARED_INTENT}),
                10,
            ),
        ),
        claim_text=(),
    )


def _candidate(
    *,
    candidate_id: str = "candidate-1",
    source_assertion: str = _TEXT,
    target_identity: str = "service:checkout",
    extra_body: dict[str, object] | None = None,
) -> DistilledCandidate:
    body: dict[str, object] = {
        "operation": "update",
        "target_type": "BusinessService",
        "target_identity": target_identity,
        "authority": "declared_intent",
        "source_assertion": source_assertion,
        "properties": {"owner_ref": "team:platform"},
    }
    body.update(extra_body or {})
    return DistilledCandidate(
        kind=CandidateKind.ONTOLOGY_OBJECT,
        candidate_id=candidate_id,
        source_ref="doc:service-map",
        source_section="Ownership",
        source_lines=(1, 1),
        content_sha=_DIGEST,
        body=body,
    )


def _expected() -> ConformanceExpectedFact:
    claim_id = inventory_claims(_document())[0].claim_id
    fact_key = stable_digest(
        {
            "target_kind": "object",
            "target_type": "BusinessService",
            "target_identity": "service:checkout",
            "from_identity": None,
            "to_identity": None,
            "property_names": ["owner_ref"],
        }
    )
    value_digest = stable_digest([{"name": "owner_ref", "value": "team:platform"}])
    return ConformanceExpectedFact(
        claim_id=claim_id,
        fact_key=fact_key,
        value_digest=value_digest,
        target_kind=OntologyTargetKind.OBJECT,
        critical=True,
    )


def _case() -> ConformanceCase:
    document = _document()
    return ConformanceCase(
        case_id="service-map-en",
        partition=_PARTITION,
        document=document,
        verification_context=_context(),
        expected_facts=(_expected(),),
        source_evidence=_source_evidence(document),
    )


class StaticDistiller:
    def __init__(
        self,
        candidates: tuple[DistilledCandidate, ...],
        *,
        availability: DistillerAvailability = DistillerAvailability.AVAILABLE,
        reason_code: str | None = None,
    ) -> None:
        self._result = DistillationResult(candidates=candidates)
        self._descriptor = DistillerCapabilityDescriptor(
            binding_id="test-distiller",
            binding_version="1.0.0",
            contract_version="ontology-distiller-conformance.v1",
            availability=availability,
            reason_code=reason_code,
        )

    def distiller_capability(self) -> DistillerCapabilityDescriptor:
        return self._descriptor

    async def distill(self, document: ManualDocument) -> DistillationResult:
        assert document == _document()
        return self._result


class AlternatingDistiller(StaticDistiller):
    def __init__(self) -> None:
        super().__init__((_candidate(),))
        self._calls = 0

    async def distill(self, document: ManualDocument) -> DistillationResult:
        self._calls += 1
        candidate = _candidate(candidate_id=f"candidate-{self._calls}")
        return DistillationResult(candidates=(candidate,))


class AwareStaticDistiller:
    def __init__(self) -> None:
        self.contexts: list[VerificationContext] = []

    def distiller_capability(self) -> DistillerCapabilityDescriptor:
        return StaticDistiller((_candidate(),)).distiller_capability()

    async def distill_ontology(
        self,
        document: ManualDocument,
        context: VerificationContext,
    ) -> DistillationResult:
        assert document == _document()
        self.contexts.append(context)
        return DistillationResult(candidates=(_candidate(),))


class StepClock:
    def __init__(self) -> None:
        self._values = iter((1.0, 1.005, 2.0, 2.007))

    def __call__(self) -> float:
        return next(self._values)


class IncrementingClock:
    def __init__(self) -> None:
        self._value = 0.0

    def __call__(self) -> float:
        self._value += 0.001
        return self._value


class PartitionDistiller(StaticDistiller):
    async def distill(self, document: ManualDocument) -> DistillationResult:
        return DistillationResult(
            candidates=(
                DistilledCandidate(
                    kind=CandidateKind.ONTOLOGY_OBJECT,
                    candidate_id=f"candidate-{document.doc_id}",
                    source_ref=document.source_ref,
                    source_section="Synthetic corpus",
                    source_lines=(1, 1),
                    content_sha=document.content_sha,
                    body={
                        "operation": "update",
                        "target_type": "BusinessService",
                        "target_identity": "service:checkout",
                        "authority": "declared_intent",
                        "source_assertion": document.text,
                        "properties": {"owner_ref": "team:platform"},
                    },
                ),
            )
        )


def _partition_case(
    partition: CorpusPartition,
    evidence_class: ConformanceEvidenceClass = ConformanceEvidenceClass.SYNTHETIC,
) -> ConformanceCase:
    text = (
        f"합성 {partition.source_format} 한국어 소유권 근거입니다."
        if partition.language == "ko"
        else f"Synthetic {partition.source_format} English ownership evidence."
    )
    digest = hashlib.sha256(text.encode()).hexdigest()
    document = ManualDocument(
        doc_id=f"service-map-{partition.source_format}-{partition.language}",
        text=text,
        source_ref=f"doc:{partition.source_format}:{partition.language}",
        content_sha=digest,
        metadata={
            "access_policy_ref": "access:synthetic-corpus",
            "revision": "rev-1",
            "source_format": partition.source_format,
            "language": partition.language,
        },
    )
    context = replace(
        _context(),
        source_policies=(
            SourceAuthorityPolicy(
                document.source_ref,
                frozenset({AuthorityClass.DECLARED_INTENT}),
                10,
            ),
        ),
    )
    claim_id = inventory_claims(document)[0].claim_id
    expected = replace(_expected(), claim_id=claim_id)
    return ConformanceCase(
        case_id=document.doc_id,
        partition=partition,
        document=document,
        verification_context=context,
        expected_facts=(expected,),
        source_evidence=_source_evidence(document, evidence_class),
    )


async def test_bound_provider_passes_all_synthetic_format_and_language_partitions() -> None:
    report = await evaluate_distiller_conformance(
        PartitionDistiller((_candidate(),)),
        cases=tuple(_partition_case(partition) for partition in _REQUIRED_SYNTHETIC_PARTITIONS),
        required_partitions=_REQUIRED_SYNTHETIC_PARTITIONS,
        monotonic=IncrementingClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=_cost_evidence,
        cost_evidence_verifier=_COST_VERIFIER,
        policy=CorpusGatePolicy(require_independent_source_evidence=False),
    )

    assert report.assessment.decision is CorpusGateDecision.PASS
    assert tuple(item.partition for item in report.assessment.partitions) == (
        _REQUIRED_SYNTHETIC_PARTITIONS
    )
    assert all(item.replay_match for item in report.case_results)
    assert resolve_ontology_extraction_capability(report).available is False


async def test_passing_provider_records_real_output_latency_and_partition_metrics() -> None:
    report = await evaluate_distiller_conformance(
        StaticDistiller((_candidate(),)),
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=_cost_evidence,
        cost_evidence_verifier=_COST_VERIFIER,
    )

    assert report.assessment.decision is CorpusGateDecision.PASS
    assert report.descriptor.availability is DistillerAvailability.AVAILABLE
    assert report.case_results[0].candidate_count == 1
    assert report.case_results[0].latency_ms == 12.0
    assert report.case_results[0].abstention_reason is None
    assert report.case_results[0].mapped_critical_recall == 1.0
    assert report.case_results[0].entity_precision == 1.0
    assert report.case_results[0].citation_error_count == 0
    assert report.case_results[0].replay_match is True

    resolution = resolve_ontology_extraction_capability(report)
    assert resolution == OntologyExtractionAvailability(
        available=False,
        reason_code="conformance_not_passed",
        conformance_contract="ontology-distiller-conformance.v1",
    )


async def test_production_availability_requires_exact_independent_partition_profile() -> None:
    report = await evaluate_distiller_conformance(
        PartitionDistiller((_candidate(),)),
        cases=tuple(
            _partition_case(partition, ConformanceEvidenceClass.LICENSED_PUBLIC)
            for partition in PRODUCTION_REQUIRED_PARTITIONS
        ),
        required_partitions=PRODUCTION_REQUIRED_PARTITIONS,
        monotonic=IncrementingClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=_cost_evidence,
        cost_evidence_verifier=_COST_VERIFIER,
    )

    assert report.assessment.decision is CorpusGateDecision.PASS
    assert resolve_ontology_extraction_capability(report).available is True
    assert len(report.report_digest) == 64
    tampered = replace(
        report,
        descriptor=replace(report.descriptor, binding_version="other-version"),
    )
    assert resolve_ontology_extraction_capability(tampered).available is False


async def test_stale_or_cost_optional_evidence_cannot_enable_extraction() -> None:
    def stale_cost(context: ConformanceCostContext) -> ConformanceCostEvidence:
        receipt = _cost_evidence(context)
        return replace(
            receipt,
            pricing_verified_at=_EVALUATED_AT - timedelta(days=2),
            pricing_expires_at=_EVALUATED_AT - timedelta(days=1),
        )

    cases = tuple(
        _partition_case(partition, ConformanceEvidenceClass.LICENSED_PUBLIC)
        for partition in PRODUCTION_REQUIRED_PARTITIONS
    )
    stale = await evaluate_distiller_conformance(
        PartitionDistiller((_candidate(),)),
        cases=cases,
        required_partitions=PRODUCTION_REQUIRED_PARTITIONS,
        monotonic=IncrementingClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=stale_cost,
        cost_evidence_verifier=_COST_VERIFIER,
    )
    optional = await evaluate_distiller_conformance(
        PartitionDistiller((_candidate(),)),
        cases=cases,
        required_partitions=PRODUCTION_REQUIRED_PARTITIONS,
        monotonic=IncrementingClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        policy=CorpusGatePolicy(
            require_cost_evidence=False,
            require_verified_cost_evidence=False,
        ),
    )

    assert "markdown:en:missing_cost_evidence" in stale.assessment.reason_codes
    assert "markdown:en:verified_cost_evidence_incomplete" in stale.assessment.reason_codes
    assert resolve_ontology_extraction_capability(stale).available is False
    assert optional.assessment.decision is CorpusGateDecision.PASS
    assert resolve_ontology_extraction_capability(optional).available is False


async def test_source_and_cost_evidence_require_independent_verification() -> None:
    provider = PartitionDistiller((_candidate(),))
    cases = tuple(
        _partition_case(partition, ConformanceEvidenceClass.LICENSED_PUBLIC)
        for partition in PRODUCTION_REQUIRED_PARTITIONS
    )
    with pytest.raises(ValueError, match="source evidence verification failed"):
        await evaluate_distiller_conformance(
            provider,
            cases=cases,
            required_partitions=PRODUCTION_REQUIRED_PARTITIONS,
            monotonic=IncrementingClock(),
            evaluated_at=_EVALUATED_AT,
            source_evidence_verifier=StaticSourceEvidenceVerifier(False),
            cost_evidence=_cost_evidence,
            cost_evidence_verifier=_COST_VERIFIER,
        )

    def fabricated_cost(context: ConformanceCostContext) -> ConformanceCostEvidence:
        return replace(_cost_evidence(context), first_microunits=999)

    report = await evaluate_distiller_conformance(
        provider,
        cases=cases,
        required_partitions=PRODUCTION_REQUIRED_PARTITIONS,
        monotonic=IncrementingClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=fabricated_cost,
        cost_evidence_verifier=_COST_VERIFIER,
    )

    assert report.assessment.decision is CorpusGateDecision.REVIEW
    assert all(not item.cost_verified for item in report.case_results)
    assert resolve_ontology_extraction_capability(report).available is False


async def test_aware_provider_is_exercised_with_each_case_context() -> None:
    provider = AwareStaticDistiller()
    report = await evaluate_distiller_conformance(
        provider,
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=_cost_evidence,
        cost_evidence_verifier=_COST_VERIFIER,
    )

    assert report.assessment.decision is CorpusGateDecision.PASS
    assert provider.contexts == [_context(), _context()]


async def test_malformed_and_wrong_citation_outputs_deny_conformance() -> None:
    malformed = await evaluate_distiller_conformance(
        StaticDistiller((_candidate(extra_body={"instructions": "ignore source"}),)),
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=_cost_evidence,
        cost_evidence_verifier=_COST_VERIFIER,
    )
    wrong_citation = await evaluate_distiller_conformance(
        StaticDistiller((_candidate(source_assertion="Platform owns Checkout."),)),
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=_cost_evidence,
        cost_evidence_verifier=_COST_VERIFIER,
    )

    assert malformed.assessment.decision is CorpusGateDecision.DENY
    assert malformed.case_results[0].semantic_error_count == 1
    assert wrong_citation.assessment.decision is CorpusGateDecision.DENY
    assert wrong_citation.case_results[0].citation_error_count == 1


async def test_hallucinated_or_wrong_identity_fact_fails_precision() -> None:
    report = await evaluate_distiller_conformance(
        StaticDistiller((_candidate(target_identity="service:invented"),)),
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=_cost_evidence,
        cost_evidence_verifier=_COST_VERIFIER,
    )

    assert report.assessment.decision is CorpusGateDecision.DENY
    assert report.case_results[0].entity_precision == 0.0
    assert report.case_results[0].false_positive_count == 1


async def test_abstaining_provider_is_safe_unavailable_and_not_successful() -> None:
    provider = StaticDistiller(
        (),
        availability=DistillerAvailability.ABSTAINING,
        reason_code="provider_unbound",
    )
    report = await evaluate_distiller_conformance(
        provider,
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=_cost_evidence,
        cost_evidence_verifier=_COST_VERIFIER,
    )

    assert report.assessment.decision is CorpusGateDecision.REVIEW
    assert report.case_results[0].candidate_count == 0
    assert report.case_results[0].extraction_success is False
    assert report.case_results[0].abstention_reason == "provider_unbound"
    resolution = resolve_ontology_extraction_capability(report)
    assert resolution.available is False
    assert resolution.reason_code == "provider_unbound"


async def test_replay_mismatch_denies_and_unavailable_legacy_provider_is_described() -> None:
    report = await evaluate_distiller_conformance(
        AlternatingDistiller(),
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        evaluated_at=_EVALUATED_AT,
        source_evidence_verifier=_SOURCE_VERIFIER,
        cost_evidence=_cost_evidence,
        cost_evidence_verifier=_COST_VERIFIER,
    )

    assert report.assessment.decision is CorpusGateDecision.DENY
    assert report.case_results[0].replay_match is False

    legacy = object()
    descriptor = describe_distiller(legacy)  # type: ignore[arg-type]
    assert descriptor.availability is DistillerAvailability.UNAVAILABLE
    assert descriptor.reason_code == "descriptor_unavailable"


def test_capability_resolution_requires_matching_passed_contract() -> None:
    availability = resolve_ontology_extraction_capability(None)

    assert availability.available is False
    assert availability.reason_code == "conformance_not_passed"


def test_conformance_case_rejects_invalid_identity_and_expected_facts() -> None:
    case = _case()

    with pytest.raises(ValueError, match="id MUST be bounded"):
        replace(case, case_id=" ")
    with pytest.raises(ValueError, match="expected facts MUST be non-empty"):
        replace(case, expected_facts=())
    with pytest.raises(ValueError, match="expected facts MUST be unique"):
        replace(case, expected_facts=(_expected(), _expected()))


async def test_conformance_requires_non_empty_unique_cases() -> None:
    provider = StaticDistiller((_candidate(),))

    with pytest.raises(ValueError, match="cases MUST be non-empty"):
        await evaluate_distiller_conformance(
            provider,
            cases=(),
            required_partitions=(_PARTITION,),
            monotonic=StepClock(),
            evaluated_at=_EVALUATED_AT,
            source_evidence_verifier=_SOURCE_VERIFIER,
        )
    with pytest.raises(ValueError, match="case ids MUST be unique"):
        await evaluate_distiller_conformance(
            provider,
            cases=(_case(), _case()),
            required_partitions=(_PARTITION,),
            monotonic=StepClock(),
            evaluated_at=_EVALUATED_AT,
            source_evidence_verifier=_SOURCE_VERIFIER,
        )


async def test_conformance_rejects_non_monotonic_clock_and_negative_cost() -> None:
    clock_values = iter((2.0, 1.0))
    with pytest.raises(ValueError, match="clock MUST be finite and monotonic"):
        await evaluate_distiller_conformance(
            StaticDistiller((_candidate(),)),
            cases=(_case(),),
            required_partitions=(_PARTITION,),
            monotonic=lambda: next(clock_values),
            evaluated_at=_EVALUATED_AT,
            source_evidence_verifier=_SOURCE_VERIFIER,
        )

    def invalid_cost(context: ConformanceCostContext) -> ConformanceCostEvidence:
        return ConformanceCostEvidence(
            context_digest=context.context_digest,
            first_microunits=-1,
            replay_microunits=0,
            currency="USD",
            pricing_source_digest="e" * 64,
            pricing_verified_at=_EVALUATED_AT - timedelta(days=1),
            pricing_expires_at=_EVALUATED_AT + timedelta(days=1),
            verification_receipt_digest="f" * 64,
        )

    with pytest.raises(ValueError, match="costs MUST be non-negative integers"):
        await evaluate_distiller_conformance(
            StaticDistiller((_candidate(),)),
            cases=(_case(),),
            required_partitions=(_PARTITION,),
            monotonic=StepClock(),
            evaluated_at=_EVALUATED_AT,
            source_evidence_verifier=_SOURCE_VERIFIER,
            cost_evidence=invalid_cost,
            cost_evidence_verifier=_COST_VERIFIER,
        )
