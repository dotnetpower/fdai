"""Default-off verified answer authoring over a P0 model evidence view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fdai_service_contracts.answer_claims import ComposedAnswer

from fdai.core.conversation.model_evidence_view import ModelEvidenceView
from fdai.core.conversation.semantic_reasoning_claims import (
    ClaimVerdict,
    GoalEvidence,
    verify_answer_claims,
)


class VerifiedAnswerAuthor(Protocol):
    """Model-backed author port; production binding remains default-off."""

    family: str

    async def author(
        self,
        *,
        utterance: str,
        evidence_view: ModelEvidenceView,
        retry_reasons: tuple[str, ...] = (),
    ) -> ComposedAnswer | None: ...


class VerifiedAnswerReviewer(Protocol):
    """Independent entailment reviewer port over the same P0 view."""

    family: str

    async def review(
        self,
        *,
        answer: ComposedAnswer,
        evidence_view: ModelEvidenceView,
    ) -> bool | None:
        """Return whether every claim follows from its evidence; ``None`` when unavailable."""
        ...


@dataclass(frozen=True, slots=True)
class VerifiedAnswerAuthoringResult:
    answer: ComposedAnswer | None
    verdict: ClaimVerdict | None
    held_reason: str | None = None
    attempts: int = 0


class VerifiedAnswerAuthoringService:
    """Author, V-CLAIM, review, retry once, then hold fail-closed."""

    def __init__(self, *, author: VerifiedAnswerAuthor, reviewer: VerifiedAnswerReviewer) -> None:
        if not author.family.strip() or not reviewer.family.strip():
            raise ValueError("verified answer model families MUST be non-empty")
        if author.family.strip().casefold() == reviewer.family.strip().casefold():
            raise ValueError("verified answer author and reviewer families MUST differ")
        self._author = author
        self._reviewer = reviewer

    async def author_answer(
        self,
        *,
        utterance: str,
        evidence_view: ModelEvidenceView,
        evidence: tuple[GoalEvidence, ...],
        known_identities: frozenset[str] = frozenset(),
    ) -> VerifiedAnswerAuthoringResult:
        retry_reasons: tuple[str, ...] = ()
        last_verdict: ClaimVerdict | None = None
        held = "verified_answer_review_rejected"
        for attempt in (1, 2):
            answer = await self._author.author(
                utterance=utterance,
                evidence_view=evidence_view,
                retry_reasons=retry_reasons,
            )
            if answer is None:
                return VerifiedAnswerAuthoringResult(
                    None, last_verdict, "answer_author_unavailable", attempt
                )
            verdict = verify_answer_claims(
                answer,
                evidence=evidence,
                utterance=utterance,
                known_identities=known_identities,
            )
            last_verdict = verdict
            if not verdict.accepted:
                retry_reasons, held = verdict.violations, "verified_answer_claims_rejected"
                continue
            reviewed = await self._reviewer.review(answer=answer, evidence_view=evidence_view)
            if reviewed is None:
                # No reviewer reading is not a pass; the answer holds with the evidence view.
                return VerifiedAnswerAuthoringResult(
                    None, verdict, "entailment_review_unavailable", attempt
                )
            if reviewed:
                return VerifiedAnswerAuthoringResult(answer, verdict, attempts=attempt)
            retry_reasons, held = ("entailment_rejected",), "verified_answer_review_rejected"
        return VerifiedAnswerAuthoringResult(None, last_verdict, held, 2)


__all__ = [
    "VerifiedAnswerAuthor",
    "VerifiedAnswerAuthoringResult",
    "VerifiedAnswerAuthoringService",
    "VerifiedAnswerReviewer",
]
