"""Bounded question campaign runner tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.conversation.epistemic_coverage import EpistemicStatus
from fdai.core.conversation.question_campaign import (
    CampaignTurnEvidence,
    InMemoryQuestionCampaignLedger,
    QuestionCampaignState,
    QuestionCampaignTrigger,
    QuestionCaseAttemptRecord,
    build_question_campaign_identity,
)
from fdai.core.conversation.question_campaign_runner import (
    QuestionCampaignRunner,
    QuestionExecutionResult,
    QuestionGenerationInput,
)
from fdai.core.conversation.question_candidates import (
    QuestionCandidateGeneration,
    QuestionCandidateReview,
    QuestionModelUsage,
)
from fdai.core.conversation.question_novelty import InMemoryQuestionNoveltyLedger
from fdai.core.conversation.question_perspectives import (
    QuestionAnchorKind,
    QuestionCapabilityFamily,
    QuestionEvidencePosture,
    QuestionExpectedPosture,
    QuestionPerspective,
)
from fdai.core.conversation.question_universe import GeneratedQuestionCase, QuestionCaseClass
from fdai.core.conversation_assurance.models import (
    AssessmentRecord,
    AssessmentState,
    AssuranceDecision,
    AssuranceVerdict,
)

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 19, tzinfo=UTC)


def _case(case_id: str = "q:1") -> GeneratedQuestionCase:
    return GeneratedQuestionCase(
        case_id=case_id,
        principal_manifest_digest=DIGEST,
        declaration_id="object:Resource",
        declaration_digest=DIGEST,
        locale="en",
        case_class=QuestionCaseClass.POSITIVE,
        perspective=QuestionPerspective.RESOURCE,
        required_capability=QuestionCapabilityFamily.OBJECT_SET,
        evidence_posture=QuestionEvidencePosture.FRESH,
        anchor_kind=QuestionAnchorKind.SELECTED_OBJECT,
        expected_posture=QuestionExpectedPosture.ANSWER,
        action_posture="advise_only",
        path_depth=1,
        result_bound=20,
    )


def _identity(
    *,
    trigger: QuestionCampaignTrigger = QuestionCampaignTrigger.MANUAL,
    token_budget: int = 0,
    cost_budget_microusd: int = 0,
):
    return build_question_campaign_identity(
        source_revision="a" * 40,
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
        question_universe_digest=DIGEST,
        generation_profile_digest=DIGEST,
        model_set_digest=DIGEST,
        scope_digest=DIGEST,
        started_at=NOW,
        question_budget=20,
        time_budget_seconds=1_800,
        no_progress_seconds=300,
        token_budget=token_budget,
        cost_budget_microusd=cost_budget_microusd,
        trigger=trigger,
    )


class _Generator:
    model_family = "family-a"

    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid
        self.calls = 0

    @property
    def max_usage_per_call(self) -> QuestionModelUsage:
        return QuestionModelUsage(
            model_calls=1,
            prompt_tokens=10,
            completion_tokens=5,
            cost_microusd=7,
        )

    async def generate(self, *, case, descriptor, attempt_number, prior_fingerprints):
        self.calls += 1
        return QuestionCandidateGeneration(
            payload={
                "question": (
                    "What is the current state of the selected resource?" if self.valid else "short"
                ),
            },
            usage=QuestionModelUsage(
                model_calls=1,
                prompt_tokens=10,
                completion_tokens=5,
                cost_microusd=7,
            ),
        )


class _Reviewer:
    @property
    def max_usage_per_call(self) -> QuestionModelUsage:
        return QuestionModelUsage(model_calls=1)

    async def review(self, **_kwargs):
        return QuestionCandidateReview(
            reviewer_identity="reviewer-1",
            reviewer_family="family-b",
            equivalent=True,
            same_locale=True,
            same_result_shape=True,
            same_scope=True,
            same_evidence_authority=True,
            confidence=0.95,
            max_embedding_similarity=0.1,
        )


class _NoveltyReviewer(_Reviewer):
    async def review(self, **kwargs):
        review = await super().review(**kwargs)
        return replace(
            review,
            embedding_space_digest=DIGEST,
            embedding_model_version="embedding-v1",
            embedding_dimension=384,
            candidate_embedding_digest=DIGEST,
        )


class _ExpensiveReviewer(_Reviewer):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def max_usage_per_call(self) -> QuestionModelUsage:
        return QuestionModelUsage(
            model_calls=1,
            prompt_tokens=10,
            completion_tokens=0,
            cost_microusd=1,
        )

    async def review(self, **kwargs):
        self.calls += 1
        return await super().review(**kwargs)


class _AdvancingInvalidGenerator(_Generator):
    def __init__(self, clock: list[float]) -> None:
        super().__init__(valid=False)
        self._clock = clock

    async def generate(self, **kwargs):
        result = await super().generate(**kwargs)
        self._clock[0] = 6.0
        return result


class _Executor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, *, campaign, case, question):
        self.calls += 1
        del campaign, question
        return QuestionExecutionResult(
            disposition="answered",
            reason="verified_answer",
            turn=CampaignTurnEvidence(
                turn_id=f"turn:{case.case_id}",
                conversation_id="campaign-conversation",
                principal_scope_digest=DIGEST,
                question="What is the current state of the selected resource?",
                answer="The selected resource is available.",
                question_digest=DIGEST,
                answer_digest=DIGEST,
                evidence_manifest_digest=DIGEST,
                evidence_refs=("evidence:1",),
                verification_status="verified",
                verification_authority="ontology_query",
                verification_reason_code="verified_query",
                verification_route_id="semantic.query",
                checks_completed=1,
                checks_total=1,
                evidence_complete=True,
                ontology_release_digest=DIGEST,
                graph_revision=DIGEST,
                locale="en",
                answer_model_identity="answer-model",
            ),
            epistemic_status=EpistemicStatus.VERIFIED_ANSWER,
            understanding_receipt_digest=DIGEST,
            completeness_receipt_digest=DIGEST,
            claim_proof_receipt_digests=(DIGEST,),
            closed_population_receipt_digest=None,
            latency_ms=25,
        )


class _MismatchedExecutor(_Executor):
    async def execute(self, *, campaign, case, question):
        result = await super().execute(campaign=campaign, case=case, question=question)
        return QuestionExecutionResult(
            disposition="held",
            reason="evidence_unavailable",
            turn=result.turn,
            epistemic_status=EpistemicStatus.UNKNOWN_UNAVAILABLE,
            understanding_receipt_digest=result.understanding_receipt_digest,
            completeness_receipt_digest=result.completeness_receipt_digest,
            claim_proof_receipt_digests=result.claim_proof_receipt_digests,
            closed_population_receipt_digest=result.closed_population_receipt_digest,
            latency_ms=result.latency_ms,
        )


class _Assurance:
    async def assess(self, turn):
        return AssessmentRecord(
            assessment_id=f"assessment:{turn.turn_id}",
            turn_id=turn.turn_id,
            conversation_id=turn.conversation_id,
            principal_scope=turn.principal_scope,
            question_digest=turn.question_digest,
            answer_digest=turn.answer_digest,
            evidence_manifest_digest=turn.evidence_manifest_digest,
            rubric_version="1.0.0",
            model_set_digest=DIGEST,
            decision=AssuranceDecision(
                verdict=AssuranceVerdict.PASS,
                content_score=100.0,
                confidence=1.0,
            ),
            assessed_at=NOW,
            state=AssessmentState.COMPLETED,
        )


def _input(case: GeneratedQuestionCase) -> QuestionGenerationInput:
    return QuestionGenerationInput(
        case_id=case.case_id,
        declaration_kind="object",
        declaration_name="Resource",
        public_description="A provider-neutral managed resource.",
        readable_property_names=("id",),
        link_semantics=(),
        available_capabilities=("object_set",),
    )


async def test_runner_builds_complete_assurance_and_epistemic_chain() -> None:
    case = _case()
    ledger = InMemoryQuestionCampaignLedger()
    runner = QuestionCampaignRunner(
        generator=_Generator(),
        reviewer=_Reviewer(),
        executor=_Executor(),
        assurance=_Assurance(),
        ledger=ledger,
        pantheon_names=("Odin", "Thor", "Bragi"),
    )

    result = await runner.run(
        identity=_identity(),
        cases=(case,),
        full_universe_case_ids=(case.case_id,),
        generation_inputs={case.case_id: _input(case)},
    )

    assert result.state is QuestionCampaignState.COMPLETED
    assert result.evaluation.subset_complete is True
    assert result.evaluation.full_universe_closed is True
    assert result.attempts[0].terminal_reason == "verified_answer"
    assert result.attempts[0].assessment_id is not None
    assert result.attempts[0].epistemic_record_digest is not None
    completion = await ledger.get_completion(result.evaluation.campaign_id)
    assert completion is not None
    assert completion.state is QuestionCampaignState.COMPLETED


async def test_runner_persists_novelty_before_execution_and_blocks_cross_campaign_reuse() -> None:
    case = _case()
    campaign_ledger = InMemoryQuestionCampaignLedger()
    novelty_ledger = InMemoryQuestionNoveltyLedger()
    executor = _Executor()
    runner = QuestionCampaignRunner(
        generator=_Generator(),
        reviewer=_NoveltyReviewer(),
        executor=executor,
        assurance=_Assurance(),
        ledger=campaign_ledger,
        novelty_ledger=novelty_ledger,
        pantheon_names=("Odin", "Thor", "Bragi"),
        utcnow=lambda: NOW,
    )

    first = await runner.run(
        identity=_identity(),
        cases=(case,),
        full_universe_case_ids=(case.case_id,),
        generation_inputs={case.case_id: _input(case)},
    )
    second = await runner.run(
        identity=build_question_campaign_identity(
            source_revision="a" * 40,
            ontology_release_digest=DIGEST,
            principal_manifest_digests=(DIGEST,),
            question_universe_digest=DIGEST,
            generation_profile_digest=DIGEST,
            model_set_digest=DIGEST,
            scope_digest=DIGEST,
            started_at=NOW + timedelta(minutes=1),
            question_budget=20,
            time_budget_seconds=1_800,
            no_progress_seconds=300,
            token_budget=0,
            cost_budget_microusd=0,
            trigger=QuestionCampaignTrigger.MANUAL,
        ),
        cases=(case,),
        full_universe_case_ids=(case.case_id,),
        generation_inputs={case.case_id: _input(case)},
    )

    assert first.state is QuestionCampaignState.COMPLETED
    assert len(await novelty_ledger.list_novelty()) == 1
    assert executor.calls == 1
    assert second.state is QuestionCampaignState.COMPLETED
    assert second.attempts[0].terminal_reason == "candidate_duplicate_rejected"


async def test_runner_resumes_after_process_loss_without_reexecuting_terminal_case() -> None:
    first = _case("q:1")
    second = _case("q:2")
    identity = _identity()
    ledger = InMemoryQuestionCampaignLedger()
    await ledger.create_campaign(identity)
    await ledger.append_attempt(
        QuestionCaseAttemptRecord(
            campaign_id=identity.campaign_id,
            case_id=first.case_id,
            validated_question_digest=DIGEST,
            semantic_turn_id="turn:q:1",
            attempt_number=1,
            terminal_disposition="answered",
            terminal_reason="verified_answer",
            failure_kind=None,
            assessment_id="assessment:q:1",
            epistemic_record_digest=DIGEST,
            latency_ms=25,
            model_calls=1,
            prompt_tokens=10,
            completion_tokens=5,
            cost_microusd=7,
        )
    )
    generator = _Generator()
    runner = QuestionCampaignRunner(
        generator=generator,
        reviewer=_Reviewer(),
        executor=_Executor(),
        assurance=_Assurance(),
        ledger=ledger,
        pantheon_names=("Odin", "Thor", "Bragi"),
    )

    result = await runner.run(
        identity=identity,
        cases=(first, second),
        full_universe_case_ids=(first.case_id, second.case_id),
        generation_inputs={
            first.case_id: _input(first),
            second.case_id: _input(second),
        },
    )

    assert generator.calls == 1
    assert result.state is QuestionCampaignState.COMPLETED
    assert result.evaluation.terminal_case_count == 2
    assert len(result.attempts) == 2


async def test_runner_holds_before_execution_when_another_replica_claims_case() -> None:
    case = _case()
    identity = _identity()
    ledger = InMemoryQuestionCampaignLedger()
    await ledger.create_campaign(identity)
    await ledger.claim_case(
        campaign_id=identity.campaign_id,
        case_id=case.case_id,
        owner_id="runner:other",
        claimed_at=NOW,
        lease_seconds=identity.time_budget_seconds,
    )
    generator = _Generator()
    runner = QuestionCampaignRunner(
        generator=generator,
        reviewer=_Reviewer(),
        executor=_Executor(),
        assurance=_Assurance(),
        ledger=ledger,
        pantheon_names=("Odin", "Thor", "Bragi"),
        utcnow=lambda: NOW,
    )

    result = await runner.run(
        identity=identity,
        cases=(case,),
        full_universe_case_ids=(case.case_id,),
        generation_inputs={case.case_id: _input(case)},
    )

    assert generator.calls == 0
    assert result.state is QuestionCampaignState.HELD
    assert result.reason == "case_claim_unavailable"
    assert await ledger.get_completion(identity.campaign_id) is None


async def test_invalid_generation_retries_three_times_then_holds() -> None:
    case = _case()
    generator = _Generator(valid=False)
    runner = QuestionCampaignRunner(
        generator=generator,
        reviewer=_Reviewer(),
        executor=_Executor(),
        assurance=_Assurance(),
        ledger=InMemoryQuestionCampaignLedger(),
        pantheon_names=("Odin", "Thor", "Bragi"),
    )

    result = await runner.run(
        identity=_identity(),
        cases=(case,),
        full_universe_case_ids=(case.case_id,),
        generation_inputs={case.case_id: _input(case)},
    )

    assert generator.calls == 3
    assert result.attempts[0].terminal_disposition == "held"
    assert result.attempts[0].terminal_reason == "candidate_length_invalid"
    assert result.evaluation.subset_complete is True
    assert result.evaluation.full_universe_closed is False


async def test_runner_rejects_terminal_posture_mismatch_before_assurance() -> None:
    case = _case()
    runner = QuestionCampaignRunner(
        generator=_Generator(),
        reviewer=_Reviewer(),
        executor=_MismatchedExecutor(),
        assurance=_Assurance(),
        ledger=InMemoryQuestionCampaignLedger(),
        pantheon_names=("Odin", "Thor", "Bragi"),
    )

    result = await runner.run(
        identity=_identity(),
        cases=(case,),
        full_universe_case_ids=(case.case_id,),
        generation_inputs={case.case_id: _input(case)},
    )

    assert result.state is QuestionCampaignState.HELD
    assert result.attempts[0].failure_kind == "terminal_posture_mismatch"
    assert result.attempts[0].assessment_id is None


async def test_scheduled_campaign_holds_when_token_budget_is_exceeded() -> None:
    first = _case("q:1")
    second = _case("q:2")
    runner = QuestionCampaignRunner(
        generator=_Generator(),
        reviewer=_Reviewer(),
        executor=_Executor(),
        assurance=_Assurance(),
        ledger=InMemoryQuestionCampaignLedger(),
        pantheon_names=("Odin", "Thor", "Bragi"),
    )

    result = await runner.run(
        identity=_identity(
            trigger=QuestionCampaignTrigger.SCHEDULED,
            token_budget=20,
            cost_budget_microusd=100,
        ),
        cases=(first, second),
        full_universe_case_ids=(first.case_id, second.case_id),
        generation_inputs={
            first.case_id: _input(first),
            second.case_id: _input(second),
        },
    )

    assert result.state is QuestionCampaignState.HELD
    assert result.reason == "campaign_token_budget_reserved"
    assert result.evaluation.budget_within_limit is True
    assert result.evaluation.release_evidence_eligible is False


async def test_scheduled_campaign_reserves_reviewer_budget_before_call() -> None:
    case = _case()
    reviewer = _ExpensiveReviewer()
    runner = QuestionCampaignRunner(
        generator=_Generator(),
        reviewer=reviewer,
        executor=_Executor(),
        assurance=_Assurance(),
        ledger=InMemoryQuestionCampaignLedger(),
        pantheon_names=("Odin", "Thor", "Bragi"),
    )

    result = await runner.run(
        identity=_identity(
            trigger=QuestionCampaignTrigger.SCHEDULED,
            token_budget=20,
            cost_budget_microusd=100,
        ),
        cases=(case,),
        full_universe_case_ids=(case.case_id,),
        generation_inputs={case.case_id: _input(case)},
    )

    assert reviewer.calls == 0
    assert result.state is QuestionCampaignState.HELD
    assert result.reason == "campaign_token_budget_reserved"


async def test_retry_loop_rechecks_no_progress_deadline_between_calls() -> None:
    case = _case()
    clock = [0.0]
    generator = _AdvancingInvalidGenerator(clock)
    runner = QuestionCampaignRunner(
        generator=generator,
        reviewer=_Reviewer(),
        executor=_Executor(),
        assurance=_Assurance(),
        ledger=InMemoryQuestionCampaignLedger(),
        pantheon_names=("Odin", "Thor", "Bragi"),
        monotonic=lambda: clock[0],
    )
    identity = _identity()
    identity = replace(identity, time_budget_seconds=10, no_progress_seconds=5)

    result = await runner.run(
        identity=identity,
        cases=(case,),
        full_universe_case_ids=(case.case_id,),
        generation_inputs={case.case_id: _input(case)},
    )

    assert generator.calls == 1
    assert result.attempts[0].terminal_reason == "campaign_deadline_exceeded"
    assert result.evaluation.release_evidence_eligible is False
