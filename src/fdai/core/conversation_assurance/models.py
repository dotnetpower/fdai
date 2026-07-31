"""Immutable contracts for off-path conversation assurance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

_MAX_TEXT_CHARS = 16_384
_MAX_RATIONALE_CHARS = 1_000
_MAX_EVIDENCE_REFS = 64


class AssuranceCriterion(StrEnum):
    FACTUAL_CORRECTNESS = "factual_correctness"
    INTENT_RESOLUTION = "intent_resolution"
    COMPLETENESS = "completeness"
    CALIBRATION = "calibration"
    ACTIONABILITY = "actionability"
    CLARITY = "clarity"


class AssuranceVerdict(StrEnum):
    PASS = "pass"  # noqa: S105 - machine verdict, not a credential
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class AssessmentState(StrEnum):
    COMPLETED = "completed"
    DEFERRED = "deferred"
    DISPUTED = "disputed"


class DisputeReason(StrEnum):
    WRONG_FACT = "wrong_fact"
    MISSING_INTENT = "missing_intent"
    STALE_EVIDENCE = "stale_evidence"
    WRONG_SCOPE = "wrong_scope"
    INAPPROPRIATE_ABSTENTION = "inappropriate_abstention"
    LANGUAGE_QUALITY = "language_quality"


CRITERION_WEIGHTS: dict[AssuranceCriterion, int] = {
    AssuranceCriterion.FACTUAL_CORRECTNESS: 4,
    AssuranceCriterion.INTENT_RESOLUTION: 3,
    AssuranceCriterion.COMPLETENESS: 2,
    AssuranceCriterion.CALIBRATION: 3,
    AssuranceCriterion.ACTIONABILITY: 2,
    AssuranceCriterion.CLARITY: 1,
}


@dataclass(frozen=True, slots=True)
class TurnAssessmentInput:
    """Bounded transient input assembled from one persisted terminal turn."""

    turn_id: str
    conversation_id: str
    principal_scope: str
    question: str
    answer: str
    question_digest: str
    answer_digest: str
    evidence_manifest_digest: str
    evidence_refs: tuple[str, ...]
    verification_status: str
    verification_authority: str
    checks_completed: int
    checks_total: int
    failed_claim_ids: tuple[str, ...] = ()
    locale: str = "en"
    answer_model_identity: str | None = None
    deterministic_answer: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("turn_id", self.turn_id),
            ("conversation_id", self.conversation_id),
            ("principal_scope", self.principal_scope),
            ("question_digest", self.question_digest),
            ("answer_digest", self.answer_digest),
            ("evidence_manifest_digest", self.evidence_manifest_digest),
            ("verification_status", self.verification_status),
            ("verification_authority", self.verification_authority),
        ):
            if not value or not value.strip():
                raise ValueError(f"TurnAssessmentInput.{name} MUST be non-empty")
        for name, value in (("question", self.question), ("answer", self.answer)):
            if not value.strip() or len(value) > _MAX_TEXT_CHARS:
                raise ValueError(
                    f"TurnAssessmentInput.{name} MUST contain 1..{_MAX_TEXT_CHARS} characters"
                )
        if self.locale not in {"en", "ko"}:
            raise ValueError("TurnAssessmentInput.locale MUST be en or ko")
        if not 0 <= self.checks_completed <= self.checks_total:
            raise ValueError("verification check counts are inconsistent")
        if len(self.evidence_refs) > _MAX_EVIDENCE_REFS:
            raise ValueError("TurnAssessmentInput.evidence_refs exceeds the bounded cap")


@dataclass(frozen=True, slots=True)
class CriterionScore:
    criterion: AssuranceCriterion
    score: int
    rationale: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.score, bool) or not 0 <= self.score <= 4:
            raise ValueError("CriterionScore.score MUST be an integer in [0, 4]")
        if not self.rationale.strip() or len(self.rationale) > _MAX_RATIONALE_CHARS:
            raise ValueError(
                f"CriterionScore.rationale MUST contain 1..{_MAX_RATIONALE_CHARS} characters"
            )
        if len(self.evidence_refs) > _MAX_EVIDENCE_REFS:
            raise ValueError("CriterionScore.evidence_refs exceeds the bounded cap")


@dataclass(frozen=True, slots=True)
class EvaluatorOutput:
    model_identity: str
    model_family: str
    scores: tuple[CriterionScore, ...]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_microusd: int = 0

    def __post_init__(self) -> None:
        if not self.model_identity.strip() or not self.model_family.strip():
            raise ValueError("evaluator model identity and family MUST be non-empty")
        if any(value < 0 for value in self.usage):
            raise ValueError("evaluator usage and cost MUST be non-negative")

    @property
    def usage(self) -> tuple[int, int, int]:
        return self.prompt_tokens, self.completion_tokens, self.cost_microusd


@dataclass(frozen=True, slots=True)
class AssuranceDecision:
    verdict: AssuranceVerdict
    content_score: float
    confidence: float
    criteria: tuple[CriterionScore, ...] = ()
    reasons: tuple[str, ...] = ()
    evaluator_identities: tuple[str, ...] = ()
    disagreement: bool = False
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_microusd: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.content_score <= 100.0:
            raise ValueError("AssuranceDecision.content_score MUST be in [0, 100]")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("AssuranceDecision.confidence MUST be in [0, 1]")
        if not 0 <= self.model_calls <= 3:
            raise ValueError("AssuranceDecision.model_calls MUST be in [0, 3]")


@dataclass(frozen=True, slots=True)
class DeterministicAssessment:
    verdict: AssuranceVerdict | None
    reasons: tuple[str, ...] = ()

    @property
    def needs_semantic_review(self) -> bool:
        return self.verdict is None


@dataclass(frozen=True, slots=True)
class DebateContext:
    first: EvaluatorOutput
    second: EvaluatorOutput
    disputed_criteria: tuple[AssuranceCriterion, ...]


@runtime_checkable
class ConversationAssuranceEvaluator(Protocol):
    @property
    def model_identity(self) -> str: ...

    @property
    def model_family(self) -> str: ...

    @property
    def prospective_cost_microusd(self) -> int: ...

    async def evaluate(
        self,
        turn: TurnAssessmentInput,
        *,
        debate: DebateContext | None = None,
    ) -> EvaluatorOutput: ...


@dataclass(frozen=True, slots=True)
class AssessmentRecord:
    assessment_id: str
    turn_id: str
    conversation_id: str
    principal_scope: str
    question_digest: str
    answer_digest: str
    evidence_manifest_digest: str
    rubric_version: str
    model_set_digest: str
    decision: AssuranceDecision
    assessed_at: datetime
    state: AssessmentState = AssessmentState.COMPLETED
    dispute_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.assessed_at.tzinfo is None:
            raise ValueError("AssessmentRecord.assessed_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class DisputeRecord:
    dispute_id: str
    assessment_id: str
    principal_scope: str
    reported_by: str
    reason: DisputeReason
    detail: str
    evidence_refs: tuple[str, ...]
    reported_at: datetime

    def __post_init__(self) -> None:
        if not self.detail.strip() or len(self.detail) > _MAX_RATIONALE_CHARS:
            raise ValueError(
                f"DisputeRecord.detail MUST contain 1..{_MAX_RATIONALE_CHARS} characters"
            )
        if self.reported_at.tzinfo is None:
            raise ValueError("DisputeRecord.reported_at MUST be timezone-aware")
        if len(self.evidence_refs) > _MAX_EVIDENCE_REFS:
            raise ValueError("DisputeRecord.evidence_refs exceeds the bounded cap")


__all__ = [
    "CRITERION_WEIGHTS",
    "AssessmentRecord",
    "AssessmentState",
    "AssuranceCriterion",
    "AssuranceDecision",
    "AssuranceVerdict",
    "ConversationAssuranceEvaluator",
    "CriterionScore",
    "DebateContext",
    "DeterministicAssessment",
    "DisputeReason",
    "DisputeRecord",
    "EvaluatorOutput",
    "TurnAssessmentInput",
]
