"""Continuous structural coverage and question-disposition release gates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from fdai_service_contracts.ontology_query import StructuralCoverageReceipt

from .epistemic_coverage import EpistemicCoverageReceipt

_TERMINAL_DISPOSITIONS = frozenset(
    {"answered", "clarification", "held", "unsupported", "action_draft", "cancelled"}
)
_DIGEST_PATTERN = re.compile(r"sha256:[a-f0-9]{64}")
_REASON_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,127}")
_MAX_EVIDENCE_REFS = 12
_MAX_CHECKS = 64

ReceiptSource = Literal["deterministic_fixture", "cross_service_e2e", "live_assurance"]
SemanticRoute = Literal[
    "verified_query_plan",
    "semantic_clarification",
    "semantic_unsupported",
    "semantic_action_draft",
    "semantic_cancellation",
]
UnavailableReason = Literal[
    "authoritative_evidence_unavailable",
    "historical_evidence_unavailable",
    "semantic_planner_unavailable",
]

_RECEIPT_SOURCES = frozenset({"deterministic_fixture", "cross_service_e2e", "live_assurance"})
_PRODUCTION_RECEIPT_SOURCES = frozenset({"cross_service_e2e", "live_assurance"})
_SEMANTIC_ROUTES = frozenset(
    {
        "verified_query_plan",
        "semantic_clarification",
        "semantic_unsupported",
        "semantic_action_draft",
        "semantic_cancellation",
    }
)
_UNAVAILABLE_REASONS = frozenset(
    {
        "authoritative_evidence_unavailable",
        "historical_evidence_unavailable",
        "semantic_planner_unavailable",
    }
)
_ROUTE_BY_DISPOSITION = {
    "answered": "verified_query_plan",
    "clarification": "semantic_clarification",
    "unsupported": "semantic_unsupported",
    "action_draft": "semantic_action_draft",
    "cancelled": "semantic_cancellation",
}


@dataclass(frozen=True, slots=True)
class QuestionDispositionRecord:
    """One evidence-bound terminal outcome without answer content."""

    question_id: str
    cohort: str
    disposition: str
    receipt_id: str = ""
    receipt_source: ReceiptSource | None = None
    reason_code: str | None = None
    semantic_route: SemanticRoute | None = None
    unavailable_reason: UnavailableReason | None = None
    ontology_release_digest: str | None = None
    principal_manifest_digest: str | None = None
    plan_digest: str | None = None
    execution_receipt_digest: str | None = None
    evidence_refs: tuple[str, ...] = ()
    checks_completed: int = 0
    checks_total: int = 0
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
        if not self.receipt_id or len(self.receipt_id) > 256:
            raise ValueError("question receipt id MUST be bounded")
        if self.receipt_source not in _RECEIPT_SOURCES:
            raise ValueError(
                "question receipt source MUST be deterministic_fixture, "
                "cross_service_e2e, or live_assurance"
            )
        if self.reason_code is None or _REASON_CODE_PATTERN.fullmatch(self.reason_code) is None:
            raise ValueError("question reason_code MUST be typed and bounded")
        if self.semantic_route is not None and self.semantic_route not in _SEMANTIC_ROUTES:
            raise ValueError("question semantic route is invalid")
        if (
            self.unavailable_reason is not None
            and self.unavailable_reason not in _UNAVAILABLE_REASONS
        ):
            raise ValueError("question unavailable reason is invalid")
        if (self.semantic_route is None) == (self.unavailable_reason is None):
            raise ValueError("question MUST carry one semantic route or typed unavailable reason")
        expected_route = _ROUTE_BY_DISPOSITION.get(self.disposition)
        if expected_route is not None and self.semantic_route != expected_route:
            raise ValueError("question semantic route does not match its disposition")
        if self.disposition == "held" and self.unavailable_reason is None:
            raise ValueError("held question MUST carry a typed unavailable reason")
        digests = (
            self.ontology_release_digest,
            self.principal_manifest_digest,
            self.plan_digest,
            self.execution_receipt_digest,
        )
        if any(value is not None and _DIGEST_PATTERN.fullmatch(value) is None for value in digests):
            raise ValueError("question receipt digests MUST be canonical SHA-256 values")
        if len(self.evidence_refs) > _MAX_EVIDENCE_REFS:
            raise ValueError("question evidence references exceed the bound")
        if any(not value or len(value) > 256 for value in self.evidence_refs):
            raise ValueError("question evidence references MUST be bounded")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("question evidence references MUST be unique")
        if not 0 <= self.checks_completed <= _MAX_CHECKS:
            raise ValueError("question checks_completed is outside the bound")
        if not 0 <= self.checks_total <= _MAX_CHECKS:
            raise ValueError("question checks_total is outside the bound")
        if self.checks_completed > self.checks_total:
            raise ValueError("question checks_completed MUST NOT exceed checks_total")
        if self.disposition == "answered" and (
            any(value is None for value in digests)
            or not self.evidence_refs
            or self.checks_total == 0
            or self.checks_completed != self.checks_total
        ):
            raise ValueError("answered question MUST carry complete verified receipts")
        if self.unsupported_claim_count < 0 or self.unauthorized_execution_count < 0:
            raise ValueError("question disposition violation counts MUST be non-negative")


@dataclass(frozen=True, slots=True)
class OntologyQueryCoverageGateReceipt:
    """Replay-stable release decision over schema and question cohorts."""

    ontology_release_digest: str
    principal_receipt_digests: tuple[str, ...]
    question_receipt_digests: tuple[str, ...]
    receipt_sources: tuple[str, ...]
    accepted_question_count: int
    terminal_question_count: int
    answer_counts_by_cohort: Mapping[str, int]
    legacy_ordinary_language_count: int
    unsupported_claim_count: int
    unauthorized_execution_count: int
    epistemic_coverage_receipt_digest: str | None
    passed: bool
    production_ready: bool
    receipt_digest: str


def evaluate_ontology_query_coverage(
    *,
    structural_receipts: Sequence[StructuralCoverageReceipt],
    questions: Sequence[QuestionDispositionRecord],
    epistemic_coverage: EpistemicCoverageReceipt | None = None,
) -> OntologyQueryCoverageGateReceipt:
    """Require total structural accounting and terminal question disposition."""

    if not structural_receipts:
        raise ValueError("ontology query coverage requires principal receipts")
    releases = {item.ontology_release_digest for item in structural_receipts}
    if len(releases) != 1:
        raise ValueError("structural coverage receipts MUST share one release")
    if any(not item.complete for item in structural_receipts):
        raise ValueError("structural schema coverage MUST be complete")
    release_digest = next(iter(releases))
    principal_manifest_digests = {item.manifest_digest for item in structural_receipts}
    if epistemic_coverage is not None:
        if epistemic_coverage.ontology_release_digest != release_digest:
            raise ValueError("epistemic coverage MUST match the structural release")
        if set(epistemic_coverage.principal_manifest_digests) != principal_manifest_digests:
            raise ValueError("epistemic coverage MUST match all principal manifests")
    if not questions:
        raise ValueError("question disposition gate requires a non-empty cohort")
    identifiers = [item.question_id for item in questions]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("question disposition ids MUST be unique")
    receipt_ids = [item.receipt_id for item in questions]
    if len(receipt_ids) != len(set(receipt_ids)):
        raise ValueError("question receipt ids MUST be unique")
    execution_receipt_digests = [
        item.execution_receipt_digest
        for item in questions
        if item.execution_receipt_digest is not None
    ]
    if len(execution_receipt_digests) != len(set(execution_receipt_digests)):
        raise ValueError("question execution receipt digests MUST be unique")
    for item in questions:
        if item.disposition != "answered":
            continue
        if item.ontology_release_digest != release_digest:
            raise ValueError("answered question receipt MUST match the structural release")
        if item.principal_manifest_digest not in principal_manifest_digests:
            raise ValueError("answered question receipt MUST match a principal manifest")
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
    principal_receipt_digests = tuple(sorted(item.receipt_digest for item in structural_receipts))
    question_receipt_digests = tuple(sorted(_question_receipt_digest(item) for item in questions))
    receipt_sources = tuple(sorted({str(item.receipt_source) for item in questions}))
    production_ready = (
        passed
        and epistemic_coverage is not None
        and epistemic_coverage.passed
        and all(source in _PRODUCTION_RECEIPT_SOURCES for source in receipt_sources)
    )
    answer_counts_by_cohort = dict(sorted(answers_by_cohort.items()))
    body = {
        "ontology_release_digest": release_digest,
        "principal_receipt_digests": principal_receipt_digests,
        "question_receipt_digests": question_receipt_digests,
        "receipt_sources": receipt_sources,
        "accepted_question_count": len(questions),
        "terminal_question_count": terminal,
        "answer_counts_by_cohort": answer_counts_by_cohort,
        "legacy_ordinary_language_count": legacy,
        "unsupported_claim_count": unsupported,
        "unauthorized_execution_count": unauthorized,
        "epistemic_coverage_receipt_digest": (
            epistemic_coverage.receipt_digest if epistemic_coverage is not None else None
        ),
        "passed": passed,
        "production_ready": production_ready,
    }
    return OntologyQueryCoverageGateReceipt(
        ontology_release_digest=release_digest,
        principal_receipt_digests=principal_receipt_digests,
        question_receipt_digests=question_receipt_digests,
        receipt_sources=receipt_sources,
        accepted_question_count=len(questions),
        terminal_question_count=terminal,
        answer_counts_by_cohort=answer_counts_by_cohort,
        legacy_ordinary_language_count=legacy,
        unsupported_claim_count=unsupported,
        unauthorized_execution_count=unauthorized,
        epistemic_coverage_receipt_digest=(
            epistemic_coverage.receipt_digest if epistemic_coverage is not None else None
        ),
        passed=passed,
        production_ready=production_ready,
        receipt_digest=_digest(body),
    )


def require_ontology_query_coverage(
    receipt: OntologyQueryCoverageGateReceipt,
    *,
    require_production_ready: bool = False,
) -> None:
    """Fail structural validation, and optionally require production evidence."""

    if not receipt.passed:
        raise ValueError("ontology query coverage release gate failed")
    if require_production_ready and not receipt.production_ready:
        raise ValueError("ontology query coverage lacks cross-service or live production proof")


def _question_receipt_digest(record: QuestionDispositionRecord) -> str:
    return _digest(
        {
            "question_id": record.question_id,
            "cohort": record.cohort,
            "disposition": record.disposition,
            "receipt_id": record.receipt_id,
            "receipt_source": record.receipt_source,
            "reason_code": record.reason_code,
            "semantic_route": record.semantic_route,
            "unavailable_reason": record.unavailable_reason,
            "ontology_release_digest": record.ontology_release_digest,
            "principal_manifest_digest": record.principal_manifest_digest,
            "plan_digest": record.plan_digest,
            "execution_receipt_digest": record.execution_receipt_digest,
            "evidence_refs": record.evidence_refs,
            "checks_completed": record.checks_completed,
            "checks_total": record.checks_total,
            "unsupported_claim_count": record.unsupported_claim_count,
            "unauthorized_execution_count": record.unauthorized_execution_count,
            "used_legacy_ordinary_language_route": record.used_legacy_ordinary_language_route,
        }
    )


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
    "ReceiptSource",
    "SemanticRoute",
    "UnavailableReason",
    "evaluate_ontology_query_coverage",
    "require_ontology_query_coverage",
]
