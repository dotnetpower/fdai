"""Versioned bilingual golden questions and deterministic certification."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum

from fdai.core.conversation.question_campaign import QuestionCampaignHardZeroCounters
from fdai.core.conversation.question_perspectives import QuestionEvidencePosture

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_SEMVER_PATTERN = re.compile(r"[1-9][0-9]*\.[0-9]+\.[0-9]+")
_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,255}")
_CATALOG_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,127}")
_ALLOWED_DISPOSITIONS = frozenset(
    {"answered", "clarification", "held", "unsupported", "action_draft"}
)
_LOCALES = frozenset({"en", "ko"})
_TEMPORAL_SCOPES = frozenset({"current", "historical", "none", "windowed"})
_RUNTIME_CONTEXTS = frozenset(
    {"explicit_target_required", "incident_binding", "none", "server_scope"}
)
_VARIATION_KINDS = frozenset(
    {
        "audit_oriented",
        "concise",
        "contrastive",
        "direct",
        "evidence_first",
        "investigative",
        "operator_colloquial",
        "uncertainty_aware",
    }
)


class GoldenAuthorityPosture(StrEnum):
    """Maximum authority a golden answer may claim."""

    READ_ONLY = "read_only"
    DRAFT_ONLY = "draft_only"


@dataclass(frozen=True, slots=True)
class GoldenSemanticFrame:
    """Exact meaning expected from wording without fixing answer text."""

    operation: str
    subject: str
    measure_concepts: tuple[str, ...]
    output_shape: str | None
    temporal_scope: str = "none"

    def __post_init__(self) -> None:
        for name, value in (("operation", self.operation), ("subject", self.subject)):
            if _IDENTIFIER_PATTERN.fullmatch(value) is None:
                raise ValueError(f"golden semantic frame {name} is invalid")
        if (
            self.output_shape is not None
            and _IDENTIFIER_PATTERN.fullmatch(self.output_shape) is None
        ):
            raise ValueError("golden semantic frame output_shape is invalid")
        if self.temporal_scope not in _TEMPORAL_SCOPES:
            raise ValueError("golden semantic frame temporal_scope is invalid")
        _require_ordered_identifiers("golden semantic frame measures", self.measure_concepts)

    @property
    def digest(self) -> str:
        """Return the canonical frame identity used by certification."""

        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class GoldenOntologyPathStep:
    """One directed declaration step expected in a golden semantic plan."""

    from_type: str
    link_type: str
    direction: str
    to_type: str

    def __post_init__(self) -> None:
        _require_catalog_names("golden ontology step types", (self.from_type, self.to_type))
        if _IDENTIFIER_PATTERN.fullmatch(self.link_type) is None:
            raise ValueError("golden ontology step link type is invalid")
        if self.direction not in {"incoming", "outgoing"}:
            raise ValueError("golden ontology step direction is invalid")


@dataclass(frozen=True, slots=True)
class GoldenOntologyPath:
    """One bounded ordered ontology path expected by a golden question."""

    path_id: str
    steps: tuple[GoldenOntologyPathStep, ...]

    def __post_init__(self) -> None:
        if _IDENTIFIER_PATTERN.fullmatch(self.path_id) is None:
            raise ValueError("golden ontology path id is invalid")
        if not 1 <= len(self.steps) <= 5:
            raise ValueError("golden ontology path MUST contain 1..5 steps")
        if any(
            previous.to_type != current.from_type
            for previous, current in zip(self.steps, self.steps[1:], strict=False)
        ):
            raise ValueError("golden ontology path steps MUST be contiguous")


@dataclass(frozen=True, slots=True)
class GoldenOntologyExpectation:
    """Typed anchor, target, path, and traversal bounds for one golden pair."""

    anchor_type: str
    target_types: tuple[str, ...]
    paths: tuple[GoldenOntologyPath, ...]
    min_traversal_depth: int
    max_traversal_depth: int

    def __post_init__(self) -> None:
        _require_catalog_names("golden ontology anchor", (self.anchor_type,))
        _require_catalog_names(
            "golden ontology targets", self.target_types, ordered=True, required=True
        )
        if self.paths != tuple(sorted(self.paths, key=lambda item: item.path_id)):
            raise ValueError("golden ontology paths MUST be ordered")
        if len({item.path_id for item in self.paths}) != len(self.paths):
            raise ValueError("golden ontology path ids MUST be unique")
        if not 0 <= self.min_traversal_depth <= self.max_traversal_depth <= 5:
            raise ValueError("golden ontology traversal bounds are invalid")
        depths = tuple(len(item.steps) for item in self.paths)
        if depths and (
            min(depths) != self.min_traversal_depth or max(depths) != self.max_traversal_depth
        ):
            raise ValueError("golden ontology path depths conflict with traversal bounds")
        if not depths and (self.min_traversal_depth != 0 or self.max_traversal_depth != 0):
            raise ValueError("empty golden ontology paths require zero traversal bounds")


@dataclass(frozen=True, slots=True)
class GoldenQuestionCase:
    """One locale-specific wording bound to semantic and safety expectations."""

    case_id: str
    semantic_pair_id: str
    locale: str
    question: str
    expected_frame: GoldenSemanticFrame
    required_capabilities: tuple[str, ...]
    allowed_dispositions: tuple[str, ...]
    expected_disposition: str
    required_facts: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    evidence_posture: QuestionEvidencePosture
    authority_posture: GoldenAuthorityPosture
    required_object_types: tuple[str, ...] = ()
    required_link_types: tuple[str, ...] = ()
    required_function_types: tuple[str, ...] = ()
    expected_ontology: GoldenOntologyExpectation | None = None
    required_limitations: tuple[str, ...] = ()
    runtime_context: str = "none"
    variation_kind: str = "direct"

    def __post_init__(self) -> None:
        for name, value in (
            ("case id", self.case_id),
            ("semantic pair id", self.semantic_pair_id),
        ):
            if _IDENTIFIER_PATTERN.fullmatch(value) is None:
                raise ValueError(f"golden question {name} is invalid")
        if self.locale not in _LOCALES:
            raise ValueError("golden question locale MUST be en or ko")
        if not 8 <= len(self.question.strip()) <= 400:
            raise ValueError("golden question text MUST contain 8..400 characters")
        _require_ordered_identifiers(
            "golden required capabilities", self.required_capabilities, required=True
        )
        if (
            not self.allowed_dispositions
            or self.allowed_dispositions != tuple(sorted(set(self.allowed_dispositions)))
            or not set(self.allowed_dispositions) <= _ALLOWED_DISPOSITIONS
        ):
            raise ValueError("golden allowed dispositions are invalid")
        if (
            self.expected_disposition not in _ALLOWED_DISPOSITIONS
            or self.expected_disposition not in self.allowed_dispositions
        ):
            raise ValueError("golden expected disposition is invalid")
        _require_ordered_identifiers("golden required facts", self.required_facts)
        _require_ordered_identifiers("golden forbidden claims", self.forbidden_claims)
        _require_catalog_names(
            "golden required object types", self.required_object_types, ordered=True
        )
        _require_ordered_identifiers("golden required link types", self.required_link_types)
        _require_ordered_identifiers("golden required function types", self.required_function_types)
        _require_ordered_identifiers("golden required limitations", self.required_limitations)
        if self.runtime_context not in _RUNTIME_CONTEXTS:
            raise ValueError("golden runtime context is invalid")
        if self.variation_kind not in _VARIATION_KINDS:
            raise ValueError("golden variation kind is invalid")
        if not isinstance(self.evidence_posture, QuestionEvidencePosture):
            raise ValueError("golden evidence posture MUST be a declared enum value")
        if not isinstance(self.authority_posture, GoldenAuthorityPosture):
            raise ValueError("golden authority posture MUST be a declared enum value")

    @property
    def expectation_digest(self) -> str:
        """Return the locale-neutral expected behavior identity."""

        return _digest(
            {
                "expected_frame": asdict(self.expected_frame),
                "required_capabilities": self.required_capabilities,
                "allowed_dispositions": self.allowed_dispositions,
                "expected_disposition": self.expected_disposition,
                "required_facts": self.required_facts,
                "forbidden_claims": self.forbidden_claims,
                "required_object_types": self.required_object_types,
                "required_link_types": self.required_link_types,
                "required_function_types": self.required_function_types,
                "expected_ontology": (
                    asdict(self.expected_ontology) if self.expected_ontology is not None else None
                ),
                "required_limitations": self.required_limitations,
                "runtime_context": self.runtime_context,
                "variation_kind": self.variation_kind,
                "evidence_posture": self.evidence_posture.value,
                "authority_posture": self.authority_posture.value,
            }
        )


@dataclass(frozen=True, slots=True)
class GoldenQuestionCorpus:
    """Content-addressed immutable bilingual semantic corpus."""

    schema_version: str
    corpus_version: str
    cases: tuple[GoldenQuestionCase, ...]
    corpus_digest: str
    source_digest: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0" or _SEMVER_PATTERN.fullmatch(self.corpus_version) is None:
            raise ValueError("golden corpus versions are invalid")
        if not self.cases or self.cases != tuple(sorted(self.cases, key=lambda item: item.case_id)):
            raise ValueError("golden cases MUST be non-empty and ordered")
        if len({item.case_id for item in self.cases}) != len(self.cases):
            raise ValueError("golden case ids MUST be unique")
        _require_bilingual_pairs(self.cases)
        if self.source_digest is not None:
            _require_digest("golden corpus source", self.source_digest)
        _require_digest("golden corpus", self.corpus_digest)
        if self.corpus_digest != _corpus_digest(self):
            raise ValueError("golden corpus digest does not match content")


@dataclass(frozen=True, slots=True)
class GoldenCaseCertification:
    """Content-free deterministic gate results for one golden case."""

    case_id: str
    semantic_frame_matched: bool
    capabilities_exact: bool
    disposition_allowed: bool
    required_facts_present: bool
    forbidden_claims_absent: bool
    evidence_posture_matched: bool
    authority_posture_matched: bool
    transport_passed: bool
    assessment_digest: str
    hard_zero: QuestionCampaignHardZeroCounters = QuestionCampaignHardZeroCounters()

    def __post_init__(self) -> None:
        if _IDENTIFIER_PATTERN.fullmatch(self.case_id) is None:
            raise ValueError("golden certification case id is invalid")
        _require_digest("golden assessment", self.assessment_digest)

    @property
    def passed(self) -> bool:
        """Return true only when every independent deterministic gate passes."""

        return all(
            (
                self.semantic_frame_matched,
                self.capabilities_exact,
                self.disposition_allowed,
                self.required_facts_present,
                self.forbidden_claims_absent,
                self.evidence_posture_matched,
                self.authority_posture_matched,
                self.transport_passed,
                self.hard_zero.total == 0,
            )
        )


@dataclass(frozen=True, slots=True)
class GoldenCertificationReceipt:
    """Exact-corpus release gate that precedes every generated campaign."""

    corpus_digest: str
    ontology_release_digest: str
    principal_manifest_digests: tuple[str, ...]
    case_count: int
    passed_case_count: int
    passed: bool
    reason: str
    case_assessment_digests: tuple[str, ...]
    hard_zero: QuestionCampaignHardZeroCounters
    receipt_digest: str

    def __post_init__(self) -> None:
        _require_digest("golden certification corpus", self.corpus_digest)
        _require_digest("golden certification release", self.ontology_release_digest)
        _require_ordered_digests(
            "golden certification principal manifests",
            self.principal_manifest_digests,
        )
        if not 0 <= self.passed_case_count <= self.case_count:
            raise ValueError("golden certification case counts are inconsistent")
        if self.passed != (self.passed_case_count == self.case_count):
            raise ValueError("golden certification verdict conflicts with case counts")
        expected_reason = "golden_certification_passed" if self.passed else "golden_case_failed"
        if self.reason != expected_reason:
            raise ValueError("golden certification reason conflicts with verdict")
        if len(self.case_assessment_digests) != self.case_count:
            raise ValueError("golden certification assessment count is inconsistent")
        for digest in self.case_assessment_digests:
            _require_digest("golden certification assessment", digest)
        if self.receipt_digest != _digest(_golden_certification_body(self)):
            raise ValueError("golden certification receipt digest does not match content")


def build_golden_corpus(
    *,
    corpus_version: str,
    cases: Sequence[GoldenQuestionCase],
    source_digest: str | None = None,
) -> GoldenQuestionCorpus:
    """Build a canonical corpus and reject locale or expectation drift."""

    ordered_cases = tuple(sorted(cases, key=lambda item: item.case_id))
    provisional = GoldenQuestionCorpus.__new__(GoldenQuestionCorpus)
    object.__setattr__(provisional, "schema_version", "1.0.0")
    object.__setattr__(provisional, "corpus_version", corpus_version)
    object.__setattr__(provisional, "cases", ordered_cases)
    object.__setattr__(provisional, "source_digest", source_digest)
    object.__setattr__(provisional, "corpus_digest", _corpus_digest(provisional))
    return GoldenQuestionCorpus(
        schema_version=provisional.schema_version,
        corpus_version=provisional.corpus_version,
        cases=provisional.cases,
        corpus_digest=provisional.corpus_digest,
        source_digest=provisional.source_digest,
    )


def evaluate_golden_certification(
    *,
    corpus: GoldenQuestionCorpus,
    ontology_release_digest: str,
    principal_manifest_digests: Sequence[str],
    results: Sequence[GoldenCaseCertification],
) -> GoldenCertificationReceipt:
    """Require exact case accounting and every deterministic gate before generation."""

    _require_digest("golden certification release", ontology_release_digest)
    ordered_manifests = tuple(sorted(set(principal_manifest_digests)))
    _require_ordered_digests("golden certification principal manifests", ordered_manifests)
    expected = tuple(item.case_id for item in corpus.cases)
    observed = tuple(sorted(item.case_id for item in results))
    if observed != expected or len(observed) != len(set(observed)):
        raise ValueError("golden certification results MUST exactly cover the corpus")
    passed_count = sum(item.passed for item in results)
    passed = passed_count == len(corpus.cases)
    hard_zero = _sum_hard_zero(results)
    assessment_digests = tuple(
        item.assessment_digest for item in sorted(results, key=lambda item: item.case_id)
    )
    provisional = GoldenCertificationReceipt.__new__(GoldenCertificationReceipt)
    for name, value in {
        "corpus_digest": corpus.corpus_digest,
        "ontology_release_digest": ontology_release_digest,
        "principal_manifest_digests": ordered_manifests,
        "case_count": len(corpus.cases),
        "passed_case_count": passed_count,
        "passed": passed,
        "reason": "golden_certification_passed" if passed else "golden_case_failed",
        "case_assessment_digests": assessment_digests,
        "hard_zero": hard_zero,
    }.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(
        provisional,
        "receipt_digest",
        _digest(_golden_certification_body(provisional)),
    )
    return GoldenCertificationReceipt(
        **{
            name: getattr(provisional, name)
            for name in GoldenCertificationReceipt.__dataclass_fields__
        }
    )


def _golden_certification_body(receipt: GoldenCertificationReceipt) -> dict[str, object]:
    return {
        "corpus_digest": receipt.corpus_digest,
        "ontology_release_digest": receipt.ontology_release_digest,
        "principal_manifest_digests": receipt.principal_manifest_digests,
        "case_count": receipt.case_count,
        "passed_case_count": receipt.passed_case_count,
        "passed": receipt.passed,
        "reason": receipt.reason,
        "assessment_digests": receipt.case_assessment_digests,
        "hard_zero": asdict(receipt.hard_zero),
    }


def _sum_hard_zero(results: Sequence[GoldenCaseCertification]) -> QuestionCampaignHardZeroCounters:
    names = tuple(asdict(QuestionCampaignHardZeroCounters()))
    return QuestionCampaignHardZeroCounters(
        **{name: sum(getattr(item.hard_zero, name) for item in results) for name in names}
    )


def _require_bilingual_pairs(cases: Sequence[GoldenQuestionCase]) -> None:
    pairs: dict[str, list[GoldenQuestionCase]] = {}
    for case in cases:
        pairs.setdefault(case.semantic_pair_id, []).append(case)
    for pair in pairs.values():
        if {item.locale for item in pair} != _LOCALES or len(pair) != 2:
            raise ValueError("golden semantic pairs MUST contain exactly en and ko")
        if len({item.expectation_digest for item in pair}) != 1:
            raise ValueError("golden bilingual expectations MUST be identical")


def _corpus_digest(corpus: GoldenQuestionCorpus) -> str:
    return _digest(
        {
            "schema_version": corpus.schema_version,
            "corpus_version": corpus.corpus_version,
            "source_digest": corpus.source_digest,
            "cases": [
                {
                    **asdict(case),
                    "evidence_posture": case.evidence_posture.value,
                    "authority_posture": case.authority_posture.value,
                }
                for case in corpus.cases
            ],
        }
    )


def _require_ordered_digests(name: str, values: tuple[str, ...]) -> None:
    if not values or values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be non-empty and ordered")
    for value in values:
        _require_digest(name, value)


def _require_ordered_identifiers(
    name: str, values: tuple[str, ...], *, required: bool = False
) -> None:
    if (required and not values) or values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be ordered and unique")
    if any(_IDENTIFIER_PATTERN.fullmatch(value) is None for value in values):
        raise ValueError(f"{name} contain an invalid identifier")


def _require_catalog_names(
    name: str,
    values: tuple[str, ...],
    *,
    ordered: bool = False,
    required: bool = False,
) -> None:
    if required and not values:
        raise ValueError(f"{name} MUST be non-empty")
    if ordered and values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be ordered and unique")
    if any(_CATALOG_NAME_PATTERN.fullmatch(value) is None for value in values):
        raise ValueError(f"{name} contain an invalid catalog name")


def _require_digest(name: str, value: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a canonical SHA-256 value")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "GoldenAuthorityPosture",
    "GoldenCaseCertification",
    "GoldenCertificationReceipt",
    "GoldenOntologyExpectation",
    "GoldenOntologyPath",
    "GoldenOntologyPathStep",
    "GoldenQuestionCase",
    "GoldenQuestionCorpus",
    "GoldenSemanticFrame",
    "build_golden_corpus",
    "evaluate_golden_certification",
]
