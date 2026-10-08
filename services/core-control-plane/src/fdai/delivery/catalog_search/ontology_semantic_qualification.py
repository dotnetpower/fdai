"""Pre-registered agreement-gated, pooled qualification over verified semantic passes.

A stochastic proposal model cannot honestly meet a single-run 1.0 threshold, and repeating
runs until one passes would select a favorable sample. This protocol is fixed before any
holdout it judges is measured. Wrong selections are the safety gate; clarifications are a
safe failure that only lowers the correct-answer rate.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from .ontology_evaluation import OntologyRetrievalEvaluationCase
from .ontology_semantic_evaluation import OntologySemanticEvaluationReport

PROTOCOL_ID = "agreement-gated-pooled-qualification.v1"


@dataclass(frozen=True, slots=True)
class OntologyQualificationProtocol:
    """Frozen v1 parameters; changing any value requires a new protocol id."""

    protocol_id: str = PROTOCOL_ID
    passes_per_decision: int = 2
    decisions_per_case: int = 3
    confidence: float = 0.95
    max_pooled_wrong_upper_bound: float = 0.02
    max_language_wrong_upper_bound: float = 0.03
    min_language_correct_rate: float = 0.95

    def __post_init__(self) -> None:
        if (
            self.protocol_id != PROTOCOL_ID
            or self.passes_per_decision != 2
            or self.decisions_per_case != 3
            or self.confidence != 0.95
            or self.max_pooled_wrong_upper_bound != 0.02
            or self.max_language_wrong_upper_bound != 0.03
            or self.min_language_correct_rate != 0.95
        ):
            raise ValueError("qualification protocol v1 parameters are pre-registered")


@dataclass(frozen=True, slots=True)
class GatedDecision:
    case_id: str
    language: str
    expected: frozenset[str]
    selected: frozenset[str]
    agreed: bool

    @property
    def wrong(self) -> bool:
        return bool(self.selected - self.expected)

    @property
    def correct(self) -> bool:
        return self.selected == self.expected


@dataclass(frozen=True, slots=True)
class LanguageQualification:
    language: str
    decisions: int
    wrong: int
    wrong_upper_bound: float
    answerable: int
    correct: int

    @property
    def correct_rate(self) -> float:
        return self.correct / self.answerable if self.answerable else 1.0


@dataclass(frozen=True, slots=True)
class OntologyQualificationReport:
    protocol_id: str
    stage: Literal["calibration", "holdout"]
    binding_digests: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    decisions: int
    wrong: int
    wrong_upper_bound: float
    languages: tuple[LanguageQualification, ...]
    disagreements: int
    failure_codes: tuple[str, ...]
    production_qualification: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)

    @property
    def passed(self) -> bool:
        return not self.failure_codes


def clopper_pearson_upper(failures: int, trials: int, confidence: float = 0.95) -> float:
    """One-sided exact upper confidence bound for a binomial failure rate."""
    if trials <= 0 or not 0 <= failures <= trials or not 0 < confidence < 1:
        raise ValueError("binomial bound requires valid counts and confidence")
    if failures == trials:
        return 1.0
    alpha = 1 - confidence

    def cdf(rate: float) -> float:
        if rate <= 0:
            return 1.0
        if rate >= 1:
            return 0.0
        log_p, log_q = math.log(rate), math.log1p(-rate)
        return math.fsum(
            math.exp(
                math.lgamma(trials + 1)
                - math.lgamma(k + 1)
                - math.lgamma(trials - k + 1)
                + k * log_p
                + (trials - k) * log_q
            )
            for k in range(failures + 1)
        )

    low, high = 0.0, 1.0
    for _ in range(100):
        middle = (low + high) / 2
        if cdf(middle) > alpha:
            low = middle
        else:
            high = middle
    return high


def gate_agreement(
    cases: Sequence[OntologyRetrievalEvaluationCase],
    passes: Sequence[OntologySemanticEvaluationReport],
) -> tuple[GatedDecision, ...]:
    """Select a case only when every pass returned exactly the same membership set."""
    cases = tuple(cases)
    if len(passes) < 2 or any(len(report.measurements) != len(cases) for report in passes):
        raise ValueError("agreement gate requires complete passes over the same cases")
    decisions: list[GatedDecision] = []
    for index, case in enumerate(cases):
        results = []
        for report in passes:
            measurement = report.measurements[index]
            if measurement.case_id != case.case_id:
                raise ValueError("agreement gate passes must keep the frozen case order")
            results.append(frozenset(measurement.retrieved_document_ids))
        agreed = all(result == results[0] for result in results)
        decisions.append(
            GatedDecision(
                case_id=case.case_id,
                language=case.cohort.split("-", 1)[0],
                expected=frozenset(case.expected_document_ids),
                selected=results[0] if agreed else frozenset(),
                agreed=agreed,
            )
        )
    return tuple(decisions)


@dataclass(frozen=True, slots=True)
class OntologyQualificationGroup:
    """K x R verified passes of one frozen case set, in decision order."""

    cases: tuple[OntologyRetrievalEvaluationCase, ...]
    passes: tuple[OntologySemanticEvaluationReport, ...]
    evidence_digests: tuple[str, ...]


def qualify_agreement_gated_passes(
    *,
    groups: Sequence[OntologyQualificationGroup],
    protocol: OntologyQualificationProtocol | None = None,
) -> OntologyQualificationReport:
    """Pool gated decisions across case sets of one stage and judge them once.

    Callers verify every pass offline first and pin each pass's evidence digest; a retained
    file can't count twice. Each group holds K x R passes sharing one binding digest. Aborted
    passes are not reports and never count.
    """
    protocol = protocol or OntologyQualificationProtocol()
    expected_passes = protocol.passes_per_decision * protocol.decisions_per_case
    all_digests = [digest for group in groups for digest in group.evidence_digests]
    stages = {report.stage for group in groups for report in group.passes}
    case_ids = [case.case_id for group in groups for case in group.cases]
    if (
        not groups
        or len(stages) != 1
        or len(set(all_digests)) != len(all_digests)
        or len(set(case_ids)) != len(case_ids)
    ):
        raise ValueError("qualification groups need one stage, unique evidence and cases")
    bindings: list[str] = []
    decisions: list[GatedDecision] = []
    for group in groups:
        group_bindings = {report.binding_digest for report in group.passes}
        if (
            len(group.passes) != expected_passes
            or len(group.evidence_digests) != expected_passes
            or len(group_bindings) != 1
        ):
            raise ValueError("qualification requires K x R passes of one binding per group")
        bindings.extend(group_bindings)
        for start in range(0, expected_passes, protocol.passes_per_decision):
            decisions.extend(
                gate_agreement(
                    group.cases, group.passes[start : start + protocol.passes_per_decision]
                )
            )
    if len(set(bindings)) != len(bindings):
        raise ValueError("qualification groups must be distinct evaluation bindings")
    wrong = sum(decision.wrong for decision in decisions)
    pooled_bound = clopper_pearson_upper(wrong, len(decisions), protocol.confidence)
    failures: list[str] = []
    if pooled_bound > protocol.max_pooled_wrong_upper_bound:
        failures.append("pooled-wrong-selection-bound-exceeded")
    languages: list[LanguageQualification] = []
    for language in sorted({decision.language for decision in decisions}):
        own = [decision for decision in decisions if decision.language == language]
        own_wrong = sum(decision.wrong for decision in own)
        answerable = [decision for decision in own if decision.expected]
        result = LanguageQualification(
            language=language,
            decisions=len(own),
            wrong=own_wrong,
            wrong_upper_bound=clopper_pearson_upper(own_wrong, len(own), protocol.confidence),
            answerable=len(answerable),
            correct=sum(decision.correct for decision in answerable),
        )
        languages.append(result)
        if result.wrong_upper_bound > protocol.max_language_wrong_upper_bound:
            failures.append(f"{language}-wrong-selection-bound-exceeded")
        if result.correct_rate < protocol.min_language_correct_rate:
            failures.append(f"{language}-correct-rate-below-threshold")
    return OntologyQualificationReport(
        protocol_id=protocol.protocol_id,
        stage=next(iter(stages)),
        binding_digests=tuple(bindings),
        evidence_digests=tuple(all_digests),
        decisions=len(decisions),
        wrong=wrong,
        wrong_upper_bound=pooled_bound,
        languages=tuple(languages),
        disagreements=sum(not decision.agreed for decision in decisions),
        failure_codes=tuple(failures),
    )


__all__ = [
    "PROTOCOL_ID",
    "GatedDecision",
    "LanguageQualification",
    "OntologyQualificationGroup",
    "OntologyQualificationProtocol",
    "OntologyQualificationReport",
    "clopper_pearson_upper",
    "gate_agreement",
    "qualify_agreement_gated_passes",
]
