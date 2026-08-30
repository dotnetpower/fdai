"""Compile bounded discrimination-shadow cohorts into inert strategy candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from fdai.core.operational_learning.investigation_strategy_evidence import (
    InvestigationStrategyComparisonEvidence,
)
from fdai.core.rca.discrimination_shadow import (
    ChallengerComparisonOutcome,
    DiscriminationShadowComparison,
    ShadowComparisonDisposition,
)

_MAX_COMPARISONS = 100
_DIGEST_PREFIX = "sha256:"


class InvestigationStrategyCompilationDisposition(StrEnum):
    """Terminal candidate-compilation disposition."""

    COMPILED = "compiled"
    HELD = "held"


class InvestigationStrategyHoldReason(StrEnum):
    """Stable reasons an evidence cohort remains held."""

    MISSING_EVIDENCE = "missing_evidence"
    INSUFFICIENT_COHORT = "insufficient_cohort"
    EVIDENCE_CONFLICT = "evidence_conflict"
    STRATEGY_PAIR_CONFLICT = "strategy_pair_conflict"
    INCOMPLETE_COMPARISON = "incomplete_comparison"
    SAFETY_FAILURE = "safety_failure"
    INVARIANT_FAILURE = "invariant_failure"
    NO_CHALLENGER_IMPROVEMENT = "no_challenger_improvement"
    NO_NON_IMPROVEMENT_CONTROL = "no_non_improvement_control"


@dataclass(frozen=True, slots=True)
class InvestigationStrategyCandidate:
    """Norns-owned inert proposal grounded in exact shadow-comparison refs."""

    active_strategy_digest: str
    challenger_strategy_digest: str
    comparison_refs: tuple[str, ...]
    comparison_digests: tuple[str, ...]
    sample_size: int
    challenger_improvement_count: int
    non_improvement_or_control_count: int
    agreement_count: int
    realized_evidence_count: int
    owner_agent: Literal["Norns"] = "Norns"
    state: Literal["inert"] = "inert"
    activation_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    query_execution_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    candidate_digest: str = field(init=False)
    candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        _digest("active_strategy_digest", self.active_strategy_digest)
        _digest("challenger_strategy_digest", self.challenger_strategy_digest)
        if self.active_strategy_digest == self.challenger_strategy_digest:
            raise ValueError("candidate strategy digests MUST differ")
        _canonical_refs(self.comparison_refs)
        _canonical_digests(self.comparison_digests)
        if len(self.comparison_refs) != len(self.comparison_digests):
            raise ValueError("candidate comparison refs and digests MUST align")
        expected_refs = tuple(_comparison_id(value) for value in self.comparison_digests)
        if self.comparison_refs != expected_refs:
            raise ValueError("candidate comparison refs MUST match their content digests")
        counts = (
            self.sample_size,
            self.challenger_improvement_count,
            self.non_improvement_or_control_count,
            self.agreement_count,
            self.realized_evidence_count,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("candidate cohort counts MUST be non-negative integers")
        if self.sample_size != len(self.comparison_refs):
            raise ValueError("candidate sample_size MUST match comparison refs")
        if self.challenger_improvement_count < 1 or self.non_improvement_or_control_count < 1:
            raise ValueError("candidate cohort MUST contain improvement and control evidence")
        if (
            self.challenger_improvement_count + self.non_improvement_or_control_count
            != self.sample_size
            or self.agreement_count > self.sample_size
            or self.realized_evidence_count > self.sample_size
        ):
            raise ValueError("candidate cohort counts conflict")
        if self.owner_agent != "Norns" or self.state != "inert":
            raise ValueError("investigation strategy candidates MUST be inert and Norns-owned")
        _authority_free(
            self.activation_authority,
            self.promotion_authority,
            self.query_execution_authority,
            self.execution_authority,
            self.mutation_authority,
        )
        digest = _content_digest(_candidate_material(self))
        object.__setattr__(self, "candidate_digest", digest)
        object.__setattr__(self, "candidate_id", _candidate_id(digest))

    def to_rule_candidate_mapping(self) -> dict[str, object]:
        """Return the inert Norns proposal accepted by the existing Mimir queue."""

        return {
            "source_signal": "investigation_strategy_comparison_cohort",
            "evidence": {
                "candidate_id": self.candidate_id,
                "candidate_digest": self.candidate_digest,
                "comparison_refs": list(self.comparison_refs),
                "comparison_digests": list(self.comparison_digests),
                "sample_size": self.sample_size,
                "challenger_improvement_count": self.challenger_improvement_count,
                "non_improvement_or_control_count": (self.non_improvement_or_control_count),
            },
            "proposed_by": "Norns",
            "proposal_kind": "revision",
            "suggested_change": "review_investigation_strategy",
            "target_rule_id": (f"investigation.selector.{self.challenger_strategy_digest[7:23]}"),
            "enforcement_mode": "shadow",
            "auto_promote": False,
        }


@dataclass(frozen=True, slots=True)
class InvestigationStrategyCompilation:
    """Typed compiled or held result; neither state grants authority."""

    disposition: InvestigationStrategyCompilationDisposition
    hold_reasons: tuple[InvestigationStrategyHoldReason, ...]
    candidate: InvestigationStrategyCandidate | None
    evidence_count: int
    cohort_digest: str
    activation_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    query_execution_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, InvestigationStrategyCompilationDisposition):
            raise ValueError("investigation strategy compilation disposition is invalid")
        canonical = tuple(sorted(set(self.hold_reasons), key=str))
        if (
            not isinstance(self.hold_reasons, tuple)
            or any(
                not isinstance(item, InvestigationStrategyHoldReason) for item in self.hold_reasons
            )
            or self.hold_reasons != canonical
        ):
            raise ValueError("compilation hold reasons MUST be a canonical tuple")
        if type(self.evidence_count) is not int or not 0 <= self.evidence_count <= _MAX_COMPARISONS:
            raise ValueError("compilation evidence_count MUST be bounded")
        _digest("cohort_digest", self.cohort_digest)
        compiled = self.disposition is InvestigationStrategyCompilationDisposition.COMPILED
        if compiled != (self.candidate is not None) or compiled == bool(self.hold_reasons):
            raise ValueError("compilation disposition conflicts with candidate or hold reasons")
        _authority_free(
            self.activation_authority,
            self.promotion_authority,
            self.query_execution_authority,
            self.execution_authority,
        )
        object.__setattr__(self, "result_digest", _content_digest(_result_material(self)))


class InvestigationStrategyCandidateCompiler:
    """Require one bounded, balanced, failure-free strategy-pair cohort."""

    def compile(
        self,
        comparisons: tuple[DiscriminationShadowComparison, ...],
    ) -> InvestigationStrategyCompilation:
        """Compile eligible evidence or return every applicable typed hold."""

        _validate_boundary(comparisons)
        return self.compile_evidence(
            tuple(InvestigationStrategyComparisonEvidence.from_shadow(item) for item in comparisons)
        )

    def compile_evidence(
        self,
        comparisons: tuple[InvestigationStrategyComparisonEvidence, ...],
    ) -> InvestigationStrategyCompilation:
        """Compile one Muninn-sealed transport cohort as Norns."""

        _validate_evidence_boundary(comparisons)
        cohort_digest = _content_digest(
            {"comparison_digests": sorted(item.comparison_digest for item in comparisons)}
        )
        reasons: set[InvestigationStrategyHoldReason] = set()
        if not comparisons:
            reasons.add(InvestigationStrategyHoldReason.MISSING_EVIDENCE)
        elif len(comparisons) < 2:
            reasons.add(InvestigationStrategyHoldReason.INSUFFICIENT_COHORT)
        pairs = {
            (item.active_strategy_digest, item.challenger_strategy_digest) for item in comparisons
        }
        if len(pairs) > 1:
            reasons.add(InvestigationStrategyHoldReason.STRATEGY_PAIR_CONFLICT)
        ids = tuple(item.comparison_id for item in comparisons)
        digests = tuple(item.comparison_digest for item in comparisons)
        if len(ids) != len(set(ids)) or len(digests) != len(set(digests)):
            reasons.add(InvestigationStrategyHoldReason.EVIDENCE_CONFLICT)
        if any(item.disposition is ShadowComparisonDisposition.HELD for item in comparisons):
            reasons.add(InvestigationStrategyHoldReason.INCOMPLETE_COMPARISON)
        if any(item.safety_failure for item in comparisons):
            reasons.add(InvestigationStrategyHoldReason.SAFETY_FAILURE)
        if any(item.invariant_failure for item in comparisons):
            reasons.add(InvestigationStrategyHoldReason.INVARIANT_FAILURE)
        improvements = sum(
            item.challenger_outcome is ChallengerComparisonOutcome.IMPROVEMENT
            for item in comparisons
        )
        non_improvements = sum(
            item.challenger_outcome
            in {
                ChallengerComparisonOutcome.NON_IMPROVEMENT,
                ChallengerComparisonOutcome.CONTROL,
            }
            for item in comparisons
        )
        if comparisons and improvements == 0:
            reasons.add(InvestigationStrategyHoldReason.NO_CHALLENGER_IMPROVEMENT)
        if comparisons and non_improvements == 0:
            reasons.add(InvestigationStrategyHoldReason.NO_NON_IMPROVEMENT_CONTROL)
        if reasons:
            return _held(comparisons, reasons, cohort_digest=cohort_digest)
        active_digest, challenger_digest = next(iter(pairs))
        ordered = tuple(sorted(comparisons, key=lambda item: item.comparison_digest))
        candidate = InvestigationStrategyCandidate(
            active_strategy_digest=active_digest,
            challenger_strategy_digest=challenger_digest,
            comparison_refs=tuple(item.comparison_id for item in ordered),
            comparison_digests=tuple(item.comparison_digest for item in ordered),
            sample_size=len(ordered),
            challenger_improvement_count=improvements,
            non_improvement_or_control_count=non_improvements,
            agreement_count=sum(item.agreement for item in ordered),
            realized_evidence_count=sum(item.realized_evidence_eligible for item in ordered),
        )
        return InvestigationStrategyCompilation(
            disposition=InvestigationStrategyCompilationDisposition.COMPILED,
            hold_reasons=(),
            candidate=candidate,
            evidence_count=len(comparisons),
            cohort_digest=cohort_digest,
        )


def compile_investigation_strategy_candidate(
    comparisons: tuple[DiscriminationShadowComparison, ...],
) -> InvestigationStrategyCompilation:
    """Compile one cohort through the stateless candidate compiler."""

    return InvestigationStrategyCandidateCompiler().compile(comparisons)


def _validate_boundary(comparisons: object) -> None:
    if (
        not isinstance(comparisons, tuple)
        or any(not isinstance(item, DiscriminationShadowComparison) for item in comparisons)
        or len(comparisons) > _MAX_COMPARISONS
    ):
        raise ValueError("strategy comparison cohort MUST be a bounded immutable typed tuple")


def _validate_evidence_boundary(comparisons: object) -> None:
    if (
        not isinstance(comparisons, tuple)
        or any(
            not isinstance(item, InvestigationStrategyComparisonEvidence) for item in comparisons
        )
        or len(comparisons) > _MAX_COMPARISONS
    ):
        raise ValueError("strategy comparison evidence MUST be a bounded immutable typed tuple")


def _held(
    comparisons: tuple[InvestigationStrategyComparisonEvidence, ...],
    reasons: set[InvestigationStrategyHoldReason],
    *,
    cohort_digest: str,
) -> InvestigationStrategyCompilation:
    return InvestigationStrategyCompilation(
        disposition=InvestigationStrategyCompilationDisposition.HELD,
        hold_reasons=tuple(sorted(reasons, key=str)),
        candidate=None,
        evidence_count=len(comparisons),
        cohort_digest=cohort_digest,
    )


def _candidate_material(candidate: InvestigationStrategyCandidate) -> dict[str, object]:
    return {
        "active_strategy_digest": candidate.active_strategy_digest,
        "challenger_strategy_digest": candidate.challenger_strategy_digest,
        "comparison_refs": list(candidate.comparison_refs),
        "comparison_digests": list(candidate.comparison_digests),
        "sample_size": candidate.sample_size,
        "challenger_improvement_count": candidate.challenger_improvement_count,
        "non_improvement_or_control_count": candidate.non_improvement_or_control_count,
        "agreement_count": candidate.agreement_count,
        "realized_evidence_count": candidate.realized_evidence_count,
        "owner_agent": "Norns",
        "state": "inert",
        "activation_authority": False,
        "promotion_authority": False,
        "query_execution_authority": False,
        "execution_authority": False,
        "mutation_authority": False,
    }


def _result_material(result: InvestigationStrategyCompilation) -> dict[str, object]:
    return {
        "disposition": result.disposition.value,
        "hold_reasons": [item.value for item in result.hold_reasons],
        "candidate_digest": result.candidate.candidate_digest if result.candidate else None,
        "evidence_count": result.evidence_count,
        "cohort_digest": result.cohort_digest,
        "activation_authority": False,
        "promotion_authority": False,
        "query_execution_authority": False,
        "execution_authority": False,
    }


def _canonical_refs(values: tuple[str, ...]) -> None:
    if (
        not isinstance(values, tuple)
        or not 2 <= len(values) <= _MAX_COMPARISONS
        or values != tuple(sorted(set(values)))
        or any(
            not value.startswith("discrimination-shadow-") or len(value) > 256 for value in values
        )
    ):
        raise ValueError("candidate comparison refs MUST be canonical and bounded")


def _canonical_digests(values: tuple[str, ...]) -> None:
    if (
        not isinstance(values, tuple)
        or not 2 <= len(values) <= _MAX_COMPARISONS
        or values != tuple(sorted(set(values)))
    ):
        raise ValueError("candidate comparison digests MUST be canonical and bounded")
    for value in values:
        _digest("comparison_digest", value)


def _digest(name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith(_DIGEST_PREFIX)
        or len(value) != len(_DIGEST_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a sha256 digest")


def _content_digest(value: object) -> str:
    encoded = json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    return f"{_DIGEST_PREFIX}{hashlib.sha256(encoded).hexdigest()}"


def _candidate_id(digest: str) -> str:
    return f"investigation-strategy-{digest.removeprefix(_DIGEST_PREFIX)[:32]}"


def _comparison_id(digest: str) -> str:
    return f"discrimination-shadow-{digest.removeprefix(_DIGEST_PREFIX)[:32]}"


def _authority_free(*values: object) -> None:
    if any(value is not False for value in values):
        raise ValueError("investigation strategy records MUST NOT grant authority")


__all__ = [
    "InvestigationStrategyCandidate",
    "InvestigationStrategyCandidateCompiler",
    "InvestigationStrategyCompilation",
    "InvestigationStrategyCompilationDisposition",
    "InvestigationStrategyHoldReason",
    "compile_investigation_strategy_candidate",
]
