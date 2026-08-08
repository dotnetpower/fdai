from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.conversation_assurance import (
    AccuracyPosterior,
    AssessmentRecord,
    AssuranceDecision,
    AssuranceVerdict,
    ChatPolicyCandidate,
    ChatPolicyTarget,
    DisputeReason,
    DisputeRecord,
    InMemoryConversationAssuranceLedger,
    InMemoryConversationPolicyCandidateStore,
    PolicyStage,
    PolicyTransition,
    PolicyTrialMetrics,
    PromotionConfig,
    cluster_failures,
    evaluate_policy_transition,
)


def _assessment(identifier: str, verdict: AssuranceVerdict) -> AssessmentRecord:
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
            verdict=verdict,
            content_score=0.0 if verdict is AssuranceVerdict.FAIL else 100.0,
            confidence=1.0,
            reasons=("verification_failed",) if verdict is AssuranceVerdict.FAIL else (),
        ),
        assessed_at=datetime(2026, 7, 31, tzinfo=UTC),
    )


async def test_ledger_is_idempotent_and_principal_scoped() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    record = _assessment("assessment-1", AssuranceVerdict.PASS)

    assert await ledger.append_assessment(record)
    assert not await ledger.append_assessment(record)
    assert (
        await ledger.get_assessment(
            principal_scope="principal-2", assessment_id=record.assessment_id
        )
        is None
    )


async def test_dispute_requires_matching_scope() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    await ledger.append_assessment(_assessment("assessment-1", AssuranceVerdict.FAIL))
    dispute = DisputeRecord(
        dispute_id="dispute-1",
        assessment_id="assessment-1",
        principal_scope="principal-2",
        reported_by="operator-1",
        reason=DisputeReason.WRONG_FACT,
        detail="The answer used an incorrect resource state.",
        evidence_refs=(),
        reported_at=datetime(2026, 7, 31, tzinfo=UTC),
    )

    with pytest.raises(LookupError, match="principal scope"):
        await ledger.append_dispute(dispute)


def test_posterior_variance_decreases_with_evidence() -> None:
    prior = AccuracyPosterior(alpha=1.0, beta=1.0)
    posterior = prior
    for _ in range(20):
        posterior = posterior.observe(correct=True)

    assert posterior.mean > prior.mean
    assert posterior.variance < prior.variance


def test_repeated_failures_form_one_bounded_cluster() -> None:
    records = tuple(_assessment(f"assessment-{index}", AssuranceVerdict.FAIL) for index in range(4))

    clusters = cluster_failures(records, min_samples=3)

    assert len(clusters) == 1
    assert clusters[0].sample_count == 4


def test_failure_clusters_do_not_combine_principal_scopes() -> None:
    first = _assessment("assessment-1", AssuranceVerdict.FAIL)
    second = replace(
        _assessment("assessment-2", AssuranceVerdict.FAIL),
        principal_scope="principal-2",
    )

    assert cluster_failures((first, second), min_samples=2) == ()


def _candidate(stage: PolicyStage = PolicyStage.SHADOW) -> ChatPolicyCandidate:
    policy_text = "Improve answer calibration without changing evidence or authority."
    return ChatPolicyCandidate(
        candidate_id="candidate-1",
        principal_scope="principal-1",
        cluster_id="cluster-1",
        target=ChatPolicyTarget.NARRATOR_PROMPT,
        policy_digest=hashlib.sha256(policy_text.encode()).hexdigest(),
        incumbent_policy_digest="i" * 64,
        policy_text=policy_text,
        stage=stage,
    )


def test_policy_candidate_rejects_artifact_digest_mismatch() -> None:
    with pytest.raises(ValueError, match="match policy_digest"):
        ChatPolicyCandidate(
            candidate_id="candidate-mismatch",
            principal_scope="principal-1",
            cluster_id="cluster-1",
            target=ChatPolicyTarget.NARRATOR_PROMPT,
            policy_digest="a" * 64,
            incumbent_policy_digest="i" * 64,
            policy_text="A different policy artifact.",
        )


def test_legacy_digest_only_candidate_remains_readable_in_shadow() -> None:
    candidate = ChatPolicyCandidate(
        candidate_id="candidate-legacy",
        principal_scope="principal-1",
        cluster_id="cluster-1",
        target=ChatPolicyTarget.NARRATOR_PROMPT,
        policy_digest="a" * 64,
        incumbent_policy_digest="i" * 64,
    )

    assert candidate.policy_text is None
    assert candidate.stage is PolicyStage.SHADOW


