"""Offline typed label comparison, not causal inference or operational qualification.

Labels must be supplied independently of runner results. Identity separation records
that assertion; it does not authenticate a reviewer or an evidence source. Evidence
bodies and their time windows remain in the pinned source revisions, not this scorer.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Literal

from fdai_service_contracts.ontology_query import canonical_json, content_digest

MAX_CASES = 128
MAX_RESULTS = 256
MAX_EVIDENCE_REFS = 32
EVALUATION_METHOD: Literal["typed-causal-quality-v1"] = "typed-causal-quality-v1"


class CausalEvaluationDisposition(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNRESOLVED = "unresolved"
    UNAVAILABLE = "unavailable"


class CausalEvaluationProvenance(StrEnum):
    SYNTHETIC = "synthetic"
    LOCAL_FIXTURE = "local_fixture"
    GOVERNED_OPERATIONAL = "governed_operational"


_HOLDS = frozenset(
    {CausalEvaluationDisposition.UNRESOLVED, CausalEvaluationDisposition.UNAVAILABLE}
)


def _text(name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= 256
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(f"{name} MUST be bounded non-empty text without control characters")


def _digest(name: str, value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} MUST be a canonical SHA-256 content digest")


def _case_id(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", value) is None:
        raise ValueError("case_id MUST be a bounded ASCII identifier")


def _outcome(disposition: CausalEvaluationDisposition, cause_ref: str | None) -> None:
    if not isinstance(disposition, CausalEvaluationDisposition):
        raise ValueError("disposition MUST be a CausalEvaluationDisposition")
    if disposition in _HOLDS:
        if cause_ref is not None:
            raise ValueError("held dispositions MUST NOT assert a cause identity")
    elif cause_ref is None:
        raise ValueError("supported or refuted dispositions MUST identify the tested cause")
    else:
        _text("cause_ref", cause_ref)


def _typed_tuple(name: str, values: tuple[object, ...], kind: type, maximum: int) -> None:
    if (
        not isinstance(values, tuple)
        or len(values) > maximum
        or any(type(value) is not kind for value in values)
    ):
        raise ValueError(f"{name} MUST be an immutable typed tuple of at most {maximum} items")


@dataclass(frozen=True, slots=True)
class CausalEvaluationEvidence:
    """One exact allowed citation and the content revision behind it.

    Provenance is declared input, not an admission decision. Even a governed source
    cannot turn this local comparison into deployed qualification or authority.
    """

    ref: str
    source_revision: str
    provenance: CausalEvaluationProvenance

    def __post_init__(self) -> None:
        _text("evidence ref", self.ref)
        _digest("evidence source_revision", self.source_revision)
        if not isinstance(self.provenance, CausalEvaluationProvenance):
            raise ValueError("provenance MUST be a CausalEvaluationProvenance")


@dataclass(frozen=True, slots=True)
class CausalEvaluationCase:
    """An independent label for one pinned evidence frame and exact cause identity."""

    case_id: str
    labeler_id: str
    label_source_revision: str
    label_method: str
    label_provenance: CausalEvaluationProvenance
    expected_disposition: CausalEvaluationDisposition
    expected_cause_ref: str | None
    evidence: tuple[CausalEvaluationEvidence, ...]

    def __post_init__(self) -> None:
        _case_id(self.case_id)
        _text("labeler_id", self.labeler_id)
        _digest("label_source_revision", self.label_source_revision)
        _text("label_method", self.label_method)
        if not isinstance(self.label_provenance, CausalEvaluationProvenance):
            raise ValueError("label_provenance MUST be a CausalEvaluationProvenance")
        _outcome(self.expected_disposition, self.expected_cause_ref)
        _typed_tuple("evidence", self.evidence, CausalEvaluationEvidence, MAX_EVIDENCE_REFS)
        refs = tuple(item.ref for item in self.evidence)
        if len(set(refs)) != len(refs):
            raise ValueError("allowed evidence references MUST be unique within each case")
        if self.expected_disposition not in _HOLDS and not refs:
            raise ValueError("determinate labels MUST have pinned evidence")
        object.__setattr__(
            self, "evidence", tuple(sorted(self.evidence, key=lambda item: item.ref))
        )

    @property
    def allowed_evidence_refs(self) -> tuple[str, ...]:
        return tuple(item.ref for item in self.evidence)


@dataclass(frozen=True, slots=True)
class CausalEvaluationResult:
    """One submitted result; missing results are never converted into holds."""

    case_id: str
    actual_disposition: CausalEvaluationDisposition
    actual_cause_ref: str | None
    cited_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _case_id(self.case_id)
        _outcome(self.actual_disposition, self.actual_cause_ref)
        _typed_tuple("cited_evidence_refs", self.cited_evidence_refs, str, MAX_EVIDENCE_REFS)
        for ref in self.cited_evidence_refs:
            _text("cited evidence ref", ref)
        if len(set(self.cited_evidence_refs)) != len(self.cited_evidence_refs):
            raise ValueError("cited evidence references MUST be unique within each result")
        object.__setattr__(self, "cited_evidence_refs", tuple(sorted(self.cited_evidence_refs)))


@dataclass(frozen=True, slots=True)
class CausalEvaluationMetrics:
    """Counts retain their denominators; absent citation/positive exposure is not 100%.

    Cause claims count SUPPORTED results only; wrong refutations still fail case
    accuracy. Completion requires exactly one result for a registered case, including
    explicit holds. Unknown and duplicate submissions cannot earn case credit.
    """

    denominator: int
    submitted_results: int
    completed_cases: int
    correct_cases: int
    expected_cause_claims: int
    correct_cause_claims: int
    unsupported_cause_claims: int
    justified_holds: int
    unjustified_holds: int
    valid_citations: int
    invalid_citations: int
    uncited_determinate_results: int
    duplicate_results: int
    unknown_results: int
    missing_case_ids: tuple[str, ...]
    duplicate_case_ids: tuple[str, ...]
    unknown_case_ids: tuple[str, ...]

    @property
    def accuracy(self) -> float:
        return self.correct_cases / self.denominator if self.denominator > 0 else 0.0

    @property
    def completion_coverage(self) -> float:
        return self.completed_cases / self.denominator if self.denominator > 0 else 0.0

    @property
    def cause_recall(self) -> float:
        return (
            self.correct_cause_claims / self.expected_cause_claims
            if self.expected_cause_claims > 0
            else 0.0
        )

    @property
    def citation_validity(self) -> float | None:
        count = self.valid_citations + self.invalid_citations
        return self.valid_citations / count if count else None


@dataclass(frozen=True, slots=True)
class CausalEvaluationReceipt:
    """Immutable, replayable comparison of supplied labels and runner results.

    At least one supported label is required to expose an always-held runner.
    Digests bind exact labels, source revisions, provenance, all submissions
    (including duplicates), counts, runner revision, and evaluator method.
    Each canonical case/result set must fit the shared 64 KiB serialization bound.
    Construction validates and computes every derived field; callers cannot set
    accuracy, authority, or deployed qualification.
    """

    cases: tuple[CausalEvaluationCase, ...]
    results: tuple[CausalEvaluationResult, ...]
    runner_id: str
    runner_source_revision: str
    runner_method: str
    evaluator_method: Literal["typed-causal-quality-v1"] = field(
        default=EVALUATION_METHOD, init=False
    )
    deployed_qualification: Literal[False] = field(default=False, init=False)
    mutation_authority: Literal[False] = field(default=False, init=False)
    promotion_authority: Literal[False] = field(default=False, init=False)
    metrics: CausalEvaluationMetrics = field(init=False)
    case_set_digest: str = field(init=False)
    result_set_digest: str = field(init=False)
    receipt_digest: str = field(init=False)
    receipt_id: str = field(init=False)

    def __post_init__(self) -> None:
        _typed_tuple("cases", self.cases, CausalEvaluationCase, MAX_CASES)
        _typed_tuple("results", self.results, CausalEvaluationResult, MAX_RESULTS)
        _text("runner_id", self.runner_id)
        _digest("runner_source_revision", self.runner_source_revision)
        _text("runner_method", self.runner_method)
        if not self.cases or len({item.case_id for item in self.cases}) != len(self.cases):
            raise ValueError("cases MUST be non-empty with unique stable case ids")
        if not any(
            item.expected_disposition is CausalEvaluationDisposition.SUPPORTED
            for item in self.cases
        ):
            raise ValueError("cases MUST include a supported cause label to measure cause recall")
        if any(item.labeler_id == self.runner_id for item in self.cases):
            raise ValueError("labels MUST be supplied independently from the evaluated runner")
        cases = tuple(sorted(self.cases, key=lambda item: item.case_id))
        results = tuple(sorted(self.results, key=lambda item: canonical_json(asdict(item))))
        object.__setattr__(self, "cases", cases)
        object.__setattr__(self, "results", results)
        metrics = _measure(cases, results)
        case_set_digest = content_digest([asdict(item) for item in cases])
        result_set_digest = content_digest([asdict(item) for item in results])
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "case_set_digest", case_set_digest)
        object.__setattr__(self, "result_set_digest", result_set_digest)
        receipt_digest = content_digest(
            {
                "evaluator_method": self.evaluator_method,
                "runner_id": self.runner_id,
                "runner_source_revision": self.runner_source_revision,
                "runner_method": self.runner_method,
                "case_set_digest": case_set_digest,
                "result_set_digest": result_set_digest,
                "metrics": asdict(metrics),
                "deployed_qualification": self.deployed_qualification,
                "mutation_authority": self.mutation_authority,
                "promotion_authority": self.promotion_authority,
            }
        )
        object.__setattr__(self, "receipt_digest", receipt_digest)
        object.__setattr__(self, "receipt_id", f"causal-evaluation:{receipt_digest[7:]}")


def evaluate_causal_quality(
    *,
    cases: tuple[CausalEvaluationCase, ...],
    results: tuple[CausalEvaluationResult, ...],
    runner_id: str,
    runner_source_revision: str,
    runner_method: str,
) -> CausalEvaluationReceipt:
    """Compare finite independent labels with actual outputs, without invoking a runner.

    Raises ValueError on malformed, unbounded, self-labeled, or vacuous case sets.
    Missing, duplicate, unknown, unsupported, and uncited results are measured, not
    dropped. Allowed references establish citation membership, not causal entailment.
    """

    return CausalEvaluationReceipt(
        cases=cases,
        results=results,
        runner_id=runner_id,
        runner_source_revision=runner_source_revision,
        runner_method=runner_method,
    )


def _measure(
    cases: tuple[CausalEvaluationCase, ...], results: tuple[CausalEvaluationResult, ...]
) -> CausalEvaluationMetrics:
    by_id = {item.case_id: item for item in cases}
    counts = Counter(item.case_id for item in results)
    correct = correct_claims = unsupported = justified = unjustified = 0
    valid_refs = invalid_refs = uncited = 0
    for result in results:
        case = by_id.get(result.case_id)
        allowed = frozenset(case.allowed_evidence_refs) if case else frozenset()
        invalid = len(set(result.cited_evidence_refs) - allowed)
        invalid_refs += invalid
        valid_refs += len(result.cited_evidence_refs) - invalid
        held = result.actual_disposition in _HOLDS
        no_citation = not held and not result.cited_evidence_refs
        uncited += int(no_citation)
        matches = (
            case is not None
            and counts[result.case_id] == 1
            and result.actual_disposition is case.expected_disposition
            and result.actual_cause_ref == case.expected_cause_ref
            and invalid == 0
            and not no_citation
        )
        correct += int(matches)
        if result.actual_disposition is CausalEvaluationDisposition.SUPPORTED:
            correct_claims += int(matches)
            unsupported += int(not matches)
        if held:
            justified += int(matches)
            unjustified += int(not matches)
    return CausalEvaluationMetrics(
        denominator=len(cases),
        submitted_results=len(results),
        completed_cases=sum(counts[item.case_id] == 1 for item in cases),
        correct_cases=correct,
        expected_cause_claims=sum(
            item.expected_disposition is CausalEvaluationDisposition.SUPPORTED for item in cases
        ),
        correct_cause_claims=correct_claims,
        unsupported_cause_claims=unsupported,
        justified_holds=justified,
        unjustified_holds=unjustified,
        valid_citations=valid_refs,
        invalid_citations=invalid_refs,
        uncited_determinate_results=uncited,
        duplicate_results=sum(count - 1 for count in counts.values()),
        unknown_results=sum(count for case_id, count in counts.items() if case_id not in by_id),
        missing_case_ids=tuple(item.case_id for item in cases if counts[item.case_id] == 0),
        duplicate_case_ids=tuple(sorted(key for key, count in counts.items() if count > 1)),
        unknown_case_ids=tuple(sorted(key for key in counts if key not in by_id)),
    )
