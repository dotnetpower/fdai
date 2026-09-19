"""Bounded mixed-family semantic review for conversation assurance."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable

from fdai.core.conversation_assurance.models import (
    CRITERION_WEIGHTS,
    AssuranceCriterion,
    AssuranceDecision,
    AssuranceVerdict,
    ConversationAssuranceEvaluator,
    CriterionScore,
    DebateContext,
    EvaluatorOutput,
    TurnAssessmentInput,
)
from fdai.core.metering.budget import BudgetLedger
from fdai.core.prompts.profiles import PromptRequestBudgetExceededError
from fdai.core.prompts.types import PromptProfileEvidence

_PASS_THRESHOLD = 3
_MINIMUM_CONFIDENCE = 0.85
_REQUIRED_CRITERIA = frozenset(AssuranceCriterion)


class MixedFamilyAssuranceReviewer:
    """Run two independent evaluators and one optional bounded tie-break."""

    def __init__(
        self,
        *,
        first: ConversationAssuranceEvaluator,
        second: ConversationAssuranceEvaluator,
        tie_breaker: ConversationAssuranceEvaluator | None = None,
        budget: BudgetLedger | None = None,
        prospective_cost_microusd_per_call: int = 0,
    ) -> None:
        evaluators = (first, second) + ((tie_breaker,) if tie_breaker is not None else ())
        identities = {item.model_identity for item in evaluators}
        families = {item.model_family for item in evaluators}
        if len(identities) != len(evaluators):
            raise ValueError("assurance evaluator identities MUST be distinct")
        if len(families) != len(evaluators):
            raise ValueError("assurance evaluator families MUST be distinct")
        if prospective_cost_microusd_per_call < 0:
            raise ValueError("prospective model cost MUST be non-negative")
        self._first = first
        self._second = second
        self._tie_breaker = tie_breaker
        self._budget = budget
        self._prospective_cost_microusd_per_call = prospective_cost_microusd_per_call

    @property
    def model_set_digest(self) -> str:
        identities: tuple[str, ...] = (
            self._first.model_identity,
            self._second.model_identity,
        )
        if self._tie_breaker is not None:
            identities += (self._tie_breaker.model_identity,)
        return hashlib.sha256("\0".join(identities).encode()).hexdigest()

    @property
    def evaluator_models(self) -> tuple[tuple[str, str], ...]:
        """Return configured evaluator identity and family pairs in call order."""

        evaluators = (self._first, self._second) + (
            (self._tie_breaker,) if self._tie_breaker is not None else ()
        )
        return tuple((item.model_identity, item.model_family) for item in evaluators)

    async def review(self, turn: TurnAssessmentInput) -> AssuranceDecision:
        """Return the reduced decision while preserving the historical API."""

        decision, _outputs = await self.review_with_outputs(turn)
        return decision

    async def review_with_outputs(
        self,
        turn: TurnAssessmentInput,
    ) -> tuple[AssuranceDecision, tuple[EvaluatorOutput, ...]]:
        """Return the decision and independently validated atomic outputs."""

        evaluator_identities = {
            self._first.model_identity,
            self._second.model_identity,
        }
        if self._tie_breaker is not None:
            evaluator_identities.add(self._tie_breaker.model_identity)
        evaluator_families = {
            self._first.model_family,
            self._second.model_family,
        }
        if self._tie_breaker is not None:
            evaluator_families.add(self._tie_breaker.model_family)
        if (
            turn.answer_model_identity in evaluator_identities
            or turn.answer_model_family in evaluator_families
        ):
            return _inconclusive("answer_model_cannot_self_evaluate"), ()
        if not await self._reserve(turn.turn_id, calls=2):
            return _inconclusive("model_budget_deferred"), ()
        tasks = (
            asyncio.create_task(self._first.evaluate(turn)),
            asyncio.create_task(self._second.evaluate(turn)),
        )
        try:
            first, second = await asyncio.gather(*tasks)
        except Exception as exc:  # noqa: BLE001 - off-path review fails closed
            for task in tasks:
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            completed = tuple(result for result in results if isinstance(result, EvaluatorOutput))
            return (
                _inconclusive(
                    _evaluator_error_reason(exc),
                    outputs=completed,
                    failure_profile_evidence=_failure_profile_evidence(results),
                ),
                completed,
            )
        primary_outputs = (first, second)
        invalid = _validate_outputs(turn, (first, second))
        if invalid is not None:
            return _inconclusive(invalid, outputs=primary_outputs), primary_outputs
        first_verdict = _verdict(first)
        second_verdict = _verdict(second)
        disputed = _disputed_criteria(first, second)
        if first_verdict is second_verdict and not disputed:
            return (
                _decision_from_outputs(primary_outputs, disagreement=False),
                primary_outputs,
            )
        if self._tie_breaker is None:
            reason = (
                "model_verdict_disagreement"
                if first_verdict is not second_verdict
                else "model_criterion_disagreement"
            )
            return _inconclusive(reason, outputs=primary_outputs), primary_outputs
        if not await self._reserve(turn.turn_id, calls=1):
            return (
                _inconclusive("model_budget_deferred", outputs=primary_outputs),
                primary_outputs,
            )
        try:
            tie_output = await self._tie_breaker.evaluate(
                turn,
                debate=DebateContext(first, second, disputed),
            )
        except Exception as exc:  # noqa: BLE001 - bounded tie-break fails closed
            return (
                _inconclusive(
                    _evaluator_error_reason(exc, prefix="tie_breaker_error"),
                    outputs=primary_outputs,
                    failure_profile_evidence=_failure_profile_evidence((exc,)),
                ),
                primary_outputs,
            )
        all_outputs = (*primary_outputs, tie_output)
        invalid = _validate_outputs(turn, (tie_output,))
        if invalid is not None:
            return _inconclusive(invalid, outputs=all_outputs), all_outputs
        return _decision_from_outputs(all_outputs, disagreement=True), all_outputs

    async def _reserve(self, turn_id: str, *, calls: int) -> bool:
        if self._budget is None:
            return True
        return await self._budget.reserve(
            f"conversation-assurance:{turn_id}",
            calls=calls,
            cost_microusd=self._prospective_cost_microusd_per_call * calls,
        )


def _validate_outputs(
    turn: TurnAssessmentInput,
    outputs: Iterable[EvaluatorOutput],
) -> str | None:
    allowed_refs = set(turn.evidence_refs)
    for output in outputs:
        if output.confidence < _MINIMUM_CONFIDENCE:
            return "evaluator_confidence_below_threshold"
        criteria = [score.criterion for score in output.scores]
        if len(criteria) != len(set(criteria)):
            return "duplicate_criterion"
        if set(criteria) != _REQUIRED_CRITERIA:
            return "criterion_coverage_incomplete"
        if any(not set(score.evidence_refs).issubset(allowed_refs) for score in output.scores):
            return "unsupported_evidence_ref"
    return None


def _verdict(output: EvaluatorOutput) -> AssuranceVerdict:
    return (
        AssuranceVerdict.PASS
        if all(item.score >= _PASS_THRESHOLD for item in output.scores)
        else AssuranceVerdict.FAIL
    )


def _disputed_criteria(
    first: EvaluatorOutput,
    second: EvaluatorOutput,
) -> tuple[AssuranceCriterion, ...]:
    first_scores = {item.criterion: item.score for item in first.scores}
    second_scores = {item.criterion: item.score for item in second.scores}
    return tuple(
        criterion
        for criterion in AssuranceCriterion
        if abs(first_scores[criterion] - second_scores[criterion]) > 1
    )


def _decision_from_outputs(
    outputs: tuple[EvaluatorOutput, ...],
    *,
    disagreement: bool,
) -> AssuranceDecision:
    by_criterion = {
        criterion: tuple(
            next(score for score in output.scores if score.criterion is criterion)
            for output in outputs
        )
        for criterion in AssuranceCriterion
    }
    conservative_scores: list[CriterionScore] = []
    for criterion, scores in by_criterion.items():
        minimum = min(scores, key=lambda item: item.score)
        conservative_scores.append(
            CriterionScore(
                criterion=criterion,
                score=minimum.score,
                rationale=minimum.rationale,
                evidence_refs=minimum.evidence_refs,
            )
        )
    conservative = tuple(conservative_scores)
    verdict = (
        AssuranceVerdict.PASS
        if all(score.score >= _PASS_THRESHOLD for score in conservative)
        else AssuranceVerdict.FAIL
    )
    return AssuranceDecision(
        verdict=verdict,
        content_score=_content_score(conservative),
        confidence=1.0 if not disagreement else 2.0 / 3.0,
        criteria=conservative,
        reasons=("mixed_family_consensus",) if not disagreement else ("tie_break_completed",),
        evaluator_identities=tuple(output.model_identity for output in outputs),
        disagreement=disagreement,
        model_calls=len(outputs),
        prompt_tokens=sum(output.prompt_tokens for output in outputs),
        completion_tokens=sum(output.completion_tokens for output in outputs),
        cost_microusd=sum(output.cost_microusd for output in outputs),
        prompt_profile_evidence=tuple(
            output.prompt_profile_evidence
            for output in outputs
            if output.prompt_profile_evidence is not None
        ),
    )


def _content_score(scores: tuple[CriterionScore, ...]) -> float:
    numerator = sum(CRITERION_WEIGHTS[item.criterion] * item.score for item in scores)
    denominator = 4 * sum(CRITERION_WEIGHTS.values())
    return 100.0 * numerator / denominator


def _inconclusive(
    reason: str,
    *,
    outputs: tuple[EvaluatorOutput, ...] = (),
    failure_profile_evidence: tuple[PromptProfileEvidence, ...] = (),
) -> AssuranceDecision:
    return AssuranceDecision(
        verdict=AssuranceVerdict.INCONCLUSIVE,
        content_score=0.0,
        confidence=0.0,
        reasons=(reason,),
        evaluator_identities=tuple(output.model_identity for output in outputs),
        disagreement=reason == "model_disagreement",
        model_calls=len(outputs),
        prompt_tokens=sum(output.prompt_tokens for output in outputs),
        completion_tokens=sum(output.completion_tokens for output in outputs),
        cost_microusd=sum(output.cost_microusd for output in outputs),
        prompt_profile_evidence=tuple(
            output.prompt_profile_evidence
            for output in outputs
            if output.prompt_profile_evidence is not None
        )
        + failure_profile_evidence,
    )


def _failure_profile_evidence(
    results: Iterable[object],
) -> tuple[PromptProfileEvidence, ...]:
    return tuple(
        result.prompt_profile_evidence
        for result in results
        if isinstance(result, PromptRequestBudgetExceededError)
    )


def _evaluator_error_reason(exc: Exception, *, prefix: str = "evaluator_error") -> str:
    reason_code = getattr(exc, "assurance_reason_code", None)
    if (
        isinstance(reason_code, str)
        and 1 <= len(reason_code) <= 64
        and reason_code.isascii()
        and reason_code[0].isalpha()
        and all(
            character.islower() or character.isdigit() or character == "_"
            for character in reason_code
        )
    ):
        return f"{prefix}:{reason_code}"
    return f"{prefix}:{type(exc).__name__}"


__all__ = ["MixedFamilyAssuranceReviewer"]
