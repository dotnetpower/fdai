"""Compose useful explanations with independently checked, optional operational examples."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal, TypeVar

from fdai_service_contracts.adaptive_answer import AdaptiveAnswer, AdaptiveGoalResult
from fdai_service_contracts.ontology_query import EvidenceAuthority
from fdai_service_contracts.semantic_turn import SemanticConversationModelTier
from pydantic import BaseModel, ValidationError

from .adaptive_call_scope import AdaptiveBudgetExceededError, bind_adaptive_model_budget
from .adaptive_models import (
    DEFAULT_ADAPTIVE_POLICY,
    AdaptiveDraft,
    AdaptiveEvidence,
    AdaptiveModel,
    AdaptivePlan,
    AdaptivePolicy,
    AdaptiveReview,
)
from .adaptive_prompt import (
    ConversationProfile,
    ConversationTierSelectableAdaptiveModel,
    compose_adaptive_prompt,
)
from .adaptive_wait import await_adaptive_call
from .model_observation import ConversationModelObservation

_LOGGER = logging.getLogger(__name__)
_Candidate = TypeVar("_Candidate", bound=BaseModel)
EvidenceReader = Callable[[str], Awaitable[AdaptiveEvidence]]
ProfileResolver = Callable[[str, str, Mapping[str, object] | None], ConversationProfile]


@lru_cache(maxsize=8)
def _stage_schema_json(shape: type[BaseModel]) -> str:
    """Cache only immutable schema text; each provider receives its own decoded value."""
    return json.dumps(shape.model_json_schema(), separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class AdaptiveOutcome:
    """A no-authority terminal with measured model observations."""

    answer: AdaptiveAnswer
    observations: tuple[ConversationModelObservation, ...]


@dataclass(frozen=True, slots=True)
class AdaptiveUnavailable:
    """A failed classification attempt cannot be retried through another route."""

    reason: str
    observations: tuple[ConversationModelObservation, ...]


BudgetLimit = Literal["deadline", "model_calls", "tokens"]


@dataclass(frozen=True, slots=True)
class AdaptiveBudgetTelemetry:
    """Settled measures of the enforcing adaptive turn budget, with no wall-clock time.

    Tokens charged as a byte-based reservation but never reconciled with measured usage stay
    reserved, which makes the measurement incomplete. The separate semantic preflight runs before
    this budget exists and is reported only in the model trace.
    """

    calls: int
    max_calls: int
    tokens_used: int
    tokens_reserved: int
    max_tokens: int
    elapsed_ms: int
    max_elapsed_ms: int
    complete: bool
    exhaustion_reason: BudgetLimit | None


@dataclass(slots=True)
class _Budget:
    policy: AdaptivePolicy
    clock: Callable[[], float] = time.monotonic
    model: AdaptiveModel | None = None
    started: float = field(init=False)
    calls: int = 0
    tokens: int = 0
    pending_tokens: int = 0
    limit_hits: list[BudgetLimit] = field(default_factory=list)
    ended_by: BudgetLimit | None = None
    observations: list[ConversationModelObservation] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.started = self.clock()

    @property
    def remaining(self) -> float:
        return self.policy.total_seconds - (self.clock() - self.started)

    def reserve(self, input_bytes: int, output_tokens: int, reserved_calls: int) -> int:
        reservation = input_bytes + output_tokens
        limit: BudgetLimit | None = (
            "deadline"
            if self.remaining <= 0
            else "model_calls"
            if self.calls + reserved_calls >= self.policy.max_calls
            else "tokens"
            if self.tokens + reservation > self.policy.max_tokens
            else None
        )
        if limit is not None:
            self.record_exhaustion(limit)
        if input_bytes > self.policy.max_input_bytes or limit is not None:
            raise AdaptiveBudgetExceededError("adaptive model budget exhausted")
        self.calls += 1
        self.tokens += reservation
        self.pending_tokens += reservation
        return reservation

    def observe(self, reservation: int, observation: ConversationModelObservation) -> None:
        self.observations.append(observation)
        observed = (observation.usage or {}).get("total_tokens")
        if type(observed) is int and observed >= 0:
            self.tokens += observed - reservation
            self.pending_tokens = max(0, self.pending_tokens - reservation)
        if self.tokens > self.policy.max_tokens:
            self.record_exhaustion("tokens")
        if self.remaining <= 0:
            self.record_exhaustion("deadline")
        if self.tokens > self.policy.max_tokens or self.remaining <= 0:
            raise AdaptiveBudgetExceededError("adaptive observed model budget exceeded")

    def record_exhaustion(self, limit: BudgetLimit, *, ended_turn: bool = False) -> None:
        """Remember each limit that stopped model work and the one that ended the turn."""
        if limit not in self.limit_hits:
            self.limit_hits.append(limit)
        if ended_turn:
            self.ended_by = limit

    def end_turn(self, error: BaseException) -> None:
        """Record the limit that ended a governed path stopped by a timeout or budget denial."""
        if isinstance(error, TimeoutError):
            self.record_exhaustion("deadline", ended_turn=True)
        elif self.limit_hits:
            self.record_exhaustion(self.limit_hits[-1], ended_turn=True)

    def telemetry(self) -> AdaptiveBudgetTelemetry | None:
        """Snapshot settled measures, or ``None`` when v1 telemetry cannot represent them.

        A measure may end above its maximum only as the exhaustion reason, so an overshoot names
        its own limit. Tokens and elapsed time both over their maxima have no v1 representation.
        """
        elapsed_ms = max(0, round((self.clock() - self.started) * 1000))
        max_elapsed_ms = round(self.policy.total_seconds * 1000)
        tokens_over = self.tokens > self.policy.max_tokens
        elapsed_over = elapsed_ms > max_elapsed_ms
        if self.calls > self.policy.max_calls or (tokens_over and elapsed_over):
            return None
        reason: BudgetLimit | None = (
            "tokens"
            if tokens_over
            else "deadline"
            if elapsed_over
            else self.ended_by or (self.limit_hits[0] if self.limit_hits else None)
        )
        return AdaptiveBudgetTelemetry(
            calls=self.calls,
            max_calls=self.policy.max_calls,
            tokens_used=self.tokens - self.pending_tokens,
            tokens_reserved=self.pending_tokens,
            max_tokens=self.policy.max_tokens,
            elapsed_ms=elapsed_ms,
            max_elapsed_ms=max_elapsed_ms,
            complete=self.pending_tokens == 0,
            exhaustion_reason=reason,
        )


@dataclass(frozen=True, slots=True)
class AdaptiveDeferred:
    """Retain the interpreted plan and turn budget while the governed path runs."""

    plan: AdaptivePlan
    profile: ConversationProfile
    payload: Mapping[str, object]
    budget: _Budget


class AdaptiveConversationService:
    """Interpret whole turns, bind read-only evidence, review, and refine once.

    Scope or operational execution failures never become invented evidence. Calls are
    bounded as one turn; model stages receive data separately from trusted prompt layers.
    """

    def __init__(
        self,
        *,
        model: AdaptiveModel,
        profile_resolver: ProfileResolver,
        prompts: Mapping[str, str],
        policy: AdaptivePolicy = DEFAULT_ADAPTIVE_POLICY,
        clock: Callable[[], float] = time.monotonic,
        model_factory: Callable[[], AdaptiveModel | None] | None = None,
    ) -> None:
        if any(
            not prompts.get(stage) for stage in ("plan", "answer", "review", "refine", "verify")
        ):
            raise ValueError("adaptive prompts require every bounded stage")
        self._model = model
        self._model_factory = model_factory
        self._profiles = profile_resolver
        self._prompts = dict(prompts)
        self._policy = policy
        self._clock = clock

    def social_profile(
        self,
        agent: str,
        locale: str,
        relationship: Mapping[str, object] | None,
    ) -> Mapping[str, str]:
        """Expose only server-owned identity and role to the existing social narrator."""
        profile = self._profiles(agent, locale, relationship)
        return {"identity": profile.agent, "role": profile.role_directive}

    async def respond(
        self,
        *,
        utterance: str,
        history: Sequence[Mapping[str, str]],
        locale: str,
        target_agent: str,
        relationship: Mapping[str, object] | None,
        read_evidence: EvidenceReader,
        cancelled: asyncio.Event | None = None,
        allow_refinement: bool = True,
        conversation_model_tier: SemanticConversationModelTier | None = None,
    ) -> AdaptiveOutcome | AdaptiveUnavailable | AdaptiveDeferred | None:
        """Return advisory output or defer a non-advisory turn to the governed runtime."""
        profile = self._profiles(target_agent, locale, relationship)
        model = self._model_factory() if self._model_factory is not None else self._model
        if model is None:
            _LOGGER.warning("adaptive_t1_pair_unavailable")
            return AdaptiveUnavailable("adaptive_t1_pair_unavailable", ())
        if conversation_model_tier is SemanticConversationModelTier.T2:
            if not isinstance(model, ConversationTierSelectableAdaptiveModel):
                return AdaptiveUnavailable("conversation_t2_model_unavailable", ())
            model = model.for_conversation_tier(conversation_model_tier)
            if model is None:
                return AdaptiveUnavailable("conversation_t2_model_unavailable", ())
        budget = _Budget(self._policy, clock=self._clock, model=model)
        payload: dict[str, object] = {
            "utterance": utterance,
            "history": list(history[-8:]),
        }
        plan = await self._stage("plan", AdaptivePlan, profile, payload, budget, cancelled)
        if plan is None:
            return AdaptiveUnavailable("adaptive_planning_unavailable", tuple(budget.observations))
        if (
            plan.context_dependency == "pending_decision"
            or plan.action_requested
            or plan.route == "legacy"
        ):
            return AdaptiveDeferred(plan, profile, payload, budget)
        return await self._answer(
            plan,
            profile,
            payload,
            budget,
            read_evidence,
            cancelled,
            allow_refinement,
        )

    async def resume_after_governed_draft(
        self,
        deferred: AdaptiveDeferred,
        *,
        read_evidence: EvidenceReader,
        cancelled: asyncio.Event | None,
        allow_refinement: bool,
    ) -> AdaptiveOutcome:
        """Add an explanation only after the normal path returned a no-authority action draft."""
        payload = {
            **deferred.payload,
            "governed_action": {
                "status": "draft_only",
                "execution_authority": False,
            },
        }
        return await self._answer(
            deferred.plan,
            deferred.profile,
            payload,
            deferred.budget,
            read_evidence,
            cancelled,
            allow_refinement,
        )

    async def _answer(
        self,
        plan: AdaptivePlan,
        profile: ConversationProfile,
        payload: dict[str, object],
        budget: _Budget,
        read_evidence: EvidenceReader,
        cancelled: asyncio.Event | None,
        allow_refinement: bool,
    ) -> AdaptiveOutcome:
        evidence: dict[str, AdaptiveEvidence] = {}
        for goal in plan.goals:
            if goal.kind == "knowledge":
                continue
            if cancelled is not None and cancelled.is_set():
                raise asyncio.CancelledError
            read_budget = budget.remaining - 2 * self._policy.per_stage_seconds
            if read_budget <= 0:
                evidence[goal.goal_id] = AdaptiveEvidence(
                    status="unavailable",
                    limitation="adaptive_evidence_budget_exhausted",
                )
                continue
            try:
                async with bind_adaptive_model_budget(budget, reserved_calls=2):
                    evidence[goal.goal_id] = await await_adaptive_call(
                        read_evidence(goal.question),
                        timeout=min(self._policy.per_stage_seconds, read_budget),
                        cancelled=cancelled,
                    )
            except AdaptiveBudgetExceededError:
                _LOGGER.warning("adaptive_evidence_model_budget_exhausted")
                evidence[goal.goal_id] = AdaptiveEvidence(
                    status="unavailable",
                    limitation="adaptive_evidence_model_budget_exhausted",
                )
            except TimeoutError:
                _LOGGER.warning("adaptive_evidence_deadline_exceeded")
                evidence[goal.goal_id] = AdaptiveEvidence(
                    status="unavailable",
                    limitation="adaptive_evidence_deadline_exceeded",
                )
            except PermissionError:
                _LOGGER.warning("adaptive_evidence_access_denied")
                evidence[goal.goal_id] = AdaptiveEvidence(
                    status="held",
                    limitation="adaptive_evidence_access_denied",
                )
            source = evidence[goal.goal_id]
            if (
                goal.kind == "environment_example"
                and source.status == "answered"
                and (
                    not source.authorities
                    or set(source.authorities) == {EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST}
                )
            ):
                evidence[goal.goal_id] = AdaptiveEvidence(
                    status="unavailable",
                    limitation="environment_example_requires_runtime_evidence",
                )
        payload["plan"] = plan.model_dump(mode="json", exclude={"draft"})
        payload["evidence"] = {
            key: {
                "status": item.status,
                "content": item.content,
                "evidence_refs": list(item.evidence_refs),
                "limitation": item.limitation,
                "authorities": [authority.value for authority in item.authorities],
            }
            for key, item in evidence.items()
        }
        draft = plan.draft or await self._stage(
            "answer", AdaptiveDraft, profile, payload, budget, cancelled
        )
        if draft is None:
            return self._limited(plan, profile, evidence, budget, "adaptive_answer_unavailable")
        review_context = (
            {key: value for key, value in payload.items() if key != "history"}
            if plan.context_dependency == "none"
            else payload
        )
        review_payload = {**review_context, "draft": draft.model_dump(mode="json")}
        review = await self._stage(
            "review",
            AdaptiveReview,
            profile,
            review_payload,
            budget,
            cancelled,
        )
        valid_ids = {goal.goal_id for goal in plan.goals}
        safe = self._safe(draft, review, valid_ids)
        complete = safe and self._complete(draft, review, plan, evidence)
        refinements = 0
        supported = set(review.supported_goal_ids) if review is not None else set()
        drafted = {section.goal_id for section in draft.sections}
        evidence_only_hold = (
            safe
            and all(
                goal.goal_id in supported & drafted
                for goal in plan.goals
                if goal.required and goal.kind == "knowledge"
            )
            and any(
                goal.required
                and goal.kind != "knowledge"
                and (goal.goal_id not in evidence or evidence[goal.goal_id].status != "answered")
                for goal in plan.goals
            )
        )
        if evidence_only_hold:
            _LOGGER.info("adaptive_refinement_requires_missing_evidence")
        refinement_fits = (
            budget.remaining >= 2 * self._policy.per_stage_seconds
            and budget.calls + 2 <= self._policy.max_calls
            and budget.tokens + 2 * self._policy.reserved_output_tokens <= self._policy.max_tokens
        )
        if not complete and allow_refinement and not refinement_fits:
            _LOGGER.info("adaptive_refinement_budget_exhausted")
        if (
            not complete
            and allow_refinement
            and self._policy.refinement_enabled
            and review is not None
            and refinement_fits
            and not evidence_only_hold
        ):
            review_payload["critique"] = review.model_dump(mode="json")
            calls_before = budget.calls
            improved = await self._stage(
                "refine",
                AdaptiveDraft,
                profile,
                review_payload,
                budget,
                cancelled,
            )
            refinements = int(budget.calls > calls_before)
            if improved is not None:
                final_review = await self._stage(
                    "verify",
                    AdaptiveReview,
                    profile,
                    {**review_context, "draft": improved.model_dump(mode="json")},
                    budget,
                    cancelled,
                )
                if self._safe(improved, final_review, valid_ids):
                    draft, review = improved, final_review
                    safe = True
                    complete = self._complete(draft, review, plan, evidence)
        if not safe or review is None:
            return self._limited(
                plan, profile, evidence, budget, "adaptive_review_incomplete", refinements
            )
        supported = set(review.supported_goal_ids)
        sections = {section.goal_id: section.text for section in draft.sections}
        goals: list[AdaptiveGoalResult] = []
        paragraphs: list[str] = []
        for goal in plan.goals:
            goal_evidence = evidence.get(goal.goal_id)
            can_answer = (
                goal.goal_id in supported
                and goal.goal_id in sections
                and (
                    goal.kind == "knowledge"
                    or goal_evidence is not None
                    and goal_evidence.status == "answered"
                )
            )
            if can_answer:
                paragraphs.append(sections[goal.goal_id])
            limitation = (
                None
                if can_answer
                else (
                    goal_evidence.limitation
                    if goal_evidence is not None and goal_evidence.status != "answered"
                    else "adaptive_goal_not_supported"
                )
            )
            goals.append(
                AdaptiveGoalResult(
                    goal_id=goal.goal_id,
                    kind=goal.kind,
                    required=goal.required,
                    status="answered" if can_answer else "held" if goal.required else "unavailable",
                    evidence_refs=(
                        goal_evidence.evidence_refs
                        if can_answer and goal_evidence is not None
                        else ()
                    ),
                    limitation=limitation,
                )
            )
        if not paragraphs:
            return self._limited(
                plan, profile, evidence, budget, "adaptive_goal_not_supported", refinements
            )
        return AdaptiveOutcome(
            AdaptiveAnswer.model_validate(
                {
                    "answer": "\n\n".join(paragraphs),
                    "goals": tuple(goals),
                    "role_agent": profile.agent,
                    "quality_status": "passed" if complete else "limited",
                    "refinements": refinements,
                    "execution_authority": False,
                }
            ),
            tuple(budget.observations),
        )

    async def _stage(
        self,
        stage: str,
        shape: type[_Candidate],
        profile: ConversationProfile,
        payload: Mapping[str, object],
        budget: _Budget,
        cancelled: asyncio.Event | None,
    ) -> _Candidate | None:
        started = self._clock()
        status = "failed"
        try:
            result = await self._invoke_stage(stage, shape, profile, payload, budget, cancelled)
            status = "completed" if result is not None else "unavailable"
            return result
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        finally:
            _LOGGER.info(
                "adaptive_stage_completed",
                extra={
                    "stage": stage,
                    "status": status,
                    "duration_ms": round(max(0, self._clock() - started) * 1000),
                    "remaining_ms": round(max(0, budget.remaining) * 1000),
                    "calls": budget.calls,
                },
            )

    async def _invoke_stage(
        self,
        stage: str,
        shape: type[_Candidate],
        profile: ConversationProfile,
        payload: Mapping[str, object],
        budget: _Budget,
        cancelled: asyncio.Event | None,
    ) -> _Candidate | None:
        if cancelled is not None and cancelled.is_set():
            raise asyncio.CancelledError
        prompt = compose_adaptive_prompt(profile, stage, self._prompts[stage])
        schema = json.loads(_stage_schema_json(shape))
        encoded = json.dumps({"input": payload, "schema": schema}, ensure_ascii=False)
        size = len(encoded.encode()) + len(prompt.encode())
        try:
            reservation = budget.reserve(
                size, budget.policy.reserved_output_tokens, 1 if stage == "refine" else 0
            )
        except AdaptiveBudgetExceededError:
            _LOGGER.warning("adaptive_stage_budget_denied", extra={"stage": stage})
            return None
        try:
            result = await await_adaptive_call(
                (budget.model if budget.model is not None else self._model).complete(
                    stage=stage,
                    system_prompt=prompt,
                    payload=payload,
                    schema=schema,
                    escalated=stage == "refine",
                ),
                timeout=min(budget.policy.per_stage_seconds, budget.remaining),
                cancelled=cancelled,
            )
        except TimeoutError:
            _LOGGER.warning("adaptive_model_deadline_exceeded", extra={"stage": stage})
            return None
        if cancelled is not None and cancelled.is_set():
            raise asyncio.CancelledError
        if result is None:
            _LOGGER.warning("adaptive_model_unavailable", extra={"stage": stage})
            return None
        try:
            budget.observe(reservation, result.observation)
        except AdaptiveBudgetExceededError:
            _LOGGER.warning("adaptive_observed_budget_exceeded", extra={"stage": stage})
            return None
        try:
            return shape.model_validate(result.proposal)
        except ValidationError:
            _LOGGER.warning("adaptive_model_schema_rejected", extra={"stage": stage})
            return None

    @staticmethod
    def _safe(
        draft: AdaptiveDraft,
        review: AdaptiveReview | None,
        valid_ids: set[str],
    ) -> bool:
        return (
            review is not None
            and review.safe
            and {section.goal_id for section in draft.sections} <= valid_ids
            and set(review.supported_goal_ids) <= valid_ids
        )

    @staticmethod
    def _complete(
        draft: AdaptiveDraft,
        review: AdaptiveReview | None,
        plan: AdaptivePlan,
        evidence: Mapping[str, AdaptiveEvidence],
    ) -> bool:
        if review is None or not review.complete or review.issues:
            return False
        answered = {section.goal_id for section in draft.sections} & set(review.supported_goal_ids)
        return all(
            not goal.required
            or goal.goal_id in answered
            and (
                goal.kind == "knowledge"
                or goal.goal_id in evidence
                and evidence[goal.goal_id].status == "answered"
            )
            for goal in plan.goals
        )

    @staticmethod
    def _limited(
        plan: AdaptivePlan,
        profile: ConversationProfile,
        evidence: Mapping[str, AdaptiveEvidence],
        budget: _Budget,
        reason: str,
        refinements: int = 0,
    ) -> AdaptiveOutcome:
        answer = (
            "답변을 충분히 검토하지 못했습니다. 확인되지 않은 설명이나 환경 상태를 사실로 "
            "제시하지 않겠습니다. 질문을 유지한 채 답변 모델과 근거 원본의 "
            "준비 상태를 확인할 수 있습니다."
            if profile.locale == "ko"
            else "The answer could not be reviewed sufficiently. I will not present unconfirmed "
            "explanations or environment state as facts. Keep the question and check answer-model "
            "and evidence-source readiness."
        )
        goals: list[AdaptiveGoalResult] = []
        for goal in plan.goals:
            source = evidence.get(goal.goal_id)
            retained = False
            limitation = reason
            if source is not None and source.status == "answered":
                title = "확인된 근거 데이터" if profile.locale == "ko" else "Verified evidence data"
                longest = run = 0
                for character in source.content:
                    run = run + 1 if character == "`" else 0
                    longest = max(longest, run)
                fence = "`" * max(3, longest + 1)
                section = f"\n\n### {title}\n\n{fence}json\n{source.content}\n{fence}"
                retained = len(answer) + len(section) <= 14000
                if retained:
                    answer += section
                else:
                    limitation = "adaptive_evidence_render_budget_exhausted"
            goals.append(
                AdaptiveGoalResult(
                    goal_id=goal.goal_id,
                    kind=goal.kind,
                    required=goal.required,
                    status="answered" if retained else "held" if goal.required else "unavailable",
                    evidence_refs=source.evidence_refs if retained and source is not None else (),
                    limitation=None if retained else limitation,
                )
            )
        return AdaptiveOutcome(
            AdaptiveAnswer.model_validate(
                {
                    "answer": answer,
                    "role_agent": profile.agent,
                    "quality_status": "limited",
                    "refinements": refinements,
                    "goals": tuple(goals),
                    "execution_authority": False,
                }
            ),
            tuple(budget.observations),
        )
