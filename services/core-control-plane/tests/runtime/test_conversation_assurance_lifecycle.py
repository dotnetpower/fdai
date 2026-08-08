from __future__ import annotations

import hashlib
from typing import Any

from fdai.core.conversation_assurance import (
    BASE_POLICY_DIGEST,
    AssuranceCriterion,
    ChatPolicyCandidate,
    ChatPolicyTarget,
    CriterionScore,
    DebateContext,
    EvaluatorOutput,
    FailureCluster,
    MixedFamilyAssuranceReviewer,
    PolicyStage,
    TurnAssessmentInput,
)
from fdai.core.metering.pricing import PricingTable
from fdai.runtime.conversation_assurance_lifecycle import (
    BLIND_CONVERSATION_SCENARIOS,
    BilingualBlindPolicyTrialMeasurer,
    DeterministicNarratorPolicyProposer,
    pricing_narrator_cost_estimator,
)


class _Runtime:
    async def current_digest(self, **_kwargs: object) -> str:
        return BASE_POLICY_DIGEST

    async def resolve(self, **_kwargs: object) -> None:
        return None


class _Backend:
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        del history
        improved = "_conversation_assurance_policy" in view_context
        answer = f"{'Better' if improved else 'Baseline'} grounded answer: {prompt}"
        return {
            "answer": answer,
            "model": "narrator-family",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


class _Evaluator:
    def __init__(self, identity: str, family: str, *, fail_locale: str | None = None) -> None:
        self.model_identity = identity
        self.model_family = family
        self.prospective_cost_microusd = 100
        self.fail_locale = fail_locale

    async def evaluate(
        self,
        turn: TurnAssessmentInput,
        *,
        debate: DebateContext | None = None,
    ) -> EvaluatorOutput:
        del debate
        answer = turn.answer
        score = 1 if turn.locale == self.fail_locale else 4 if answer.startswith("Better") else 3
        return EvaluatorOutput(
            model_identity=self.model_identity,
            model_family=self.model_family,
            scores=tuple(
                CriterionScore(
                    criterion=criterion,
                    score=score,
                    rationale="Scored against frozen reference facts.",
                )
                for criterion in AssuranceCriterion
            ),
            prompt_tokens=10,
            completion_tokens=5,
            cost_microusd=20,
        )


def _cluster() -> FailureCluster:
    return FailureCluster(
        cluster_id="cluster-1",
        principal_scope="principal-1",
        signature_digest="s" * 64,
        failed_criteria=(AssuranceCriterion.CALIBRATION,),
        reasons=("verification_failed",),
        sample_count=3,
        assessment_ids=("a", "b", "c"),
    )


async def test_proposer_maps_failure_to_bounded_artifact() -> None:
    proposal = await DeterministicNarratorPolicyProposer(runtime=_Runtime()).propose(_cluster())

    assert proposal.target is ChatPolicyTarget.NARRATOR_PROMPT
    assert proposal.incumbent_policy_digest == BASE_POLICY_DIGEST
    assert "abstain instead of guessing" in proposal.policy_text
    assert proposal.policy_digest == hashlib.sha256(proposal.policy_text.encode()).hexdigest()


async def test_blind_measurer_compares_bilingual_paired_answers() -> None:
    reviewer = MixedFamilyAssuranceReviewer(
        first=_Evaluator("judge-a", "family-a"),
        second=_Evaluator("judge-b", "family-b"),
        prospective_cost_microusd_per_call=100,
    )
    policy_text = "State uncertainty explicitly and abstain instead of guessing."
    candidate = ChatPolicyCandidate(
        candidate_id="candidate-1",
        principal_scope="principal-1",
        cluster_id="cluster-1",
        target=ChatPolicyTarget.NARRATOR_PROMPT,
        policy_digest=hashlib.sha256(policy_text.encode()).hexdigest(),
        incumbent_policy_digest=BASE_POLICY_DIGEST,
        policy_text=policy_text,
        stage=PolicyStage.SHADOW,
    )
    measurer = BilingualBlindPolicyTrialMeasurer(
        backend=_Backend(),
        reviewer=reviewer,
        cost_estimator=lambda _reply: 10,
    )

    metrics = await measurer.measure(candidate, _cluster())

    assert metrics is not None
    assert metrics.observed_stage is PolicyStage.SHADOW
    assert metrics.sample_count == len(BLIND_CONVERSATION_SCENARIOS)
    assert metrics.score_delta_lcb95 > 0.0
    assert metrics.hard_failure_escapes == 0
    assert metrics.candidate_cost_per_verified_microusd > 0.0
    assert metrics.locale_gap_delta == 0.0
    assert metrics.disagreement_rate_delta == 0.0


async def test_blind_measurer_requires_verified_answer_in_each_locale() -> None:
    reviewer = MixedFamilyAssuranceReviewer(
        first=_Evaluator("judge-a", "family-a", fail_locale="ko"),
        second=_Evaluator("judge-b", "family-b", fail_locale="ko"),
        prospective_cost_microusd_per_call=100,
    )
    policy_text = "State uncertainty explicitly and abstain instead of guessing."
    candidate = ChatPolicyCandidate(
        candidate_id="candidate-locale-gap",
        principal_scope="principal-1",
        cluster_id="cluster-1",
        target=ChatPolicyTarget.NARRATOR_PROMPT,
        policy_digest=hashlib.sha256(policy_text.encode()).hexdigest(),
        incumbent_policy_digest=BASE_POLICY_DIGEST,
        policy_text=policy_text,
        stage=PolicyStage.SHADOW,
    )
    measurer = BilingualBlindPolicyTrialMeasurer(
        backend=_Backend(),
        reviewer=reviewer,
        cost_estimator=lambda _reply: 10,
    )

    assert await measurer.measure(candidate, _cluster()) is None


def test_pricing_estimator_requires_usage_and_catalog_price() -> None:
    estimator = pricing_narrator_cost_estimator(
        PricingTable.from_mapping(
            {
                "narrator-family": {
                    "input_per_1k": "0.01",
                    "output_per_1k": "0.02",
                }
            }
        )
    )

    assert (
        estimator(
            {
                "model": "narrator-family",
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )
        == 2_000
    )
    assert estimator({"model": "narrator-family"}) is None
    assert (
        estimator(
            {
                "model": "unpriced-family",
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )
        is None
    )
