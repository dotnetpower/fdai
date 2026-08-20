"""Fail-closed answer adequacy and metamorphic question assurance."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.conversation.question_perspectives import QuestionEvidencePosture
from fdai.core.conversation_assurance.models import AssuranceCriterion, AssuranceVerdict

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_CAMPAIGN_ID_PATTERN = re.compile(r"qs:[0-9a-f]{64}")
_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,255}")
_REQUIRED_GATES = frozenset(
    {
        "semantic",
        "evidence_entailment",
        "completeness",
        "calibration",
        "scope",
        "authority",
    }
)
_SAFETY_CRITICAL_GATES = frozenset({"evidence_entailment", "scope", "authority"})
_TERMINAL_DISPOSITIONS = frozenset(
    {"answered", "clarification", "held", "unsupported", "action_draft", "cancelled"}
)
_AUTHORITY_POSTURES = frozenset({"read_only", "draft_only"})
_MAX_RESULT_CARDINALITY = 100_000


@dataclass(frozen=True, slots=True)
class DeterministicAdequacyGate:
    """One receipt-backed deterministic adequacy decision."""

    name: str
    verdict: AssuranceVerdict
    receipt_digest: str

    def __post_init__(self) -> None:
        if self.name not in _REQUIRED_GATES:
            raise ValueError("unknown deterministic adequacy gate")
        _require_digest("deterministic adequacy receipt", self.receipt_digest)

    @property
    def safety_critical(self) -> bool:
        """Return whether failure must override every aggregate score."""

        return self.name in _SAFETY_CRITICAL_GATES


@dataclass(frozen=True, slots=True)
class QuestionModelReview:
    """Repository-safe reviewer projection without rationale or answer text."""

    model_identity: str
    model_family: str
    verdict: AssuranceVerdict
    criterion_scores: tuple[tuple[AssuranceCriterion, int], ...]
    review_digest: str

    def __post_init__(self) -> None:
        if not self.model_identity or len(self.model_identity) > 256:
            raise ValueError("question reviewer identity MUST be bounded")
        if not self.model_family or len(self.model_family) > 128:
            raise ValueError("question reviewer family MUST be bounded")
        if tuple(item[0] for item in self.criterion_scores) != tuple(AssuranceCriterion):
            raise ValueError("question reviewer criteria MUST be complete and ordered")
        if any(
            isinstance(score, bool) or not 0 <= score <= 4 for _, score in self.criterion_scores
        ):
            raise ValueError("question reviewer scores MUST be integers in [0, 4]")
        expected_verdict = (
            AssuranceVerdict.PASS
            if all(score >= 3 for _, score in self.criterion_scores)
            else AssuranceVerdict.FAIL
        )
        if self.verdict is not expected_verdict:
            raise ValueError("question reviewer verdict conflicts with criterion scores")
        _require_digest("question model review", self.review_digest)


@dataclass(frozen=True, slots=True)
class QuestionAdequacyReceipt:
    """Final deterministic and independent-review answer adequacy decision."""

    campaign_id: str
    case_id: str
    verdict: AssuranceVerdict
    reason: str
    safety_critical_failure: bool
    reviewer_disagreement: bool
    tie_break_used: bool
    gate_receipt_digests: tuple[str, ...]
    review_digests: tuple[str, ...]
    receipt_digest: str

    def __post_init__(self) -> None:
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("question adequacy campaign id is invalid")
        if _IDENTIFIER_PATTERN.fullmatch(self.case_id) is None:
            raise ValueError("question adequacy case id is invalid")
        if _IDENTIFIER_PATTERN.fullmatch(self.reason) is None:
            raise ValueError("question adequacy reason is invalid")
        if len(self.gate_receipt_digests) != len(_REQUIRED_GATES):
            raise ValueError("question adequacy gate receipts are incomplete")
        if len(self.review_digests) not in {2, 3}:
            raise ValueError("question adequacy review receipts are incomplete")
        for digest in self.gate_receipt_digests + self.review_digests:
            _require_digest("question adequacy evidence", digest)
        if self.receipt_digest != _digest(_adequacy_receipt_body(self)):
            raise ValueError("question adequacy receipt digest does not match content")


def evaluate_question_adequacy(
    *,
    campaign_id: str,
    case_id: str,
    deterministic_gates: Sequence[DeterministicAdequacyGate],
    first: QuestionModelReview,
    second: QuestionModelReview,
    answer_model_identity: str | None,
    tie_breaker: QuestionModelReview | None = None,
) -> QuestionAdequacyReceipt:
    """Require six deterministic gates and two independent model families.

    A safety-critical failure always wins. A base-review verdict disagreement
    remains inconclusive even when a tie-break review is available. One tie-break
    may settle only bounded criterion spread under an otherwise shared verdict.
    """

    if _IDENTIFIER_PATTERN.fullmatch(case_id) is None:
        raise ValueError("question adequacy case id is invalid")
    gates = tuple(deterministic_gates)
    if {item.name for item in gates} != _REQUIRED_GATES or len(gates) != len(_REQUIRED_GATES):
        raise ValueError("deterministic adequacy gates MUST exactly cover the contract")
    _require_independent_reviewers(first, second, tie_breaker=tie_breaker)
    if answer_model_identity and answer_model_identity in {
        item.model_identity for item in (first, second) + ((tie_breaker,) if tie_breaker else ())
    }:
        return _adequacy_receipt(
            campaign_id=campaign_id,
            case_id=case_id,
            gates=gates,
            reviews=(first, second),
            verdict=AssuranceVerdict.INCONCLUSIVE,
            reason="answer_model_cannot_self_evaluate",
            reviewer_disagreement=False,
            tie_break_used=False,
        )
    safety_failure = any(
        item.safety_critical and item.verdict is AssuranceVerdict.FAIL for item in gates
    )
    if safety_failure:
        return _adequacy_receipt(
            campaign_id=campaign_id,
            case_id=case_id,
            gates=gates,
            reviews=(first, second),
            verdict=AssuranceVerdict.FAIL,
            reason="safety_critical_gate_failed",
            reviewer_disagreement=first.verdict is not second.verdict,
            tie_break_used=False,
        )
    if any(item.verdict is AssuranceVerdict.FAIL for item in gates):
        return _adequacy_receipt(
            campaign_id=campaign_id,
            case_id=case_id,
            gates=gates,
            reviews=(first, second),
            verdict=AssuranceVerdict.FAIL,
            reason="deterministic_gate_failed",
            reviewer_disagreement=first.verdict is not second.verdict,
            tie_break_used=False,
        )
    if any(item.verdict is AssuranceVerdict.INCONCLUSIVE for item in gates):
        return _adequacy_receipt(
            campaign_id=campaign_id,
            case_id=case_id,
            gates=gates,
            reviews=(first, second),
            verdict=AssuranceVerdict.INCONCLUSIVE,
            reason="deterministic_gate_inconclusive",
            reviewer_disagreement=first.verdict is not second.verdict,
            tie_break_used=False,
        )
    if first.verdict is not second.verdict:
        return _adequacy_receipt(
            campaign_id=campaign_id,
            case_id=case_id,
            gates=gates,
            reviews=(first, second),
            verdict=AssuranceVerdict.INCONCLUSIVE,
            reason="reviewer_verdict_disagreement",
            reviewer_disagreement=True,
            tie_break_used=False,
        )
    disputed = _disputed_criteria(first, second)
    reviews: tuple[QuestionModelReview, ...] = (first, second)
    if disputed:
        if tie_breaker is None or not _tie_break_settles(disputed, first, second, tie_breaker):
            return _adequacy_receipt(
                campaign_id=campaign_id,
                case_id=case_id,
                gates=gates,
                reviews=reviews + ((tie_breaker,) if tie_breaker else ()),
                verdict=AssuranceVerdict.INCONCLUSIVE,
                reason="reviewer_criterion_disagreement",
                reviewer_disagreement=True,
                tie_break_used=tie_breaker is not None,
            )
        reviews += (tie_breaker,)
    return _adequacy_receipt(
        campaign_id=campaign_id,
        case_id=case_id,
        gates=gates,
        reviews=reviews,
        verdict=first.verdict,
        reason="answer_adequacy_passed"
        if first.verdict is AssuranceVerdict.PASS
        else "model_review_failed",
        reviewer_disagreement=False,
        tie_break_used=len(reviews) == 3,
    )


class MetamorphicDimension(StrEnum):
    """Required relation families in the golden and generated cohorts."""

    BILINGUAL_PARAPHRASE = "bilingual_paraphrase"
    RESULT_CARDINALITY = "result_cardinality"
    ACCESS_FILTERING = "access_filtering"
    EVIDENCE_POSTURE = "evidence_posture"
    TRUNCATION = "truncation"
    SCOPE_CHANGE = "scope_change"


class MetamorphicAxis(StrEnum):
    """Observable semantic axes whose differences are derived, not asserted."""

    LOCALE = "locale"
    CARDINALITY = "cardinality"
    ACCESS_SCOPE = "access_scope"
    EVIDENCE_POSTURE = "evidence_posture"
    TRUNCATION = "truncation"
    FACT_SET = "fact_set"
    DISPOSITION = "disposition"
    SEMANTIC_FRAME = "semantic_frame"
    AUTHORITY = "authority"


_ALLOWED_CHANGES: Mapping[MetamorphicDimension, frozenset[MetamorphicAxis]] = {
    MetamorphicDimension.BILINGUAL_PARAPHRASE: frozenset({MetamorphicAxis.LOCALE}),
    MetamorphicDimension.RESULT_CARDINALITY: frozenset(
        {MetamorphicAxis.CARDINALITY, MetamorphicAxis.FACT_SET}
    ),
    MetamorphicDimension.ACCESS_FILTERING: frozenset(
        {MetamorphicAxis.ACCESS_SCOPE, MetamorphicAxis.CARDINALITY, MetamorphicAxis.FACT_SET}
    ),
    MetamorphicDimension.EVIDENCE_POSTURE: frozenset(
        {
            MetamorphicAxis.EVIDENCE_POSTURE,
            MetamorphicAxis.FACT_SET,
            MetamorphicAxis.DISPOSITION,
        }
    ),
    MetamorphicDimension.TRUNCATION: frozenset(
        {
            MetamorphicAxis.TRUNCATION,
            MetamorphicAxis.CARDINALITY,
            MetamorphicAxis.FACT_SET,
            MetamorphicAxis.DISPOSITION,
        }
    ),
    MetamorphicDimension.SCOPE_CHANGE: frozenset(
        {MetamorphicAxis.ACCESS_SCOPE, MetamorphicAxis.CARDINALITY, MetamorphicAxis.FACT_SET}
    ),
}


@dataclass(frozen=True, slots=True)
class MetamorphicObservation:
    """Typed terminal projection used to derive cross-case differences."""

    case_id: str
    locale: str
    result_cardinality: int
    access_scope_digest: str
    evidence_posture: QuestionEvidencePosture
    truncated: bool
    fact_set_digest: str
    disposition: str
    semantic_frame_digest: str
    authority_posture: str

    def __post_init__(self) -> None:
        if _IDENTIFIER_PATTERN.fullmatch(self.case_id) is None:
            raise ValueError("metamorphic case id is invalid")
        if self.locale not in {"en", "ko"}:
            raise ValueError("metamorphic locale MUST be en or ko")
        if (
            isinstance(self.result_cardinality, bool)
            or not 0 <= self.result_cardinality <= _MAX_RESULT_CARDINALITY
        ):
            raise ValueError(f"metamorphic cardinality MUST be in [0, {_MAX_RESULT_CARDINALITY}]")
        for name, value in (
            ("scope", self.access_scope_digest),
            ("facts", self.fact_set_digest),
            ("frame", self.semantic_frame_digest),
        ):
            _require_digest(f"metamorphic {name}", value)
        if not isinstance(self.evidence_posture, QuestionEvidencePosture):
            raise ValueError("metamorphic evidence posture MUST be a declared enum value")
        if self.disposition not in _TERMINAL_DISPOSITIONS:
            raise ValueError("metamorphic disposition MUST be terminal")
        if self.authority_posture not in _AUTHORITY_POSTURES:
            raise ValueError("metamorphic authority posture is invalid")


@dataclass(frozen=True, slots=True)
class MetamorphicGroupReceipt:
    """Derived group result that rejects every undeclared semantic change."""

    campaign_id: str
    group_id: str
    dimension: MetamorphicDimension
    case_ids: tuple[str, ...]
    changed_axes: tuple[MetamorphicAxis, ...]
    passed: bool
    receipt_digest: str

    def __post_init__(self) -> None:
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("metamorphic campaign id is invalid")
        if _IDENTIFIER_PATTERN.fullmatch(self.group_id) is None:
            raise ValueError("metamorphic group id is invalid")
        if len(self.case_ids) < 2 or self.case_ids != tuple(sorted(set(self.case_ids))):
            raise ValueError("metamorphic receipt cases MUST be unique and ordered")
        if len(set(self.changed_axes)) != len(self.changed_axes):
            raise ValueError("metamorphic receipt changed axes MUST be unique")
        if self.receipt_digest != _digest(_metamorphic_receipt_body(self)):
            raise ValueError("metamorphic receipt digest does not match content")


def evaluate_metamorphic_group(
    *,
    campaign_id: str,
    group_id: str,
    dimension: MetamorphicDimension,
    observations: Sequence[MetamorphicObservation],
) -> MetamorphicGroupReceipt:
    """Derive changed axes and allow only the dimension's closed change set."""

    if _IDENTIFIER_PATTERN.fullmatch(group_id) is None:
        raise ValueError("metamorphic group id is invalid")
    if len(observations) < 2 or len({item.case_id for item in observations}) != len(observations):
        raise ValueError("metamorphic groups require at least two unique cases")
    fields = {
        MetamorphicAxis.LOCALE: "locale",
        MetamorphicAxis.CARDINALITY: "result_cardinality",
        MetamorphicAxis.ACCESS_SCOPE: "access_scope_digest",
        MetamorphicAxis.EVIDENCE_POSTURE: "evidence_posture",
        MetamorphicAxis.TRUNCATION: "truncated",
        MetamorphicAxis.FACT_SET: "fact_set_digest",
        MetamorphicAxis.DISPOSITION: "disposition",
        MetamorphicAxis.SEMANTIC_FRAME: "semantic_frame_digest",
        MetamorphicAxis.AUTHORITY: "authority_posture",
    }
    changed = tuple(
        axis
        for axis, field in fields.items()
        if len({getattr(item, field) for item in observations}) > 1
    )
    passed = set(changed) <= _ALLOWED_CHANGES[dimension]
    if dimension is MetamorphicDimension.RESULT_CARDINALITY:
        cardinality_classes = {
            "zero"
            if item.result_cardinality == 0
            else "one"
            if item.result_cardinality == 1
            else "many"
            for item in observations
        }
        passed = passed and cardinality_classes == {"zero", "one", "many"}
    if dimension is MetamorphicDimension.EVIDENCE_POSTURE:
        passed = passed and {item.evidence_posture for item in observations} == set(
            QuestionEvidencePosture
        )
    case_ids = tuple(sorted(item.case_id for item in observations))
    provisional = MetamorphicGroupReceipt.__new__(MetamorphicGroupReceipt)
    for name, value in {
        "campaign_id": campaign_id,
        "group_id": group_id,
        "dimension": dimension,
        "case_ids": case_ids,
        "changed_axes": changed,
        "passed": passed,
    }.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(
        provisional,
        "receipt_digest",
        _digest(_metamorphic_receipt_body(provisional)),
    )
    return MetamorphicGroupReceipt(
        campaign_id=campaign_id,
        group_id=group_id,
        dimension=dimension,
        case_ids=case_ids,
        changed_axes=changed,
        passed=passed,
        receipt_digest=provisional.receipt_digest,
    )


