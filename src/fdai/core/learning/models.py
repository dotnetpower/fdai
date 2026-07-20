"""Bounded evidence models for post-turn improvement review."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.core.operator_memory.types import MemoryCategory, ScopeKind

_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
_MAX_ID_CHARS = 256
_MAX_BODY_CHARS = 16_000
_MAX_CORRECTIONS = 8
_MAX_EVIDENCE_REFS = 64
_MAX_OUTCOMES = 32
_MAX_TOOL_RECEIPTS = 64
_MAX_MARKDOWN_BYTES = 64 * 1024


class EligibilityReason(StrEnum):
    ELIGIBLE_COMPLEX = "eligible_complex"
    ELIGIBLE_CORRECTION = "eligible_correction"
    ELIGIBLE_RECOVERED_FAILURE = "eligible_recovered_failure"
    ELIGIBLE_REPEATED_PROCEDURE = "eligible_repeated_procedure"
    INELIGIBLE = "ineligible"
    OPTED_OUT = "opted_out"
    UNSAFE_CONTENT = "unsafe_content"


class PostTurnProposalKind(StrEnum):
    OPERATOR_MEMORY = "operator_memory"
    RULE_HINT = "rule_hint"
    SKILL_DRAFT = "skill_draft"


@dataclass(frozen=True, slots=True)
class ToolReceiptEvidence:
    """Safe metadata from one tool receipt; raw output is never included."""

    tool_name: str
    status: str
    evidence_ref: str

    def __post_init__(self) -> None:
        _require_safe_id("ToolReceiptEvidence.tool_name", self.tool_name)
        _require_safe_id("ToolReceiptEvidence.status", self.status)
        _require_safe_id("ToolReceiptEvidence.evidence_ref", self.evidence_ref)


@dataclass(frozen=True, slots=True)
class PostTurnReviewInput:
    """Consent-filtered evidence from one completed operator turn."""

    review_id: str
    principal_scope: str
    operator_turn_id: str
    assistant_turn_id: str
    completed_at: datetime
    operator_body: str | None = None
    assistant_body: str | None = None
    tool_receipts: tuple[ToolReceiptEvidence, ...] = ()
    validation_outcomes: tuple[str, ...] = ()
    explicit_corrections: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    memory_scope_kind: ScopeKind | None = None
    memory_scope_ref: str | None = None
    failure_recovered: bool = False
    procedure_fingerprint: str | None = None
    repeated_procedure_count: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("PostTurnReviewInput.review_id", self.review_id),
            ("PostTurnReviewInput.principal_scope", self.principal_scope),
            ("PostTurnReviewInput.operator_turn_id", self.operator_turn_id),
            ("PostTurnReviewInput.assistant_turn_id", self.assistant_turn_id),
        ):
            _require_safe_id(name, value)
        if self.completed_at.tzinfo is None:
            raise ValueError("PostTurnReviewInput.completed_at MUST be timezone-aware")
        _bounded_optional_body("PostTurnReviewInput.operator_body", self.operator_body)
        _bounded_optional_body("PostTurnReviewInput.assistant_body", self.assistant_body)
        _bounded_tuple("tool_receipts", self.tool_receipts, _MAX_TOOL_RECEIPTS)
        _bounded_tuple("validation_outcomes", self.validation_outcomes, _MAX_OUTCOMES)
        _bounded_tuple("explicit_corrections", self.explicit_corrections, _MAX_CORRECTIONS)
        _bounded_tuple("evidence_refs", self.evidence_refs, _MAX_EVIDENCE_REFS)
        for outcome in self.validation_outcomes:
            _require_safe_id("PostTurnReviewInput.validation_outcomes", outcome)
        for correction in self.explicit_corrections:
            _bounded_required_body("PostTurnReviewInput.explicit_corrections", correction)
        for evidence_ref in self.evidence_refs:
            _require_safe_id("PostTurnReviewInput.evidence_refs", evidence_ref)
        if (self.memory_scope_kind is None) != (self.memory_scope_ref is None):
            raise ValueError("memory_scope_kind and memory_scope_ref MUST be supplied together")
        if self.memory_scope_ref is not None:
            _require_bounded_ref("PostTurnReviewInput.memory_scope_ref", self.memory_scope_ref)
        if self.procedure_fingerprint is not None:
            _require_safe_id(
                "PostTurnReviewInput.procedure_fingerprint",
                self.procedure_fingerprint,
            )
        if self.repeated_procedure_count < 0:
            raise ValueError("PostTurnReviewInput.repeated_procedure_count MUST be >= 0")
        if self.procedure_fingerprint is None and self.repeated_procedure_count:
            raise ValueError("repeated_procedure_count requires procedure_fingerprint")

    @property
    def body_shared(self) -> bool:
        return self.operator_body is not None and self.assistant_body is not None


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    reasons: tuple[EligibilityReason, ...]

    def __post_init__(self) -> None:
        if not self.reasons:
            raise ValueError("EligibilityDecision.reasons MUST be non-empty")


@dataclass(frozen=True, slots=True)
class OperatorMemoryCandidate:
    """Unapproved operational-memory content for the existing HIL path."""

    scope_kind: ScopeKind
    scope_ref: str
    category: MemoryCategory
    body: str
    evidence_refs: tuple[str, ...]
    confidence: float
    kind: PostTurnProposalKind = PostTurnProposalKind.OPERATOR_MEMORY

    def __post_init__(self) -> None:
        _require_bounded_ref("OperatorMemoryCandidate.scope_ref", self.scope_ref)
        _bounded_required_body("OperatorMemoryCandidate.body", self.body)
        _validate_proposal_evidence(self.evidence_refs, self.confidence)


@dataclass(frozen=True, slots=True)
class SkillProposalDraft:
    """Unapproved skill Markdown for the existing SkillWorkshop path."""

    skill_name: str
    markdown: bytes
    evidence_refs: tuple[str, ...]
    confidence: float
    kind: PostTurnProposalKind = PostTurnProposalKind.SKILL_DRAFT

    def __post_init__(self) -> None:
        _require_safe_id("SkillProposalDraft.skill_name", self.skill_name)
        if not self.markdown or len(self.markdown) > _MAX_MARKDOWN_BYTES:
            raise ValueError(
                f"SkillProposalDraft.markdown MUST be non-empty and <= {_MAX_MARKDOWN_BYTES} bytes"
            )
        _validate_proposal_evidence(self.evidence_refs, self.confidence)


@dataclass(frozen=True, slots=True)
class RuleCandidateHint:
    """Inert hint that only Norns may convert into a RuleCandidate."""

    proposal_kind: str
    target_ref: str
    pattern: str
    evidence_refs: tuple[str, ...]
    confidence: float
    kind: PostTurnProposalKind = PostTurnProposalKind.RULE_HINT

    def __post_init__(self) -> None:
        _require_safe_id("RuleCandidateHint.proposal_kind", self.proposal_kind)
        _require_safe_id("RuleCandidateHint.target_ref", self.target_ref)
        _bounded_required_body("RuleCandidateHint.pattern", self.pattern)
        _validate_proposal_evidence(self.evidence_refs, self.confidence)


@dataclass(frozen=True, slots=True)
class NoImprovement:
    reason: str

    def __post_init__(self) -> None:
        _require_safe_id("NoImprovement.reason", self.reason)


PostTurnProposal = OperatorMemoryCandidate | RuleCandidateHint | SkillProposalDraft


def _require_safe_id(name: str, value: str) -> None:
    if not value or len(value) > _MAX_ID_CHARS or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a bounded ASCII identifier")


def _require_bounded_ref(name: str, value: str) -> None:
    if not value.strip() or len(value) > 2_048 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be bounded text without control characters")


def _bounded_optional_body(name: str, value: str | None) -> None:
    if value is not None:
        _bounded_required_body(name, value)


def _bounded_required_body(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_BODY_CHARS:
        raise ValueError(f"{name} MUST be non-empty and <= {_MAX_BODY_CHARS} characters")


def _bounded_tuple(name: str, value: tuple[object, ...], maximum: int) -> None:
    if len(value) > maximum:
        raise ValueError(f"PostTurnReviewInput.{name} exceeds cap ({len(value)} > {maximum})")


def _validate_proposal_evidence(evidence_refs: tuple[str, ...], confidence: float) -> None:
    if not evidence_refs or len(evidence_refs) > _MAX_EVIDENCE_REFS:
        raise ValueError("proposal evidence_refs MUST contain 1 to 64 references")
    for evidence_ref in evidence_refs:
        _require_safe_id("proposal.evidence_refs", evidence_ref)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("proposal confidence MUST be in [0, 1]")


__all__ = [
    "EligibilityDecision",
    "EligibilityReason",
    "NoImprovement",
    "OperatorMemoryCandidate",
    "PostTurnProposal",
    "PostTurnProposalKind",
    "PostTurnReviewInput",
    "RuleCandidateHint",
    "SkillProposalDraft",
    "ToolReceiptEvidence",
]
