"""Bounded admission for generated conversation-assurance questions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from scripts.automation.conversation_assurance_question_contract import (
    TypedQuestionContract,
    reduce_semantic_equivalence,
    wording_proposal,
)

_MAX_GENERATION_ATTEMPTS = 3
_MAX_QUESTION_CHARS = 400

ProposalProvider = Callable[[int], object]
SemanticReviewer = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class QuestionAdmissionDecision:
    """Typed boundary between generated wording and the evaluation ledger."""

    challenge_id: str
    locale: str
    questions: tuple[str, ...]
    attempts: int
    rejection_reasons: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        """Return whether this decision admits questions for evaluation."""

        return bool(self.questions)


def admit_generated_question(
    *,
    challenge_id: str,
    contract: TypedQuestionContract,
    locale: str,
    attempts: int,
    propose: ProposalProvider,
    review: SemanticReviewer,
    prior_questions: tuple[str, ...] = (),
) -> QuestionAdmissionDecision:
    """Admit one wording-only proposal after bounded independent review."""

    _validate_attempts(attempts)
    prior = {_question_fingerprint(question) for question in prior_questions}
    rejections: list[str] = []
    for attempt in range(attempts):
        payload = propose(attempt)
        if not isinstance(payload, Mapping):
            rejections.append("invalid_generation_payload")
            continue
        question = wording_proposal(payload, challenge_id=challenge_id, locale=locale)
        if question is None:
            rejections.append("invalid_generation_payload")
            continue
        if not 8 <= len(question) <= _MAX_QUESTION_CHARS:
            rejections.append("question_length_out_of_bounds")
            continue
        if _question_fingerprint(question) in prior:
            rejections.append("duplicate_question")
            continue
        semantic = reduce_semantic_equivalence(
            review(question),
            expected=contract,
            expected_locale=locale,
        )
        if not semantic.accepted:
            rejections.append(semantic.reason)
            continue
        return QuestionAdmissionDecision(
            challenge_id=challenge_id,
            locale=locale,
            questions=(question,),
            attempts=attempt + 1,
            rejection_reasons=tuple(rejections),
        )
    return QuestionAdmissionDecision(
        challenge_id=challenge_id,
        locale=locale,
        questions=(),
        attempts=attempts,
        rejection_reasons=tuple(rejections),
    )


def admit_paraphrase_cohort(
    *,
    challenge_id: str,
    contract: TypedQuestionContract,
    locale: str,
    original_question: str,
    attempts: int,
    propose: ProposalProvider,
    review: SemanticReviewer,
    prior_questions: tuple[str, ...] = (),
    minimum_questions: int = 3,
    maximum_questions: int = 5,
) -> QuestionAdmissionDecision:
    """Admit an entire paraphrase cohort or fail closed without a partial cohort."""

    _validate_attempts(attempts)
    if not 3 <= minimum_questions <= maximum_questions <= 5:
        raise ValueError("paraphrase cohort bounds MUST be between 3 and 5")
    excluded = {
        _question_fingerprint(question) for question in (*prior_questions, original_question)
    }
    rejections: list[str] = []
    for attempt in range(attempts):
        payload = propose(attempt)
        questions = _cohort_questions(
            payload,
            challenge_id=challenge_id,
            excluded=excluded,
            minimum_questions=minimum_questions,
            maximum_questions=maximum_questions,
        )
        if questions is None:
            rejections.append("invalid_paraphrase_cohort")
            continue
        rejected_reason = _cohort_review_rejection(
            questions,
            contract=contract,
            locale=locale,
            review=review,
        )
        if rejected_reason is not None:
            rejections.append(rejected_reason)
            continue
        return QuestionAdmissionDecision(
            challenge_id=challenge_id,
            locale=locale,
            questions=questions,
            attempts=attempt + 1,
            rejection_reasons=tuple(rejections),
        )
    return QuestionAdmissionDecision(
        challenge_id=challenge_id,
        locale=locale,
        questions=(),
        attempts=attempts,
        rejection_reasons=tuple(rejections),
    )


def persist_admitted_questions[T](
    decision: QuestionAdmissionDecision,
    write_evaluation: Callable[[str], T],
) -> tuple[T, ...]:
    """Write only independently admitted questions to the normal evaluation ledger."""

    if not decision.accepted:
        return ()
    return tuple(write_evaluation(question) for question in decision.questions)


def _cohort_questions(
    payload: object,
    *,
    challenge_id: str,
    excluded: set[str],
    minimum_questions: int,
    maximum_questions: int,
) -> tuple[str, ...] | None:
    if not isinstance(payload, Mapping) or set(payload) != {"challenge_id", "questions"}:
        return None
    values = payload.get("questions")
    if payload.get("challenge_id") != challenge_id or not isinstance(values, list):
        return None
    if not minimum_questions <= len(values) <= maximum_questions:
        return None
    questions: list[str] = []
    fingerprints = set(excluded)
    for value in values:
        if not isinstance(value, str):
            return None
        question = _normalize_question(value)
        fingerprint = question.casefold()
        if not 8 <= len(question) <= _MAX_QUESTION_CHARS or fingerprint in fingerprints:
            return None
        fingerprints.add(fingerprint)
        questions.append(question)
    return tuple(questions)


def _cohort_review_rejection(
    questions: tuple[str, ...],
    *,
    contract: TypedQuestionContract,
    locale: str,
    review: SemanticReviewer,
) -> str | None:
    for question in questions:
        semantic = reduce_semantic_equivalence(
            review(question),
            expected=contract,
            expected_locale=locale,
        )
        if not semantic.accepted:
            return semantic.reason
    return None


def _validate_attempts(attempts: int) -> None:
    if not 1 <= attempts <= _MAX_GENERATION_ATTEMPTS:
        raise ValueError("generation attempts MUST be between 1 and 3")


def _normalize_question(question: str) -> str:
    return " ".join(question.split())


def _question_fingerprint(question: str) -> str:
    return _normalize_question(question).casefold()


__all__ = [
    "QuestionAdmissionDecision",
    "admit_generated_question",
    "admit_paraphrase_cohort",
    "persist_admitted_questions",
]
