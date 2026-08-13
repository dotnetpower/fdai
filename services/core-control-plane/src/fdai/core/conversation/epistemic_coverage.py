"""Finite question-universe and epistemic-closure release contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

_DIGEST_PATTERN = re.compile(r"sha256:[a-f0-9]{64}")
_MAX_CASES = 10_000
_MAX_CASE_ID_LENGTH = 256
_MAX_CLAIM_RECEIPTS = 64


class EpistemicStatus(StrEnum):
    """Exact terminal knowledge posture for one accepted question."""

    VERIFIED_ANSWER = "verified_answer"
    VERIFIED_EMPTY = "verified_empty"
    QUALIFIED_ANSWER = "qualified_answer"
    UNKNOWN_INCOMPLETE = "unknown_incomplete"
    UNKNOWN_STALE = "unknown_stale"
    UNKNOWN_CONFLICT = "unknown_conflict"
    UNKNOWN_UNAVAILABLE = "unknown_unavailable"
    UNKNOWN_TEMPORAL_MISALIGNMENT = "unknown_temporal_misalignment"
    CLARIFICATION_REQUIRED = "clarification_required"
    NOT_APPLICABLE = "not_applicable"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    NOT_AUTHORIZED = "not_authorized"
    ACTION_DRAFT_READY = "action_draft_ready"
    CANCELLED = "cancelled"


_TRANSPORT_DISPOSITIONS = {
    EpistemicStatus.VERIFIED_ANSWER: "answered",
    EpistemicStatus.VERIFIED_EMPTY: "answered",
    EpistemicStatus.QUALIFIED_ANSWER: "answered",
    EpistemicStatus.UNKNOWN_INCOMPLETE: "held",
    EpistemicStatus.UNKNOWN_STALE: "held",
    EpistemicStatus.UNKNOWN_CONFLICT: "held",
    EpistemicStatus.UNKNOWN_UNAVAILABLE: "held",
    EpistemicStatus.UNKNOWN_TEMPORAL_MISALIGNMENT: "held",
    EpistemicStatus.CLARIFICATION_REQUIRED: "clarification",
    EpistemicStatus.NOT_APPLICABLE: "unsupported",
    EpistemicStatus.UNSUPPORTED_CAPABILITY: "unsupported",
    EpistemicStatus.NOT_AUTHORIZED: "held",
    EpistemicStatus.ACTION_DRAFT_READY: "action_draft",
    EpistemicStatus.CANCELLED: "cancelled",
}
_ANSWER_STATUSES = frozenset(
    {
        EpistemicStatus.VERIFIED_ANSWER,
        EpistemicStatus.VERIFIED_EMPTY,
        EpistemicStatus.QUALIFIED_ANSWER,
    }
)
_COMPLETENESS_STATUSES = frozenset(
    {
        *_ANSWER_STATUSES,
        EpistemicStatus.UNKNOWN_INCOMPLETE,
        EpistemicStatus.UNKNOWN_STALE,
        EpistemicStatus.UNKNOWN_CONFLICT,
        EpistemicStatus.UNKNOWN_UNAVAILABLE,
        EpistemicStatus.UNKNOWN_TEMPORAL_MISALIGNMENT,
    }
)


@dataclass(frozen=True, slots=True)
class QuestionUniverseReceipt:
    """Immutable finite denominator generated for one release and principal set."""

    ontology_release_digest: str
    principal_manifest_digests: tuple[str, ...]
    grammar_digest: str
    case_ids: tuple[str, ...]
    excluded_case_ids: tuple[str, ...]
    receipt_digest: str

    def __post_init__(self) -> None:
        _require_digest("ontology_release_digest", self.ontology_release_digest)
        _require_digest("grammar_digest", self.grammar_digest)
        _require_digest("receipt_digest", self.receipt_digest)
        _require_ordered_digests("principal_manifest_digests", self.principal_manifest_digests)
        _require_case_ids("case_ids", self.case_ids, allow_empty=True)
        _require_case_ids("excluded_case_ids", self.excluded_case_ids, allow_empty=True)
        if not self.case_ids and not self.excluded_case_ids:
            raise ValueError("question universe MUST contain a case or typed exclusion")
        if set(self.case_ids).intersection(self.excluded_case_ids):
            raise ValueError("question universe cases and exclusions MUST be disjoint")
        if len(self.case_ids) + len(self.excluded_case_ids) > _MAX_CASES:
            raise ValueError("question universe exceeds its case bound")
        if self.receipt_digest != _digest(self._body()):
            raise ValueError("question universe receipt digest does not match its content")

    @classmethod
    def build(
        cls,
        *,
        ontology_release_digest: str,
        principal_manifest_digests: Sequence[str],
        grammar_digest: str,
        case_ids: Sequence[str],
        excluded_case_ids: Sequence[str] = (),
    ) -> QuestionUniverseReceipt:
        """Build a canonical receipt after sorting every set-valued identity."""

        ordered_principal_digests = tuple(sorted(principal_manifest_digests))
        ordered_case_ids = tuple(sorted(case_ids))
        ordered_excluded_case_ids = tuple(sorted(excluded_case_ids))
        body = {
            "ontology_release_digest": ontology_release_digest,
            "principal_manifest_digests": ordered_principal_digests,
            "grammar_digest": grammar_digest,
            "case_ids": ordered_case_ids,
            "excluded_case_ids": ordered_excluded_case_ids,
        }
        return cls(
            ontology_release_digest=ontology_release_digest,
            principal_manifest_digests=ordered_principal_digests,
            grammar_digest=grammar_digest,
            case_ids=ordered_case_ids,
            excluded_case_ids=ordered_excluded_case_ids,
            receipt_digest=_digest(body),
        )

    def _body(self) -> dict[str, object]:
        return {
            "ontology_release_digest": self.ontology_release_digest,
            "principal_manifest_digests": self.principal_manifest_digests,
            "grammar_digest": self.grammar_digest,
            "case_ids": self.case_ids,
            "excluded_case_ids": self.excluded_case_ids,
        }


@dataclass(frozen=True, slots=True)
class EpistemicQuestionRecord:
    """Proof-carrying terminal status for one case in a question universe."""

    question_id: str
    transport_disposition: str
    epistemic_status: EpistemicStatus
    question_universe_digest: str
    understanding_receipt_digest: str | None = None
    completeness_receipt_digest: str | None = None
    claim_proof_receipt_digests: tuple[str, ...] = ()
    closed_population_receipt_digest: str | None = None
    source_span_coverage: float = 0.0
    semantic_atom_coverage: float = 0.0
    ungrounded_claim_count: int = 0
    unresolved_conflict_count: int = 0
    hidden_scope_leak_count: int = 0
    unsafe_mutation_survivor_count: int = 0
    locale_divergence_count: int = 0

    def __post_init__(self) -> None:
        _require_case_ids("question_id", (self.question_id,), allow_empty=False)
        expected_disposition = _TRANSPORT_DISPOSITIONS[self.epistemic_status]
        if self.transport_disposition != expected_disposition:
            raise ValueError("epistemic status does not match its transport disposition")
        _require_digest("question_universe_digest", self.question_universe_digest)
        optional_digests = (
            self.understanding_receipt_digest,
            self.completeness_receipt_digest,
            self.closed_population_receipt_digest,
        )
        for optional_digest in optional_digests:
            if optional_digest is not None:
                _require_digest("question proof digest", optional_digest)
        if len(self.claim_proof_receipt_digests) > _MAX_CLAIM_RECEIPTS:
            raise ValueError("question claim proof receipt count exceeds its bound")
        _require_ordered_digests(
            "claim_proof_receipt_digests",
            self.claim_proof_receipt_digests,
            allow_empty=True,
        )
        for coverage_name, coverage_value in (
            ("source_span_coverage", self.source_span_coverage),
            ("semantic_atom_coverage", self.semantic_atom_coverage),
        ):
            if not math.isfinite(coverage_value) or not 0.0 <= coverage_value <= 1.0:
                raise ValueError(f"{coverage_name} MUST be finite and in [0, 1]")
        violation_counts = (
            self.ungrounded_claim_count,
            self.unresolved_conflict_count,
            self.hidden_scope_leak_count,
            self.unsafe_mutation_survivor_count,
            self.locale_divergence_count,
        )
        if any(value < 0 for value in violation_counts):
            raise ValueError("epistemic violation counts MUST be non-negative")
        if self.epistemic_status is not EpistemicStatus.CANCELLED:
            if self.understanding_receipt_digest is None:
                raise ValueError("terminal epistemic status requires understanding proof")
            if self.source_span_coverage != 1.0 or self.semantic_atom_coverage != 1.0:
                raise ValueError("terminal epistemic status requires complete interpretation")
        if (
            self.epistemic_status in _COMPLETENESS_STATUSES
            and self.completeness_receipt_digest is None
        ):
            raise ValueError("evidence-bearing epistemic status requires completeness proof")
        if self.epistemic_status in _ANSWER_STATUSES and not self.claim_proof_receipt_digests:
            raise ValueError("answered epistemic status requires claim proof")
        if (
            self.epistemic_status is EpistemicStatus.VERIFIED_EMPTY
            and self.closed_population_receipt_digest is None
        ):
            raise ValueError("verified empty status requires closed-population proof")

    @property
    def violation_count(self) -> int:
        """Return the zero-threshold violation total for release gating."""

        return sum(
            (
                self.ungrounded_claim_count,
                self.unresolved_conflict_count,
                self.hidden_scope_leak_count,
                self.unsafe_mutation_survivor_count,
                self.locale_divergence_count,
            )
        )


@dataclass(frozen=True, slots=True)
class EpistemicCoverageReceipt:
    """Replay-stable closure decision over one complete question universe."""

    ontology_release_digest: str
    principal_manifest_digests: tuple[str, ...]
    question_universe_digest: str
    expected_case_count: int
    closed_case_count: int
    violation_count: int
    passed: bool
    receipt_digest: str


def evaluate_epistemic_coverage(
    *,
    universe: QuestionUniverseReceipt,
    questions: Sequence[EpistemicQuestionRecord],
) -> EpistemicCoverageReceipt:
    """Require exact case accounting and zero unsupported epistemic behavior."""

    identifiers = tuple(item.question_id for item in questions)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("epistemic question ids MUST be unique")
    if set(identifiers) != set(universe.case_ids):
        raise ValueError("epistemic questions MUST exactly cover the question universe")
    if any(item.question_universe_digest != universe.receipt_digest for item in questions):
        raise ValueError("epistemic questions MUST bind the exact question universe")
    violation_count = sum(item.violation_count for item in questions)
    passed = len(questions) == len(universe.case_ids) and violation_count == 0
    body = {
        "ontology_release_digest": universe.ontology_release_digest,
        "principal_manifest_digests": universe.principal_manifest_digests,
        "question_universe_digest": universe.receipt_digest,
        "expected_case_count": len(universe.case_ids),
        "closed_case_count": len(questions),
        "violation_count": violation_count,
        "passed": passed,
    }
    return EpistemicCoverageReceipt(
        ontology_release_digest=universe.ontology_release_digest,
        principal_manifest_digests=universe.principal_manifest_digests,
        question_universe_digest=universe.receipt_digest,
        expected_case_count=len(universe.case_ids),
        closed_case_count=len(questions),
        violation_count=violation_count,
        passed=passed,
        receipt_digest=_digest(body),
    )


def require_epistemic_coverage(receipt: EpistemicCoverageReceipt) -> None:
    """Reject release activation when any universe case lacks safe closure."""

    if not receipt.passed:
        raise ValueError("epistemic coverage release gate failed")


def _require_digest(name: str, value: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a canonical SHA-256 value")


def _require_ordered_digests(
    name: str,
    values: tuple[str, ...],
    *,
    allow_empty: bool = False,
) -> None:
    if not values and not allow_empty:
        raise ValueError(f"{name} MUST be non-empty")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be unique and ordered")
    for value in values:
        _require_digest(name, value)


def _require_case_ids(name: str, values: tuple[str, ...], *, allow_empty: bool) -> None:
    if not values and not allow_empty:
        raise ValueError(f"{name} MUST be non-empty")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be unique and ordered")
    if any(not value or len(value) > _MAX_CASE_ID_LENGTH for value in values):
        raise ValueError(f"{name} MUST contain bounded ids")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "EpistemicCoverageReceipt",
    "EpistemicQuestionRecord",
    "EpistemicStatus",
    "QuestionUniverseReceipt",
    "evaluate_epistemic_coverage",
    "require_epistemic_coverage",
]
