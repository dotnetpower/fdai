"""Bounded shared runner for manual and scheduled question campaigns."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.conversation.epistemic_coverage import EpistemicStatus
from fdai.core.conversation.question_campaign import (
    CampaignTurnEvidence,
    QuestionCampaignEvaluationReceipt,
    QuestionCampaignHardZeroCounters,
    QuestionCampaignIdentity,
    QuestionCampaignLedger,
    QuestionCampaignState,
    QuestionCampaignTrigger,
    QuestionCaseAttemptRecord,
    build_question_campaign_completion,
    campaign_epistemic_record,
    campaign_turn_assessment_input,
    evaluate_question_campaign,
)
from fdai.core.conversation.question_candidates import (
    NaturalLanguageQuestionCandidate,
    QuestionCandidateGeneration,
    QuestionCandidateReview,
    QuestionCandidateReviewer,
    QuestionModelUsage,
    ValidatedQuestion,
    validate_question_candidate,
)
from fdai.core.conversation.question_novelty import (
    QuestionEmbeddingIdentity,
    QuestionNoveltyDuplicateError,
    QuestionNoveltyLedger,
    QuestionNoveltyRecord,
)
from fdai.core.conversation.question_universe import GeneratedQuestionCase
from fdai.core.conversation_assurance.models import AssessmentRecord, TurnAssessmentInput


@dataclass(frozen=True, slots=True)
class QuestionGenerationInput:
    """Environment-generic descriptor supplied to a candidate-only generator."""

    case_id: str
    declaration_kind: str
    declaration_name: str
    public_description: str
    readable_property_names: tuple[str, ...]
    link_semantics: tuple[str, ...]
    available_capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id or not self.declaration_kind or not self.declaration_name:
            raise ValueError("question generation identities MUST be non-empty")
        if len(self.public_description) > 1_000:
            raise ValueError("question generation description exceeds its bound")
        for values in (
            self.readable_property_names,
            self.link_semantics,
            self.available_capabilities,
        ):
            if values != tuple(sorted(set(values))) or len(values) > 128:
                raise ValueError(
                    "question generation descriptor values MUST be bounded and ordered"
                )
            if any(not value or len(value) > 256 for value in values):
                raise ValueError("question generation descriptor values MUST be bounded text")


class QuestionCandidateGenerator(Protocol):
    """Generate wording only, without tools, queries, scope, or action authority."""

    @property
    def model_family(self) -> str: ...

    @property
    def max_usage_per_call(self) -> QuestionModelUsage | None: ...

    async def generate(
        self,
        *,
        case: GeneratedQuestionCase,
        descriptor: QuestionGenerationInput,
        attempt_number: int,
        prior_fingerprints: tuple[str, ...],
    ) -> QuestionCandidateGeneration: ...


@dataclass(frozen=True, slots=True)
class QuestionExecutionResult:
    """Terminal semantic evidence returned by authenticated read-only submission."""

    disposition: str
    reason: str
    turn: CampaignTurnEvidence
    epistemic_status: EpistemicStatus
    understanding_receipt_digest: str | None
    completeness_receipt_digest: str | None
    claim_proof_receipt_digests: tuple[str, ...]
    closed_population_receipt_digest: str | None
    latency_ms: int
    hard_zero: QuestionCampaignHardZeroCounters = QuestionCampaignHardZeroCounters()

    def __post_init__(self) -> None:
        if not self.reason or len(self.reason) > 128:
            raise ValueError("question execution reason MUST be bounded")
        if self.latency_ms < 0:
            raise ValueError("question execution latency MUST be non-negative")


class QuestionExecutionPort(Protocol):
    """Submit one validated question through authenticated semantic transport."""

    async def execute(
        self,
        *,
        campaign: QuestionCampaignIdentity,
        case: GeneratedQuestionCase,
        question: ValidatedQuestion,
    ) -> QuestionExecutionResult: ...


class QuestionAssurancePort(Protocol):
    """Reuse the existing off-path conversation assurance service."""

    async def assess(self, turn: TurnAssessmentInput) -> AssessmentRecord: ...


@dataclass(frozen=True, slots=True)
class QuestionCampaignRunnerConfig:
    """Per-call and retry bounds beneath the immutable campaign ceilings."""

    max_generation_attempts: int = 3
    generation_timeout_seconds: float = 300.0
    execution_timeout_seconds: float = 300.0
    assessment_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_generation_attempts <= 3:
            raise ValueError("question generation attempts MUST be in [1, 3]")
        if any(
            value <= 0 or value > 300
            for value in (
                self.generation_timeout_seconds,
                self.execution_timeout_seconds,
                self.assessment_timeout_seconds,
            )
        ):
            raise ValueError("question campaign per-call timeouts MUST be in (0, 300]")


@dataclass(frozen=True, slots=True)
class QuestionCampaignRunResult:
    """Terminal runner state and proof without question or answer bodies."""

    state: QuestionCampaignState
    reason: str
    evaluation: QuestionCampaignEvaluationReceipt
    attempts: tuple[QuestionCaseAttemptRecord, ...]


@dataclass(frozen=True, slots=True)
class _CaseRunOutcome:
    attempt: QuestionCaseAttemptRecord
    accepted_question: str | None


class _MeteringReviewer:
    def __init__(self, reviewer: QuestionCandidateReviewer) -> None:
        self._reviewer = reviewer
        self.usage = QuestionModelUsage(model_calls=0)

    @property
    def max_usage_per_call(self) -> QuestionModelUsage | None:
        return self._reviewer.max_usage_per_call

    async def review(
        self,
        *,
        candidate: NaturalLanguageQuestionCandidate,
        expected_case: GeneratedQuestionCase,
        prior_questions: tuple[str, ...],
    ) -> QuestionCandidateReview:
        review = await self._reviewer.review(
            candidate=candidate,
            expected_case=expected_case,
            prior_questions=prior_questions,
        )
        self.usage = self.usage + review.usage
        return review


class QuestionCampaignRunner:
    """Generate, validate, execute, assess, and persist a bounded case selection."""

    def __init__(
        self,
        *,
        generator: QuestionCandidateGenerator,
        reviewer: QuestionCandidateReviewer,
        executor: QuestionExecutionPort,
        assurance: QuestionAssurancePort,
        ledger: QuestionCampaignLedger,
        novelty_ledger: QuestionNoveltyLedger | None = None,
        pantheon_names: Sequence[str],
        config: QuestionCampaignRunnerConfig | None = None,
        monotonic: Callable[[], float] | None = None,
        utcnow: Callable[[], datetime] | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        if not generator.model_family:
            raise ValueError("question generator family MUST be non-empty")
        if not pantheon_names:
            raise ValueError("question campaign runner requires pantheon names")
        self._generator = generator
        self._reviewer = reviewer
        self._executor = executor
        self._assurance = assurance
        self._ledger = ledger
        self._novelty_ledger = novelty_ledger
        self._pantheon_names = tuple(pantheon_names)
        self._config = config or QuestionCampaignRunnerConfig()
        self._monotonic = monotonic or time.monotonic
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._stop_requested = stop_requested or (lambda: False)
        self._claim_owner_id = f"runner:{secrets.token_hex(16)}"

    async def run(
        self,
        *,
        identity: QuestionCampaignIdentity,
        cases: Sequence[GeneratedQuestionCase],
        full_universe_case_ids: Sequence[str],
        generation_inputs: Mapping[str, QuestionGenerationInput],
        prior_questions: Sequence[str] = (),
    ) -> QuestionCampaignRunResult:
        """Run one selection sequentially with total and no-progress deadlines."""

        if not cases or len(cases) > identity.question_budget:
            raise ValueError("question campaign cases MUST fit the immutable budget")
        case_ids = tuple(item.case_id for item in cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("question campaign case ids MUST be unique")
        if set(generation_inputs) != set(case_ids):
            raise ValueError("question campaign generation inputs MUST cover selected cases")
        if any(generation_inputs[item.case_id].case_id != item.case_id for item in cases):
            raise ValueError("question generation input binds a different case")
        await self._ledger.create_campaign(identity)
        previous_attempts = await self._ledger.list_attempts(identity.campaign_id)
        existing_completion = await self._ledger.get_completion(identity.campaign_id)
        started = self._monotonic()
        last_progress = started
        accepted_questions = list(prior_questions)
        prior_fingerprints: list[str] = []
        attempts = list(previous_attempts)
        latest_terminal_case_ids = {
            attempt.case_id
            for attempt in previous_attempts
            if attempt.terminal_disposition is not None
            and not any(
                later.case_id == attempt.case_id and later.attempt_number > attempt.attempt_number
                for later in previous_attempts
            )
        }
        state = QuestionCampaignState.COMPLETED
        reason = "campaign_completed"
        for case in cases:
            if case.case_id in latest_terminal_case_ids:
                continue
            if self._stop_requested():
                state = QuestionCampaignState.CANCELLED
                reason = "stop_requested"
                break
            remaining = self._remaining(identity, started=started, last_progress=last_progress)
            if remaining <= 0:
                state = QuestionCampaignState.HELD
                reason = "campaign_deadline_exceeded"
                break
            attempt_number_offset = max(
                (
                    attempt.attempt_number
                    for attempt in previous_attempts
                    if attempt.case_id == case.case_id
                ),
                default=0,
            )
            if attempt_number_offset >= 10:
                state = QuestionCampaignState.HELD
                reason = "case_attempt_budget_exhausted"
                break
            claimed = await self._ledger.claim_case(
                campaign_id=identity.campaign_id,
                case_id=case.case_id,
                owner_id=self._claim_owner_id,
                claimed_at=self._utcnow(),
                lease_seconds=identity.time_budget_seconds,
            )
            if not claimed:
                state = QuestionCampaignState.HELD
                reason = "case_claim_unavailable"
                break
            try:
                refreshed = await self._ledger.list_attempts(identity.campaign_id)
                if any(
                    attempt.case_id == case.case_id and attempt.terminal_disposition is not None
                    for attempt in refreshed
                ):
                    attempts = list(refreshed)
                    continue
                case_outcome = await self._run_case(
                    identity=identity,
                    case=case,
                    descriptor=generation_inputs[case.case_id],
                    accepted_questions=accepted_questions,
                    prior_fingerprints=prior_fingerprints,
                    remaining_seconds=remaining,
                    attempt_number_offset=attempt_number_offset,
                    prior_usage=_usage_from_attempts(attempts),
                )
                attempts.append(case_outcome.attempt)
                await self._ledger.append_attempt(case_outcome.attempt)
            finally:
                await self._ledger.release_case_claim(
                    campaign_id=identity.campaign_id,
                    case_id=case.case_id,
                    owner_id=self._claim_owner_id,
                )
            last_progress = self._monotonic()
            if case_outcome.accepted_question is not None:
                accepted_questions.append(case_outcome.accepted_question)
            if case_outcome.attempt.terminal_reason in {
                "campaign_token_budget_reserved",
                "campaign_cost_budget_reserved",
                "model_usage_bound_unavailable",
            }:
                state = QuestionCampaignState.HELD
                reason = case_outcome.attempt.terminal_reason
                break
            budget_reason = _budget_exceeded_reason(identity, _usage_from_attempts(attempts))
            if budget_reason is not None:
                state = QuestionCampaignState.HELD
                reason = budget_reason
                break
        evaluation = evaluate_question_campaign(
            identity=identity,
            selected_case_ids=case_ids,
            full_universe_case_ids=full_universe_case_ids,
            attempts=attempts,
        )
        if state is QuestionCampaignState.COMPLETED and not evaluation.subset_complete:
            state = QuestionCampaignState.HELD
            reason = "campaign_no_progress"
        if reason != "case_claim_unavailable":
            completion = build_question_campaign_completion(
                identity=identity,
                completed_at=(
                    existing_completion.completed_at
                    if existing_completion is not None
                    else self._utcnow()
                ),
                state=state,
                reason=reason,
                evaluation=evaluation,
                selected_case_ids=case_ids,
                attempts=attempts,
            )
            await self._ledger.finalize_campaign(completion)
        return QuestionCampaignRunResult(
            state=state,
            reason=reason,
            evaluation=evaluation,
            attempts=tuple(attempts),
        )

    async def _run_case(
        self,
        *,
        identity: QuestionCampaignIdentity,
        case: GeneratedQuestionCase,
        descriptor: QuestionGenerationInput,
        accepted_questions: Sequence[str],
        prior_fingerprints: list[str],
        remaining_seconds: float,
        attempt_number_offset: int,
        prior_usage: QuestionModelUsage,
    ) -> _CaseRunOutcome:
        last_reason = "candidate_generation_unavailable"
        last_attempt_number = attempt_number_offset
        generation_calls = 0
        case_usage = QuestionModelUsage(model_calls=0)
        deadline = self._monotonic() + remaining_seconds
        for generation_attempt in range(1, self._config.max_generation_attempts + 1):
            attempt_number = attempt_number_offset + generation_attempt
            if attempt_number > 10:
                break
            last_attempt_number = attempt_number
            generation_calls += 1
            reservation_reason = _budget_reservation_reason(
                identity,
                prior_usage + case_usage,
                self._generator.max_usage_per_call,
            )
            if reservation_reason is not None:
                last_reason = reservation_reason
                break
            call_remaining = deadline - self._monotonic()
            if call_remaining <= 0:
                last_reason = "campaign_deadline_exceeded"
                break
            timeout = min(call_remaining, self._config.generation_timeout_seconds)
            try:
                async with asyncio.timeout(timeout):
                    generation = await self._generator.generate(
                        case=case,
                        descriptor=descriptor,
                        attempt_number=attempt_number,
                        prior_fingerprints=tuple(prior_fingerprints),
                    )
                    case_usage = case_usage + generation.usage
                    budget_reason = _budget_exceeded_reason(
                        identity,
                        prior_usage + case_usage,
                    )
                    if budget_reason is not None:
                        last_reason = budget_reason
                        break
                    metering_reviewer = _MeteringReviewer(self._reviewer)
                    reservation_reason = _budget_reservation_reason(
                        identity,
                        prior_usage + case_usage,
                        metering_reviewer.max_usage_per_call,
                    )
                    if reservation_reason is not None:
                        last_reason = reservation_reason
                        break
                    validation = await validate_question_candidate(
                        payload=generation.payload,
                        expected_case=case,
                        generation_profile_digest=identity.generation_profile_digest,
                        generator_family=self._generator.model_family,
                        prior_questions=accepted_questions,
                        pantheon_names=self._pantheon_names,
                        reviewer=metering_reviewer,
                    )
                    case_usage = case_usage + metering_reviewer.usage
            except TimeoutError:
                last_reason = "candidate_generation_timeout"
                continue
            except Exception as error:  # noqa: BLE001 - provider output stays outside ledger
                last_reason = f"candidate_generation_error_{type(error).__name__}"
                continue
            if validation.question is None:
                last_reason = validation.receipt.reason
                continue
            if self._novelty_ledger is not None:
                novelty = _accepted_novelty_record(
                    identity=identity,
                    case=case,
                    question=validation.question,
                    generation_attempt=attempt_number,
                    recorded_at=self._utcnow(),
                )
                if novelty is None:
                    last_reason = "candidate_embedding_identity_unavailable"
                    continue
                try:
                    await self._novelty_ledger.append_novelty(novelty)
                except QuestionNoveltyDuplicateError:
                    last_reason = "candidate_duplicate_rejected"
                    continue
            prior_fingerprints.append(validation.question.fingerprint)
            return await self._execute_case(
                identity=identity,
                case=case,
                question=validation.question,
                attempt_number=attempt_number,
                generation_calls=generation_calls,
                candidate_usage=case_usage,
                deadline=deadline,
            )
        return _CaseRunOutcome(
            attempt=QuestionCaseAttemptRecord(
                campaign_id=identity.campaign_id,
                case_id=case.case_id,
                validated_question_digest=_digest({"case_id": case.case_id, "reason": last_reason}),
                semantic_turn_id=f"generation-hold:{case.case_id}",
                attempt_number=last_attempt_number,
                terminal_disposition="held",
                terminal_reason=last_reason,
                failure_kind=None,
                assessment_id=None,
                epistemic_record_digest=None,
                latency_ms=0,
                model_calls=case_usage.model_calls,
                prompt_tokens=case_usage.prompt_tokens,
                completion_tokens=case_usage.completion_tokens,
                cost_microusd=case_usage.cost_microusd,
            ),
            accepted_question=None,
        )

    async def _execute_case(
        self,
        *,
        identity: QuestionCampaignIdentity,
        case: GeneratedQuestionCase,
        question: ValidatedQuestion,
        attempt_number: int,
        generation_calls: int,
        candidate_usage: QuestionModelUsage,
        deadline: float,
    ) -> _CaseRunOutcome:
        try:
            execution_remaining = deadline - self._monotonic()
            if execution_remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(
                min(execution_remaining, self._config.execution_timeout_seconds)
            ):
                execution = await self._executor.execute(
                    campaign=identity,
                    case=case,
                    question=question,
                )
            epistemic = campaign_epistemic_record(
                case_id=case.case_id,
                question_universe_digest=identity.question_universe_digest,
                status=execution.epistemic_status,
                understanding_receipt_digest=execution.understanding_receipt_digest,
                completeness_receipt_digest=execution.completeness_receipt_digest,
                claim_proof_receipt_digests=execution.claim_proof_receipt_digests,
                closed_population_receipt_digest=execution.closed_population_receipt_digest,
                hard_zero=execution.hard_zero,
            )
            expected_disposition = {
                "answer": "answered",
                "clarify": "clarification",
                "hold": "held",
                "unsupported": "unsupported",
                "action_draft": "action_draft",
            }[case.expected_posture.value]
            if (
                execution.disposition != expected_disposition
                or epistemic.transport_disposition != expected_disposition
            ):
                return _CaseRunOutcome(
                    attempt=_failed_attempt(
                        identity,
                        case,
                        question,
                        attempt_number,
                        "terminal_posture_mismatch",
                        candidate_usage,
                    ),
                    accepted_question=question.candidate.question,
                )
            assessment_remaining = deadline - self._monotonic()
            if assessment_remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(
                min(assessment_remaining, self._config.assessment_timeout_seconds)
            ):
                assessment = await self._assurance.assess(
                    campaign_turn_assessment_input(execution.turn)
                )
        except TimeoutError:
            return _CaseRunOutcome(
                attempt=_failed_attempt(
                    identity,
                    case,
                    question,
                    attempt_number,
                    "turn_timeout",
                    candidate_usage,
                ),
                accepted_question=question.candidate.question,
            )
        except Exception as error:  # noqa: BLE001 - error type only crosses the boundary
            return _CaseRunOutcome(
                attempt=_failed_attempt(
                    identity,
                    case,
                    question,
                    attempt_number,
                    f"turn_error_{type(error).__name__}",
                    candidate_usage,
                ),
                accepted_question=question.candidate.question,
            )
        return _CaseRunOutcome(
            attempt=QuestionCaseAttemptRecord(
                campaign_id=identity.campaign_id,
                case_id=case.case_id,
                validated_question_digest=question.candidate_digest,
                semantic_turn_id=execution.turn.turn_id,
                attempt_number=attempt_number,
                terminal_disposition=execution.disposition,
                terminal_reason=execution.reason,
                failure_kind=None,
                assessment_id=assessment.assessment_id,
                epistemic_record_digest=_digest(asdict(epistemic)),
                latency_ms=execution.latency_ms,
                model_calls=candidate_usage.model_calls + assessment.decision.model_calls,
                prompt_tokens=(candidate_usage.prompt_tokens + assessment.decision.prompt_tokens),
                completion_tokens=(
                    candidate_usage.completion_tokens + assessment.decision.completion_tokens
                ),
                cost_microusd=candidate_usage.cost_microusd + assessment.decision.cost_microusd,
                hard_zero=execution.hard_zero,
            ),
            accepted_question=question.candidate.question,
        )

    def _remaining(
        self,
        identity: QuestionCampaignIdentity,
        *,
        started: float,
        last_progress: float,
    ) -> float:
        now = self._monotonic()
        return min(
            identity.time_budget_seconds - (now - started),
            identity.no_progress_seconds - (now - last_progress),
        )


def _accepted_novelty_record(
    *,
    identity: QuestionCampaignIdentity,
    case: GeneratedQuestionCase,
    question: ValidatedQuestion,
    generation_attempt: int,
    recorded_at: datetime,
) -> QuestionNoveltyRecord | None:
    review = question.review
    if (
        review.embedding_space_digest is None
        or review.embedding_model_version is None
        or review.embedding_dimension is None
        or review.candidate_embedding_digest is None
    ):
        return None
    return QuestionNoveltyRecord(
        campaign_id=identity.campaign_id,
        case_id=case.case_id,
        generation_attempt=generation_attempt,
        perspective=case.perspective.value,
        locale=case.locale,
        ontology_release_digest=identity.ontology_release_digest,
        question_fingerprint=question.fingerprint,
        embedding=QuestionEmbeddingIdentity(
            space_digest=review.embedding_space_digest,
            model_version=review.embedding_model_version,
            dimension=review.embedding_dimension,
            vector_digest=review.candidate_embedding_digest,
        ),
        nearest_question_fingerprint=review.nearest_question_fingerprint,
        max_embedding_similarity=review.max_embedding_similarity,
        exact_duplicate=False,
        semantic_duplicate=False,
        accepted=True,
        recorded_at=recorded_at,
    )


def _failed_attempt(
    identity: QuestionCampaignIdentity,
    case: GeneratedQuestionCase,
    question: ValidatedQuestion,
    attempt_number: int,
    failure_kind: str,
    usage: QuestionModelUsage,
) -> QuestionCaseAttemptRecord:
    return QuestionCaseAttemptRecord(
        campaign_id=identity.campaign_id,
        case_id=case.case_id,
        validated_question_digest=question.candidate_digest,
        semantic_turn_id=f"failed:{case.case_id}",
        attempt_number=attempt_number,
        terminal_disposition=None,
        terminal_reason=None,
        failure_kind=failure_kind[:128],
        assessment_id=None,
        epistemic_record_digest=None,
        latency_ms=0,
        model_calls=usage.model_calls,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cost_microusd=usage.cost_microusd,
    )


def _usage_from_attempts(
    attempts: Sequence[QuestionCaseAttemptRecord],
) -> QuestionModelUsage:
    return QuestionModelUsage(
        model_calls=sum(item.model_calls for item in attempts),
        prompt_tokens=sum(item.prompt_tokens for item in attempts),
        completion_tokens=sum(item.completion_tokens for item in attempts),
        cost_microusd=sum(item.cost_microusd for item in attempts),
    )


def _budget_exceeded_reason(
    identity: QuestionCampaignIdentity,
    usage: QuestionModelUsage,
) -> str | None:
    if (
        identity.token_budget
        and usage.prompt_tokens + usage.completion_tokens > identity.token_budget
    ):
        return "campaign_token_budget_exceeded"
    if identity.cost_budget_microusd and usage.cost_microusd > identity.cost_budget_microusd:
        return "campaign_cost_budget_exceeded"
    return None


def _budget_reservation_reason(
    identity: QuestionCampaignIdentity,
    usage: QuestionModelUsage,
    reservation: QuestionModelUsage | None,
) -> str | None:
    if identity.trigger is not QuestionCampaignTrigger.SCHEDULED:
        return None
    if reservation is None:
        return "model_usage_bound_unavailable"
    if (
        identity.token_budget
        and usage.prompt_tokens
        + usage.completion_tokens
        + reservation.prompt_tokens
        + reservation.completion_tokens
        > identity.token_budget
    ):
        return "campaign_token_budget_reserved"
    if (
        identity.cost_budget_microusd
        and usage.cost_microusd + reservation.cost_microusd > identity.cost_budget_microusd
    ):
        return "campaign_cost_budget_reserved"
    return None


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "QuestionAssurancePort",
    "QuestionCampaignRunResult",
    "QuestionCampaignRunner",
    "QuestionCampaignRunnerConfig",
    "QuestionCandidateGenerator",
    "QuestionExecutionPort",
    "QuestionExecutionResult",
    "QuestionGenerationInput",
]
