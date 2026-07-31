from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.conversation_assurance import (
    AssessmentRecord,
    AssuranceDecision,
    AssuranceVerdict,
    ChatPolicyCandidate,
    ChatPolicyProposal,
    ChatPolicyTarget,
    ConversationAssuranceLifecycleCoordinator,
    FailureCluster,
    InMemoryConversationPolicyCandidateStore,
    PolicyStage,
    PolicyTransition,
    PolicyTrialMetrics,
)


def _fail(identifier: str) -> AssessmentRecord:
    return AssessmentRecord(
        assessment_id=identifier,
        turn_id=f"turn-{identifier}",
        conversation_id="conversation-1",
        principal_scope="principal-1",
        question_digest="q" * 64,
        answer_digest="a" * 64,
        evidence_manifest_digest="e" * 64,
        rubric_version="1.0.0",
        model_set_digest="m" * 64,
        decision=AssuranceDecision(
            verdict=AssuranceVerdict.FAIL,
            content_score=0.0,
            confidence=1.0,
            reasons=("verification_failed",),
        ),
        assessed_at=datetime(2026, 7, 31, tzinfo=UTC),
    )


class _Proposer:
    async def propose(self, _cluster: FailureCluster) -> ChatPolicyProposal:
        return ChatPolicyProposal(
            target=ChatPolicyTarget.NARRATOR_PROMPT,
            policy_digest="p" * 64,
            incumbent_policy_digest="i" * 64,
        )


class _Measurer:
    async def measure(
        self,
        _candidate: ChatPolicyCandidate,
        _cluster: FailureCluster,
    ) -> PolicyTrialMetrics:
        return PolicyTrialMetrics(
            sample_count=100,
            score_delta_lcb95=1.0,
            hard_failure_escapes=0,
            candidate_cost_per_verified_microusd=9.0,
            incumbent_cost_per_verified_microusd=10.0,
            latency_delta_ms=0.0,
            locale_gap_delta=0.0,
            disagreement_rate_delta=0.0,
        )


class _Publisher:
    def __init__(self) -> None:
        self.published = 0
        self.restored = 0

    async def publish(
        self,
        _candidate: ChatPolicyCandidate,
        _transition: PolicyTransition,
    ) -> None:
        self.published += 1

    async def restore(
        self,
        _candidate: ChatPolicyCandidate,
        _transition: PolicyTransition,
    ) -> None:
        self.restored += 1


async def test_lifecycle_promotes_after_measured_publish() -> None:
    publisher = _Publisher()
    coordinator = ConversationAssuranceLifecycleCoordinator(
        store=InMemoryConversationPolicyCandidateStore(),
        proposer=_Proposer(),
        measurer=_Measurer(),
        publisher=publisher,
        min_cluster_samples=2,
    )

    (candidate,) = await coordinator.run((_fail("a"), _fail("b")))

    assert candidate.stage is PolicyStage.CANARY_1
    assert publisher.published == 1
    assert publisher.restored == 0


async def test_lifecycle_preserves_stage_across_repeated_candidate_proposal() -> None:
    publisher = _Publisher()
    coordinator = ConversationAssuranceLifecycleCoordinator(
        store=InMemoryConversationPolicyCandidateStore(),
        proposer=_Proposer(),
        measurer=_Measurer(),
        publisher=publisher,
        min_cluster_samples=2,
    )

    (first,) = await coordinator.run((_fail("a"), _fail("b")))
    (second,) = await coordinator.run((_fail("a"), _fail("b")))

    assert first.stage is PolicyStage.CANARY_1
    assert second.stage is PolicyStage.CANARY_5
    assert publisher.published == 2


class _FailingStore(InMemoryConversationPolicyCandidateStore):
    async def apply_transition(
        self,
        *,
        principal_scope: str,
        transition: PolicyTransition,
    ) -> ChatPolicyCandidate:
        raise RuntimeError("database unavailable")


async def test_lifecycle_restores_incumbent_when_transition_write_fails() -> None:
    publisher = _Publisher()
    coordinator = ConversationAssuranceLifecycleCoordinator(
        store=_FailingStore(),
        proposer=_Proposer(),
        measurer=_Measurer(),
        publisher=publisher,
        min_cluster_samples=2,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await coordinator.run((_fail("a"), _fail("b")))

    assert publisher.published == 1
    assert publisher.restored == 1