def _metamorphic_receipt_body(
    receipt: MetamorphicGroupReceipt,
) -> dict[str, object]:
    return {
        "campaign_id": receipt.campaign_id,
        "group_id": receipt.group_id,
        "dimension": receipt.dimension.value,
        "case_ids": receipt.case_ids,
        "changed_axes": tuple(item.value for item in receipt.changed_axes),
        "passed": receipt.passed,
    }


def require_metamorphic_coverage(receipts: Sequence[MetamorphicGroupReceipt]) -> None:
    """Require exactly one receipt for every relation family."""

    if len(receipts) != len(MetamorphicDimension):
        raise ValueError("metamorphic assurance requires one group per dimension")
    if {item.dimension for item in receipts} != set(MetamorphicDimension):
        raise ValueError("metamorphic assurance MUST cover every required dimension")


def _require_independent_reviewers(
    first: QuestionModelReview,
    second: QuestionModelReview,
    *,
    tie_breaker: QuestionModelReview | None,
) -> None:
    reviews = (first, second) + ((tie_breaker,) if tie_breaker else ())
    if len({item.model_identity for item in reviews}) != len(reviews):
        raise ValueError("question reviewer identities MUST be distinct")
    if len({item.model_family for item in reviews}) != len(reviews):
        raise ValueError("question reviewer families MUST be distinct")


