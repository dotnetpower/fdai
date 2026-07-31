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

_PASS_THRESHOLD = 3
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

    async def review(self, turn: TurnAssessmentInput) -> AssuranceDecision:
        evaluator_identities = {
            self._first.model_identity,
            self._second.model_identity,
        }
        if self._tie_breaker is not None:
            evaluator_identities.add(self._tie_breaker.model_identity)
        if turn.answer_model_identity in evaluator_identities:
            return _inconclusive("answer_model_cannot_self_evaluate")
        if not await self._reserve(turn.turn_id, calls=2):
            return _inconclusive("model_budget_deferred")
        try:
            first, second = await asyncio.gather(
                self._first.evaluate(turn),
                self._second.evaluate(turn),
            )
        except Exception as exc:  # noqa: BLE001 - off-path review fails closed
            return _inconclusive(f"evaluator_error:{type(exc).__name__}")
        invalid = _validate_outputs(turn, (first, second))
        if invalid is not None:
            return _inconclusive(invalid, outputs=(first, second))
        first_verdict = _verdict(first)
        second_verdict = _verdict(second)
        disputed = _disputed_criteria(first, second)
        if first_verdict is second_verdict and not disputed:
            return _decision_from_outputs((first, second), disagreement=False)
        if self._tie_breaker is None:
            reason = (
                "model_verdict_disagreement"
                if first_verdict is not second_verdict
                else "model_criterion_disagreement"
            )
            return _inconclusive(reason, outputs=(first, second))
        if not await self._reserve(turn.turn_id, calls=1):
            return _inconclusive("model_budget_deferred", outputs=(first, second))
        try:
            tie_output = await self._tie_breaker.evaluate(
                turn,
                debate=DebateContext(first, second, disputed),
            )
        except Exception as exc:  # noqa: BLE001 - bounded tie-break fails closed
            return _inconclusive(
                f"tie_breaker_error:{type(exc).__name__}",
                outputs=(first, second),
            )
        invalid = _validate_outputs(turn, (tie_output,))
        if invalid is not None:
            return _inconclusive(invalid, outputs=(first, second, tie_output))
        return _decision_from_outputs((first, second, tie_output), disagreement=True)

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
    )


def _content_score(scores: tuple[CriterionScore, ...]) -> float:
    numerator = sum(CRITERION_WEIGHTS[item.criterion] * item.score for item in scores)
    denominator = 4 * sum(CRITERION_WEIGHTS.values())
    return 100.0 * numerator / denominator


def _inconclusive(
    reason: str,
    *,
    outputs: tuple[EvaluatorOutput, ...] = (),
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
    )


__all__ = ["MixedFamilyAssuranceReviewer"]
