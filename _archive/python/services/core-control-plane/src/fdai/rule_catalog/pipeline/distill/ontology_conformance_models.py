"""Evidence and report contracts for ontology distiller conformance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from fdai.rule_catalog.pipeline.distill.ontology_corpus_gate import (
    CorpusGateAssessment,
    CorpusPartition,
)
from fdai.rule_catalog.pipeline.distill.ontology_evaluation import ExpectedOntologyFact
from fdai.rule_catalog.pipeline.distill.ontology_models import OntologyTargetKind, stable_digest
from fdai.rule_catalog.pipeline.distill.ontology_verify import VerificationContext
from fdai.shared.providers.distiller import (
    DistillationResult,
    DistillerCapabilityDescriptor,
    ManualDocument,
)

CONFORMANCE_CONTRACT = "ontology-distiller-conformance.v1"
PRODUCTION_REQUIRED_PARTITIONS = (
    CorpusPartition("markdown", "en"),
    CorpusPartition("sgml", "en"),
    CorpusPartition("pdf", "en"),
    CorpusPartition("ooxml", "en"),
    CorpusPartition("pdf", "ko"),
    CorpusPartition("ooxml", "ko"),
    CorpusPartition("ocr", "ko"),
)


class ConformanceEvidenceClass(StrEnum):
    """Source independence class for one corpus case."""

    SYNTHETIC = "synthetic"
    LICENSED_PUBLIC = "licensed_public"
    GOVERNED_DEPLOYMENT = "governed_deployment"


@dataclass(frozen=True, slots=True)
class ConformanceSourceEvidence:
    """Content-free provenance proving how one corpus source was admitted."""

    evidence_class: ConformanceEvidenceClass
    source_digest: str
    manifest_digest: str
    parser_receipt_digest: str
    license_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_class, ConformanceEvidenceClass):
            raise ValueError("conformance evidence class is invalid")
        for value in (
            self.source_digest,
            self.manifest_digest,
            self.parser_receipt_digest,
        ):
            require_digest(value, "conformance source evidence")
        if self.evidence_class is ConformanceEvidenceClass.LICENSED_PUBLIC:
            if self.license_digest is None:
                raise ValueError("licensed public conformance evidence requires a license digest")
            require_digest(self.license_digest, "conformance license")
        elif self.license_digest is not None:
            require_digest(self.license_digest, "conformance license")

    @property
    def independently_authored(self) -> bool:
        return self.evidence_class is not ConformanceEvidenceClass.SYNTHETIC

    @property
    def content_digest(self) -> str:
        return stable_digest(
            {
                "evidence_class": self.evidence_class.value,
                "license_digest": self.license_digest,
                "manifest_digest": self.manifest_digest,
                "parser_receipt_digest": self.parser_receipt_digest,
                "source_digest": self.source_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class ConformanceCostContext:
    """Exact two-run context that a pricing verifier must attest."""

    case_id: str
    binding_digest: str
    source_digest: str
    first_package_digest: str
    replay_package_digest: str
    usage_digest: str
    first_result: DistillationResult = field(compare=False, repr=False)
    replay_result: DistillationResult = field(compare=False, repr=False)

    @property
    def context_digest(self) -> str:
        return stable_digest(
            {
                "binding_digest": self.binding_digest,
                "case_id": self.case_id,
                "first_package_digest": self.first_package_digest,
                "replay_package_digest": self.replay_package_digest,
                "source_digest": self.source_digest,
                "usage_digest": self.usage_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class ConformanceCostEvidence:
    """Verified pricing evidence for both conformance invocations of one case."""

    context_digest: str
    first_microunits: int
    replay_microunits: int
    currency: str
    pricing_source_digest: str
    pricing_verified_at: datetime
    pricing_expires_at: datetime
    verification_receipt_digest: str

    def __post_init__(self) -> None:
        for value in (
            self.context_digest,
            self.pricing_source_digest,
            self.verification_receipt_digest,
        ):
            require_digest(value, "conformance cost evidence")
        if any(
            type(value) is not int or value < 0
            for value in (self.first_microunits, self.replay_microunits)
        ):
            raise ValueError("conformance costs MUST be non-negative integers")
        if (
            not self.currency.isascii()
            or not self.currency.isalpha()
            or not self.currency.isupper()
            or len(self.currency) != 3
        ):
            raise ValueError("conformance cost currency MUST be an uppercase three-letter code")
        for timestamp in (self.pricing_verified_at, self.pricing_expires_at):
            if timestamp.tzinfo is None:
                raise ValueError("conformance pricing times MUST be timezone-aware")
        if self.pricing_expires_at <= self.pricing_verified_at:
            raise ValueError("conformance pricing expiry MUST follow verification")

    def valid_for(self, context: ConformanceCostContext, evaluated_at: datetime) -> bool:
        return (
            self.context_digest == context.context_digest
            and self.pricing_verified_at.astimezone(UTC)
            <= evaluated_at.astimezone(UTC)
            < self.pricing_expires_at.astimezone(UTC)
        )

    @property
    def total_microunits(self) -> int:
        return self.first_microunits + self.replay_microunits

    @property
    def content_digest(self) -> str:
        return stable_digest(
            {
                "context_digest": self.context_digest,
                "currency": self.currency,
                "first_microunits": self.first_microunits,
                "pricing_expires_at": self.pricing_expires_at.astimezone(UTC).isoformat(),
                "pricing_source_digest": self.pricing_source_digest,
                "pricing_verified_at": self.pricing_verified_at.astimezone(UTC).isoformat(),
                "replay_microunits": self.replay_microunits,
                "verification_receipt_digest": self.verification_receipt_digest,
            }
        )


class ConformanceCostEvidenceProvider(Protocol):
    """Supply independently sourced pricing evidence for measured usage."""

    def __call__(self, context: ConformanceCostContext) -> ConformanceCostEvidence: ...


class ConformanceCostEvidenceVerifier(Protocol):
    """Independently authenticate pricing provenance and usage arithmetic."""

    def verify(
        self,
        context: ConformanceCostContext,
        evidence: ConformanceCostEvidence,
    ) -> bool: ...


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
    source_evidence: ConformanceSourceEvidence

    def __post_init__(self) -> None:
        if not self.case_id.strip() or len(self.case_id) > 128:
            raise ValueError("conformance case id MUST be bounded and non-empty")
        if not self.expected_facts:
            raise ValueError("conformance case expected facts MUST be non-empty")
        identities = [(item.fact_key, item.value_digest) for item in self.expected_facts]
        if len(identities) != len(set(identities)):
            raise ValueError("conformance expected facts MUST be unique")
        if self.source_evidence.source_digest != self.document.content_sha:
            raise ValueError("conformance source evidence MUST match the document digest")


class ConformanceSourceEvidenceVerifier(Protocol):
    """Authenticate source, manifest, parser, and license receipt bindings."""

    def verify(self, case: ConformanceCase) -> bool: ...


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
    independently_authored: bool
    cost_verified: bool
    source_evidence_digest: str
    cost_evidence_digest: str | None
    cost_verification_receipt_digest: str | None
    cost_currency: str | None

    @property
    def mapped_critical_recall(self) -> float:
        return ratio_or_one(
            self.mapped_critical_claim_count,
            self.expected_critical_claim_count,
        )

    @property
    def entity_precision(self) -> float:
        return ratio_or_one(self.correct_entity_count, self.predicted_entity_count)

    @property
    def link_precision(self) -> float:
        return ratio_or_one(self.correct_link_count, self.predicted_link_count)


@dataclass(frozen=True, slots=True)
class DistillerConformanceReport:
    descriptor: DistillerCapabilityDescriptor
    case_results: tuple[ConformanceCaseResult, ...]
    assessment: CorpusGateAssessment
    required_partitions: tuple[CorpusPartition, ...]
    descriptor_digest: str

    @property
    def report_digest(self) -> str:
        policy = self.assessment.policy
        return stable_digest(
            {
                "assessment": {
                    "decision": self.assessment.decision.value,
                    "reason_codes": self.assessment.reason_codes,
                    "policy": {
                        "max_citation_error_count": policy.max_citation_error_count,
                        "max_citation_error_rate": policy.max_citation_error_rate,
                        "min_detected_claim_accounting": (policy.min_detected_claim_accounting),
                        "min_entity_precision": policy.min_entity_precision,
                        "min_link_precision": policy.min_link_precision,
                        "min_mapped_critical_recall": policy.min_mapped_critical_recall,
                        "require_cost_evidence": policy.require_cost_evidence,
                        "require_independent_source_evidence": (
                            policy.require_independent_source_evidence
                        ),
                        "require_latency_evidence": policy.require_latency_evidence,
                        "require_verified_cost_evidence": (policy.require_verified_cost_evidence),
                    },
                },
                "cases": [
                    {
                        "abstention_reason": item.abstention_reason,
                        "accounted_detected_claim_count": (item.accounted_detected_claim_count),
                        "case_id": item.case_id,
                        "candidate_count": item.candidate_count,
                        "citation_count": item.citation_count,
                        "citation_error_count": item.citation_error_count,
                        "correct_entity_count": item.correct_entity_count,
                        "correct_link_count": item.correct_link_count,
                        "cost_microunits": item.cost_microunits,
                        "cost_currency": item.cost_currency,
                        "cost_verification_receipt_digest": (item.cost_verification_receipt_digest),
                        "cost_verified": item.cost_verified,
                        "detected_claim_count": item.detected_claim_count,
                        "extraction_success": item.extraction_success,
                        "expected_critical_claim_count": (item.expected_critical_claim_count),
                        "false_negative_count": item.false_negative_count,
                        "false_positive_count": item.false_positive_count,
                        "independently_authored": item.independently_authored,
                        "latency_ms": item.latency_ms,
                        "mapped_critical_claim_count": item.mapped_critical_claim_count,
                        "partition": item.partition.key,
                        "predicted_entity_count": item.predicted_entity_count,
                        "predicted_link_count": item.predicted_link_count,
                        "replay_match": item.replay_match,
                        "semantic_error_count": item.semantic_error_count,
                        "source_evidence_digest": item.source_evidence_digest,
                        "cost_evidence_digest": item.cost_evidence_digest,
                    }
                    for item in self.case_results
                ],
                "descriptor": {
                    "availability": self.descriptor.availability.value,
                    "binding_id": self.descriptor.binding_id,
                    "binding_version": self.descriptor.binding_version,
                    "contract_version": self.descriptor.contract_version,
                    "reason_code": self.descriptor.reason_code,
                },
                "descriptor_digest": self.descriptor_digest,
                "required_partitions": [item.key for item in self.required_partitions],
            }
        )


@dataclass(frozen=True, slots=True)
class OntologyExtractionAvailability:
    available: bool
    reason_code: str | None
    conformance_contract: str


def distiller_descriptor_digest(descriptor: DistillerCapabilityDescriptor) -> str:
    return stable_digest(
        {
            "availability": descriptor.availability.value,
            "binding_id": descriptor.binding_id,
            "binding_version": descriptor.binding_version,
            "contract_version": descriptor.contract_version,
            "reason_code": descriptor.reason_code,
        }
    )


def require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} MUST be a lowercase SHA-256 digest")


def ratio_or_one(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


__all__ = [
    "CONFORMANCE_CONTRACT",
    "PRODUCTION_REQUIRED_PARTITIONS",
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
    "distiller_descriptor_digest",
]
