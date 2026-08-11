"""Continuous structural coverage and question-disposition release gates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai_service_contracts.ontology_query import StructuralCoverageReceipt

_TERMINAL_DISPOSITIONS = frozenset(
    {"answered", "clarification", "held", "unsupported", "action_draft", "cancelled"}
)


@dataclass(frozen=True, slots=True)
class QuestionDispositionRecord:
    """One replay-cohort terminal outcome without answer content."""

    question_id: str
    cohort: str
    disposition: str
    unsupported_claim_count: int = 0
    unauthorized_execution_count: int = 0
    used_legacy_ordinary_language_route: bool = False

    def __post_init__(self) -> None:
        if not self.question_id or len(self.question_id) > 256:
            raise ValueError("question disposition id MUST be bounded")
        if not self.cohort or len(self.cohort) > 128:
            raise ValueError("question disposition cohort MUST be bounded")
        if self.disposition not in _TERMINAL_DISPOSITIONS:
            raise ValueError("question disposition MUST be terminal")
        if self.unsupported_claim_count < 0 or self.unauthorized_execution_count < 0:
            raise ValueError("question disposition violation counts MUST be non-negative")


@dataclass(frozen=True, slots=True)
class OntologyQueryCoverageGateReceipt:
    """Replay-stable release decision over schema and question cohorts."""

    ontology_release_digest: str
    principal_receipt_digests: tuple[str, ...]
    accepted_question_count: int
    terminal_question_count: int
    answer_counts_by_cohort: Mapping[str, int]
    legacy_ordinary_language_count: int
    unsupported_claim_count: int
    unauthorized_execution_count: int
    passed: bool
    receipt_digest: str


def evaluate_ontology_query_coverage(
    *,
    structural_receipts: Sequence[StructuralCoverageReceipt],
    questions: Sequence[QuestionDispositionRecord],
) -> OntologyQueryCoverageGateReceipt:
    """Require total structural accounting and terminal question disposition."""

    if not structural_receipts:
        raise ValueError("ontology query coverage requires principal receipts")
    releases = {item.ontology_release_digest for item in structural_receipts}
    if len(releases) != 1:
        raise ValueError("structural coverage receipts MUST share one release")
    if any(not item.complete for item in structural_receipts):
        raise ValueError("structural schema coverage MUST be complete")
    if not questions:
        raise ValueError("question disposition gate requires a non-empty cohort")
    identifiers = [item.question_id for item in questions]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("question disposition ids MUST be unique")
    answers_by_cohort: dict[str, int] = {}
    for item in questions:
        if item.disposition == "answered":
            answers_by_cohort[item.cohort] = answers_by_cohort.get(item.cohort, 0) + 1
        else:
            answers_by_cohort.setdefault(item.cohort, 0)
    legacy = sum(item.used_legacy_ordinary_language_route for item in questions)
    unsupported = sum(item.unsupported_claim_count for item in questions)
    unauthorized = sum(item.unauthorized_execution_count for item in questions)
    terminal = sum(item.disposition in _TERMINAL_DISPOSITIONS for item in questions)
    passed = terminal == len(questions) and legacy == 0 and unsupported == 0 and unauthorized == 0
    release_digest = next(iter(releases))
    principal_receipt_digests = tuple(sorted(item.receipt_digest for item in structural_receipts))
    answer_counts_by_cohort = dict(sorted(answers_by_cohort.items()))
    body = {
        "ontology_release_digest": release_digest,
        "principal_receipt_digests": principal_receipt_digests,
        "accepted_question_count": len(questions),
        "terminal_question_count": terminal,
        "answer_counts_by_cohort": answer_counts_by_cohort,
        "legacy_ordinary_language_count": legacy,
        "unsupported_claim_count": unsupported,
        "unauthorized_execution_count": unauthorized,
        "passed": passed,
    }
    return OntologyQueryCoverageGateReceipt(
        ontology_release_digest=release_digest,
        principal_receipt_digests=principal_receipt_digests,
        accepted_question_count=len(questions),
        terminal_question_count=terminal,
        answer_counts_by_cohort=answer_counts_by_cohort,
        legacy_ordinary_language_count=legacy,
        unsupported_claim_count=unsupported,
        unauthorized_execution_count=unauthorized,
        passed=passed,
        receipt_digest=_digest(body),
    )


def require_ontology_query_coverage(receipt: OntologyQueryCoverageGateReceipt) -> None:
    """Fail a release when any continuous query coverage invariant is violated."""

    if not receipt.passed:
        raise ValueError("ontology query coverage release gate failed")


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
    "OntologyQueryCoverageGateReceipt",
    "QuestionDispositionRecord",
    "evaluate_ontology_query_coverage",
    "require_ontology_query_coverage",
]
