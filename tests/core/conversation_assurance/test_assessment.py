from __future__ import annotations

from dataclasses import dataclass

import pytest

from fdai.core.conversation_assurance import (
    AssuranceCriterion,
    AssuranceVerdict,
    ConversationAssuranceCoordinator,
    CriterionScore,
    DebateContext,
    EvaluatorOutput,
    InMemoryConversationAssuranceLedger,
    MixedFamilyAssuranceReviewer,
    TurnAssessmentInput,
    assess_deterministically,
)
from fdai.core.metering.budget import InMemoryBudgetLedger, ModelBudget


def _turn(**overrides: object) -> TurnAssessmentInput:
    values: dict[str, object] = {
        "turn_id": "turn-1",
        "conversation_id": "conversation-1",
        "principal_scope": "principal-scope",
        "question": "What changed?",
        "answer": "One verified resource changed.",
        "question_digest": "q" * 64,
        "answer_digest": "a" * 64,
        "evidence_manifest_digest": "e" * 64,
        "evidence_refs": ("evidence:1",),
        "verification_status": "verified",
        "verification_authority": "server_inventory_graph",
        "checks_completed": 1,
        "checks_total": 1,
    }
    values.update(overrides)
    return TurnAssessmentInput(**values)  # type: ignore[arg-type]


def _scores(
    value: int,
    *,
    evidence_ref: str = "evidence:1",
    rationale: str = "Supported by the supplied evidence.",
) -> tuple[CriterionScore, ...]:
    return tuple(
        CriterionScore(
            criterion=criterion,
            score=value,
            rationale=rationale,
            evidence_refs=(evidence_ref,),
        )
        for criterion in AssuranceCriterion
    )


@dataclass
class _Evaluator:
    model_identity: str
    model_family: str
    score: int
    rationale: str = "Supported by the supplied evidence."
    prospective_cost_microusd: int = 2
    calls: int = 0
    saw_debate: bool = False

    async def evaluate(
        self,
        turn: TurnAssessmentInput,  # noqa: ARG002
        *,
        debate: DebateContext | None = None,
    ) -> EvaluatorOutput:
        self.calls += 1
        self.saw_debate = debate is not None
        return EvaluatorOutput(
            model_identity=self.model_identity,
            model_family=self.model_family,
            scores=_scores(self.score, rationale=self.rationale),
            prompt_tokens=10,
            completion_tokens=5,
            cost_microusd=2,
        )


def test_deterministic_verified_answer_skips_semantic_review() -> None:
    result = assess_deterministically(_turn(deterministic_answer=True))

    assert result.verdict is AssuranceVerdict.PASS
    assert not result.needs_semantic_review


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"evidence_refs": ()}, "evidence_manifest_empty"),
        ({"verification_authority": "unavailable"}, "verification_authority_unavailable"),
    ],
)
def test_deterministic_answer_requires_terminal_evidence(
    overrides: dict[str, object],
    reason: str,
) -> None:
    result = assess_deterministically(_turn(deterministic_answer=True, **overrides))

    assert result.verdict is AssuranceVerdict.INCONCLUSIVE
    assert result.reasons == (reason,)


def test_deterministic_failed_claim_fails() -> None:
    result = assess_deterministically(_turn(failed_claim_ids=("claim-1",)))

    assert result.verdict is AssuranceVerdict.FAIL


def test_deterministic_unverified_preserves_exact_reason() -> None:
    result = assess_deterministically(
        _turn(
            verification_status="unverified",
            verification_reason_code="unknown_link_type",
        )
    )

    assert result.verdict is AssuranceVerdict.FAIL
    assert result.reasons == ("verification_failed:unknown_link_type",)


async def test_mixed_family_consensus_passes_conservatively() -> None:
    first = _Evaluator("publisher-a:model-a", "family-a", 4, "Fully supported.")
    second = _Evaluator("publisher-b:model-b", "family-b", 3, "Minor support gap.")
    reviewer = MixedFamilyAssuranceReviewer(first=first, second=second)

    decision = await reviewer.review(_turn())

    assert decision.verdict is AssuranceVerdict.PASS
    assert decision.model_calls == 2
    assert decision.content_score == 75.0
    assert decision.cost_microusd == 4
    assert {item.rationale for item in decision.criteria} == {"Minor support gap."}


