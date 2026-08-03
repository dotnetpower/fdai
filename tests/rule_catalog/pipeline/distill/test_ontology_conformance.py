"""Tests for real Distiller conformance and capability resolution."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from fdai.rule_catalog.pipeline.distill.ontology_claims import inventory_claims
from fdai.rule_catalog.pipeline.distill.ontology_conformance import (
    ConformanceCase,
    ConformanceExpectedFact,
    OntologyExtractionAvailability,
    evaluate_distiller_conformance,
    resolve_ontology_extraction_capability,
)
from fdai.rule_catalog.pipeline.distill.ontology_corpus_gate import (
    CorpusGateDecision,
    CorpusPartition,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import (
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
_TEXT = "Checkout service is owned by Platform team."
_DIGEST = hashlib.sha256(_TEXT.encode()).hexdigest()


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
    claim = inventory_claims(_document())[0]
    return VerificationContext(
        ontology_release="a" * 64,
        current_graph_revision="graph-1",
        object_types=frozenset({"BusinessService"}),
        links=(),
        entities=(EntityRecord("service:checkout", "BusinessService"),),
        source_policies=(
            SourceAuthorityPolicy("doc:service-map", frozenset({claim.authority}), 10),
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
    return ConformanceCase(
        case_id="service-map-en",
        partition=_PARTITION,
        document=_document(),
        verification_context=_context(),
        expected_facts=(_expected(),),
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


class StepClock:
    def __init__(self) -> None:
        self._values = iter((1.0, 1.005, 2.0, 2.007))

    def __call__(self) -> float:
        return next(self._values)


async def test_passing_provider_records_real_output_latency_and_partition_metrics() -> None:
    report = await evaluate_distiller_conformance(
        StaticDistiller((_candidate(),)),
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        cost_microunits=lambda case, result: len(result.candidates) * 10,
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

    resolution = resolve_ontology_extraction_capability(
        report.descriptor,
        report.assessment,
    )
    assert resolution == OntologyExtractionAvailability(
        available=True,
        reason_code=None,
        conformance_contract="ontology-distiller-conformance.v1",
    )


async def test_malformed_and_wrong_citation_outputs_deny_conformance() -> None:
    malformed = await evaluate_distiller_conformance(
        StaticDistiller((_candidate(extra_body={"instructions": "ignore source"}),)),
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        cost_microunits=lambda case, result: 0,
    )
    wrong_citation = await evaluate_distiller_conformance(
        StaticDistiller((_candidate(source_assertion="Platform owns Checkout."),)),
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        cost_microunits=lambda case, result: 0,
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
        cost_microunits=lambda case, result: 0,
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
        cost_microunits=lambda case, result: 0,
    )

    assert report.assessment.decision is CorpusGateDecision.REVIEW
    assert report.case_results[0].candidate_count == 0
    assert report.case_results[0].extraction_success is False
    assert report.case_results[0].abstention_reason == "provider_unbound"
    resolution = resolve_ontology_extraction_capability(
        report.descriptor,
        report.assessment,
    )
    assert resolution.available is False
    assert resolution.reason_code == "provider_unbound"


async def test_replay_mismatch_denies_and_unavailable_legacy_provider_is_described() -> None:
    report = await evaluate_distiller_conformance(
        AlternatingDistiller(),
        cases=(_case(),),
        required_partitions=(_PARTITION,),
        monotonic=StepClock(),
        cost_microunits=lambda case, result: 0,
    )

    assert report.assessment.decision is CorpusGateDecision.DENY
    assert report.case_results[0].replay_match is False

    legacy = object()
    descriptor = describe_distiller(legacy)  # type: ignore[arg-type]
    assert descriptor.availability is DistillerAvailability.UNAVAILABLE
    assert descriptor.reason_code == "descriptor_unavailable"


def test_capability_resolution_requires_matching_passed_contract() -> None:
    descriptor = StaticDistiller((_candidate(),)).distiller_capability()
    mismatched = replace(descriptor, contract_version="ontology-distiller-conformance.v2")
    report_assessment = None

    availability = resolve_ontology_extraction_capability(mismatched, report_assessment)

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
        )
    with pytest.raises(ValueError, match="case ids MUST be unique"):
        await evaluate_distiller_conformance(
            provider,
            cases=(_case(), _case()),
            required_partitions=(_PARTITION,),
            monotonic=StepClock(),
        )


async def test_conformance_rejects_non_monotonic_clock_and_negative_cost() -> None:
    clock_values = iter((2.0, 1.0))
    with pytest.raises(ValueError, match="clock MUST be finite and monotonic"):
        await evaluate_distiller_conformance(
            StaticDistiller((_candidate(),)),
            cases=(_case(),),
            required_partitions=(_PARTITION,),
            monotonic=lambda: next(clock_values),
        )

    with pytest.raises(ValueError, match="cost MUST be a non-negative integer"):
        await evaluate_distiller_conformance(
            StaticDistiller((_candidate(),)),
            cases=(_case(),),
            required_partitions=(_PARTITION,),
            monotonic=StepClock(),
            cost_microunits=lambda case, result: -1,
        )