def _metrics(**overrides: object) -> PolicyTrialMetrics:
    values: dict[str, object] = {
        "observed_stage": PolicyStage.SHADOW,
        "evidence_digest": "e" * 64,
        "sample_count": 100,
        "score_delta_lcb95": 1.0,
        "hard_failure_escapes": 0,
        "candidate_cost_per_verified_microusd": 9.0,
        "incumbent_cost_per_verified_microusd": 10.0,
        "latency_delta_ms": 0.0,
        "locale_gap_delta": 0.0,
        "disagreement_rate_delta": 0.0,
    }
    values.update(overrides)
    return PolicyTrialMetrics(**values)  # type: ignore[arg-type]


def test_policy_advances_one_stage_after_guards_pass() -> None:
    transition = evaluate_policy_transition(_candidate(), _metrics())

    assert transition.to_stage is PolicyStage.CANARY_1


def test_policy_requires_statistically_positive_gain_by_default() -> None:
    transition = evaluate_policy_transition(
        _candidate(),
        _metrics(score_delta_lcb95=0.0),
    )

    assert transition.to_stage is PolicyStage.ROLLED_BACK
    assert transition.reasons == ("score_regression",)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_samples": 0},
        {"min_score_delta_lcb95": 0.0},
        {"max_latency_delta_ms": -1.0},
        {"max_locale_gap_delta": 1.1},
        {"max_disagreement_rate_delta": 1.1},
    ],
)
def test_invalid_promotion_thresholds_fail_at_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="promotion"):
        PromotionConfig(**kwargs)  # type: ignore[arg-type]


async def test_candidate_store_scopes_and_replays_transitions() -> None:
    store = InMemoryConversationPolicyCandidateStore()
    candidate = _candidate()
    transition = evaluate_policy_transition(candidate, _metrics())

    assert await store.append_candidate(candidate)
    assert not await store.append_candidate(candidate)
    assert (
        await store.get_candidate(
            principal_scope="principal-2",
            candidate_id=candidate.candidate_id,
        )
        is None
    )
    updated = await store.apply_transition(
        principal_scope=candidate.principal_scope,
        transition=transition,
    )
    replayed = await store.apply_transition(
        principal_scope=candidate.principal_scope,
        transition=transition,
    )

    assert updated.stage is PolicyStage.CANARY_1
    assert replayed == updated
    assert await store.list_transitions(
        principal_scope=candidate.principal_scope,
        candidate_id=candidate.candidate_id,
    ) == (transition,)


async def test_candidate_store_rejects_stale_transition() -> None:
    store = InMemoryConversationPolicyCandidateStore()
    candidate = _candidate()
    await store.append_candidate(candidate)
    advanced = evaluate_policy_transition(candidate, _metrics())
    await store.apply_transition(
        principal_scope=candidate.principal_scope,
        transition=advanced,
    )

    with pytest.raises(ValueError, match="from_stage is stale"):
        await store.apply_transition(
            principal_scope=candidate.principal_scope,
            transition=PolicyTransition(
                candidate_id=candidate.candidate_id,
                from_stage=PolicyStage.SHADOW,
                to_stage=PolicyStage.ROLLED_BACK,
                reasons=("late_guard",),
                evidence_digest="f" * 64,
            ),
        )


async def test_candidate_store_rejects_reused_trial_evidence() -> None:
    store = InMemoryConversationPolicyCandidateStore()
    candidate = _candidate()
    await store.append_candidate(candidate)
    first = evaluate_policy_transition(candidate, _metrics())
    advanced = await store.apply_transition(
        principal_scope=candidate.principal_scope,
        transition=first,
    )
    reused = evaluate_policy_transition(
        advanced,
        _metrics(observed_stage=PolicyStage.CANARY_1),
    )

    with pytest.raises(ValueError, match="evidence was already consumed"):
        await store.apply_transition(
            principal_scope=candidate.principal_scope,
            transition=reused,
        )


def test_measurement_stage_mismatch_cannot_advance() -> None:
    transition = evaluate_policy_transition(
        _candidate(PolicyStage.CANARY_5),
        _metrics(),
    )

    assert transition.from_stage is PolicyStage.CANARY_5
    assert transition.to_stage is PolicyStage.CANARY_5
    assert transition.reasons == ("measurement_stage_mismatch",)


@pytest.mark.parametrize(
    "overrides",
    [
        {"hard_failure_escapes": 1},
        {"score_delta_lcb95": -0.1},
        {"candidate_cost_per_verified_microusd": 11.0},
        {"latency_delta_ms": 251.0},
        {"locale_gap_delta": 0.03},
        {"disagreement_rate_delta": 0.03},
    ],
)
def test_any_guard_breach_rolls_back(overrides: dict[str, object]) -> None:
    transition = evaluate_policy_transition(
        _candidate(PolicyStage.CANARY_5),
        _metrics(observed_stage=PolicyStage.CANARY_5, **overrides),
    )

    assert transition.to_stage is PolicyStage.ROLLED_BACK