async def test_disagreement_uses_one_independent_tie_break() -> None:
    first = _Evaluator("publisher-a:model-a", "family-a", 4)
    second = _Evaluator("publisher-b:model-b", "family-b", 1)
    tie = _Evaluator("publisher-c:model-c", "family-c", 3)
    reviewer = MixedFamilyAssuranceReviewer(
        first=first,
        second=second,
        tie_breaker=tie,
    )

    decision = await reviewer.review(_turn())

    assert tie.saw_debate
    assert decision.verdict is AssuranceVerdict.FAIL
    assert decision.disagreement
    assert decision.model_calls == 3


async def test_unsupported_evidence_fails_closed() -> None:
    first = _Evaluator("publisher-a:model-a", "family-a", 4)
    second = _Evaluator("publisher-b:model-b", "family-b", 4)
    original = second.evaluate

    async def unsupported(
        turn: TurnAssessmentInput,
        *,
        debate: DebateContext | None = None,
    ) -> EvaluatorOutput:
        output = await original(turn, debate=debate)
        return EvaluatorOutput(
            model_identity=output.model_identity,
            model_family=output.model_family,
            scores=_scores(4, evidence_ref="fabricated:1"),
        )

    second.evaluate = unsupported  # type: ignore[method-assign]
    reviewer = MixedFamilyAssuranceReviewer(first=first, second=second)

    decision = await reviewer.review(_turn())

    assert decision.verdict is AssuranceVerdict.INCONCLUSIVE
    assert decision.reasons == ("unsupported_evidence_ref",)


def test_reviewer_rejects_same_family() -> None:
    first = _Evaluator("publisher-a:model-a", "family-a", 4)
    second = _Evaluator("publisher-b:model-b", "family-a", 4)

    with pytest.raises(ValueError, match="families MUST be distinct"):
        MixedFamilyAssuranceReviewer(first=first, second=second)


async def test_answer_model_cannot_grade_itself() -> None:
    first = _Evaluator("publisher-a:model-a", "family-a", 4)
    second = _Evaluator("publisher-b:model-b", "family-b", 4)
    reviewer = MixedFamilyAssuranceReviewer(first=first, second=second)

    decision = await reviewer.review(_turn(answer_model_identity="publisher-a:model-a"))

    assert decision.verdict is AssuranceVerdict.INCONCLUSIVE
    assert first.calls == 0
    assert second.calls == 0


async def test_answer_model_cannot_be_configured_as_tie_breaker() -> None:
    first = _Evaluator("publisher-a:model-a", "family-a", 4)
    second = _Evaluator("publisher-b:model-b", "family-b", 4)
    tie = _Evaluator("publisher-c:model-c", "family-c", 4)
    reviewer = MixedFamilyAssuranceReviewer(first=first, second=second, tie_breaker=tie)

    decision = await reviewer.review(_turn(answer_model_identity="publisher-c:model-c"))

    assert decision.verdict is AssuranceVerdict.INCONCLUSIVE
    assert first.calls == second.calls == tie.calls == 0


async def test_budget_is_reserved_before_evaluators_run() -> None:
    first = _Evaluator("publisher-a:model-a", "family-a", 4)
    second = _Evaluator("publisher-b:model-b", "family-b", 4)
    reviewer = MixedFamilyAssuranceReviewer(
        first=first,
        second=second,
        budget=InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=1)),
    )

    decision = await reviewer.review(_turn())

    assert decision.reasons == ("model_budget_deferred",)
    assert first.calls == 0
    assert second.calls == 0


async def test_coordinator_caches_deterministic_assessment() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    coordinator = ConversationAssuranceCoordinator(
        ledger=ledger,
        reviewer=None,
        rubric_version="1.0.0",
    )
    turn = _turn(deterministic_answer=True)

    first = await coordinator.assess(turn)
    second = await coordinator.assess(turn)

    assert first == second
    assert first.decision.verdict is AssuranceVerdict.PASS
    assert len(await ledger.list_assessments(principal_scope="principal-scope")) == 1