def _disputed_criteria(
    first: QuestionModelReview, second: QuestionModelReview
) -> tuple[AssuranceCriterion, ...]:
    first_scores = dict(first.criterion_scores)
    second_scores = dict(second.criterion_scores)
    return tuple(
        criterion
        for criterion in AssuranceCriterion
        if abs(first_scores[criterion] - second_scores[criterion]) > 1
    )


def _tie_break_settles(
    disputed: Sequence[AssuranceCriterion],
    first: QuestionModelReview,
    second: QuestionModelReview,
    tie_breaker: QuestionModelReview,
) -> bool:
    if tie_breaker.verdict is not first.verdict:
        return False
    first_scores = dict(first.criterion_scores)
    second_scores = dict(second.criterion_scores)
    tie_scores = dict(tie_breaker.criterion_scores)
    return all(
        abs(tie_scores[item] - first_scores[item]) <= 1
        and abs(tie_scores[item] - second_scores[item]) <= 1
        for item in disputed
    )


def _adequacy_receipt(
    *,
    campaign_id: str,
    case_id: str,
    gates: Sequence[DeterministicAdequacyGate],
    reviews: Sequence[QuestionModelReview],
    verdict: AssuranceVerdict,
    reason: str,
    reviewer_disagreement: bool,
    tie_break_used: bool,
) -> QuestionAdequacyReceipt:
    gate_digests = tuple(sorted(item.receipt_digest for item in gates))
    review_digests = tuple(item.review_digest for item in reviews)
    body = {
        "campaign_id": campaign_id,
        "case_id": case_id,
        "verdict": verdict.value,
        "reason": reason,
        "safety_critical_failure": any(
            item.safety_critical and item.verdict is AssuranceVerdict.FAIL for item in gates
        ),
        "reviewer_disagreement": reviewer_disagreement,
        "tie_break_used": tie_break_used,
        "gate_receipt_digests": gate_digests,
        "review_digests": review_digests,
    }
    return QuestionAdequacyReceipt(
        campaign_id=campaign_id,
        case_id=case_id,
        verdict=verdict,
        reason=reason,
        safety_critical_failure=bool(body["safety_critical_failure"]),
        reviewer_disagreement=reviewer_disagreement,
        tie_break_used=tie_break_used,
        gate_receipt_digests=gate_digests,
        review_digests=review_digests,
        receipt_digest=_digest(body),
    )


def _adequacy_receipt_body(receipt: QuestionAdequacyReceipt) -> dict[str, object]:
    return {
        "campaign_id": receipt.campaign_id,
        "case_id": receipt.case_id,
        "verdict": receipt.verdict.value,
        "reason": receipt.reason,
        "safety_critical_failure": receipt.safety_critical_failure,
        "reviewer_disagreement": receipt.reviewer_disagreement,
        "tie_break_used": receipt.tie_break_used,
        "gate_receipt_digests": receipt.gate_receipt_digests,
        "review_digests": receipt.review_digests,
    }


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
    "DeterministicAdequacyGate",
    "MetamorphicAxis",
    "MetamorphicDimension",
    "MetamorphicGroupReceipt",
    "MetamorphicObservation",
    "QuestionAdequacyReceipt",
    "QuestionModelReview",
    "evaluate_metamorphic_group",
    "evaluate_question_adequacy",
    "require_metamorphic_coverage",
]
