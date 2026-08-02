"""Concrete bounded lifecycle collaborators for conversation assurance."""

from __future__ import annotations

import hashlib
import math
import statistics
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any, Protocol

from fdai.core.conversation_assurance import (
    AssuranceCriterion,
    AssuranceDecision,
    AssuranceVerdict,
    ChatPolicyCandidate,
    ChatPolicyProposal,
    ChatPolicyTarget,
    ConversationPolicyRuntime,
    FailureCluster,
    MixedFamilyAssuranceReviewer,
    PolicyTrialMetrics,
    TurnAssessmentInput,
)
from fdai.core.metering import TokenUsage
from fdai.core.metering.pricing import PricingTable

_SCENARIO_VERSION = "conversation-assurance-v1"


@dataclass(frozen=True, slots=True)
class BlindConversationScenario:
    scenario_id: str
    locale: str
    question: str
    reference_facts: tuple[str, ...]


BLIND_CONVERSATION_SCENARIOS = (
    BlindConversationScenario(
        "bragi-boundary-en",
        "en",
        "What does Bragi do, and can it grant execution eligibility?",
        (
            "Bragi is the narrator and conversational router.",
            "Bragi cannot judge, approve, or grant execution eligibility.",
        ),
    ),
    BlindConversationScenario(
        "bragi-boundary-ko",
        "ko",
        "Bragi의 역할은 무엇이며 실행 자격을 부여할 수 있나요?",
        (
            "Bragi는 narrator이자 대화 router입니다.",
            "Bragi는 판단, 승인 또는 실행 자격 부여를 할 수 없습니다.",
        ),
    ),
    BlindConversationScenario(
        "insufficient-evidence-en",
        "en",
        "What should FDAI do when evidence is insufficient?",
        ("FDAI holds or escalates when evidence is insufficient; it does not guess.",),
    ),
    BlindConversationScenario(
        "insufficient-evidence-ko",
        "ko",
        "근거가 부족할 때 FDAI는 어떻게 해야 하나요?",
        ("FDAI는 근거가 부족하면 추측하지 않고 판단을 보류하거나 escalation합니다.",),
    ),
    BlindConversationScenario(
        "safe-autonomy-en",
        "en",
        "Which safeguards are required before an autonomous action can run?",
        (
            "Autonomous action requires a stop condition, rollback, blast-radius limit, "
            "dry-run, lock, and audit record.",
        ),
    ),
    BlindConversationScenario(
        "safe-autonomy-ko",
        "ko",
        "자율 액션 실행 전에 어떤 안전장치가 필요한가요?",
        (
            "자율 액션에는 중지 조건, rollback, 영향 범위 제한, dry-run, lock 및 "
            "audit record가 필요합니다.",
        ),
    ),
)


class NarratorCostEstimator(Protocol):
    def __call__(self, reply: Mapping[str, Any]) -> int | None: ...


class NarratorBackend(Protocol):
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]: ...


def pricing_narrator_cost_estimator(pricing: PricingTable) -> NarratorCostEstimator:
    """Build a strict model-and-usage estimator over the shared pricing catalog."""

    def estimate(reply: Mapping[str, Any]) -> int | None:
        model = reply.get("model")
        usage = reply.get("usage")
        if not isinstance(model, str) or not isinstance(usage, Mapping):
            return None
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if (
            isinstance(prompt, bool)
            or not isinstance(prompt, int)
            or prompt < 0
            or isinstance(completion, bool)
            or not isinstance(completion, int)
            or completion < 0
        ):
            return None
        cost = pricing.cost_of(
            model_key=model,
            usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion),
        )
        if cost is None:
            return None
        return int((cost * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))

    return estimate


class DeterministicNarratorPolicyProposer:
    """Map closed failure criteria to one generic narrator instruction."""

    def __init__(self, *, runtime: ConversationPolicyRuntime) -> None:
        self._runtime = runtime

    async def propose(self, cluster: FailureCluster) -> ChatPolicyProposal:
        directives = [_directive(criterion) for criterion in cluster.failed_criteria]
        if not directives:
            directives = [
                "Answer the operator request directly and state uncertainty when evidence "
                "is incomplete."
            ]
        text = " ".join(dict.fromkeys(directives))
        digest = hashlib.sha256(text.encode()).hexdigest()
        incumbent = await self._runtime.current_digest(
            principal_scope=cluster.principal_scope,
            target=ChatPolicyTarget.NARRATOR_PROMPT,
        )
        return ChatPolicyProposal(
            target=ChatPolicyTarget.NARRATOR_PROMPT,
            policy_digest=digest,
            incumbent_policy_digest=incumbent,
            policy_text=text,
        )


class BilingualBlindPolicyTrialMeasurer:
    """Compare incumbent and candidate on one frozen bilingual scenario set."""

    def __init__(
        self,
        *,
        backend: NarratorBackend,
        reviewer: MixedFamilyAssuranceReviewer,
        cost_estimator: NarratorCostEstimator,
        scenarios: tuple[BlindConversationScenario, ...] = BLIND_CONVERSATION_SCENARIOS,
    ) -> None:
        if not scenarios or {item.locale for item in scenarios} != {"en", "ko"}:
            raise ValueError("blind trial scenarios MUST include English and Korean")
        self._backend = backend
        self._reviewer = reviewer
        self._cost_estimator = cost_estimator
        self._scenarios = scenarios

    async def measure(
        self,
        candidate: ChatPolicyCandidate,
        cluster: FailureCluster,
    ) -> PolicyTrialMetrics | None:
        if (
            candidate.policy_text is None
            or candidate.target is not ChatPolicyTarget.NARRATOR_PROMPT
        ):
            return None
        incumbent_rows: list[_MeasuredAnswer] = []
        candidate_rows: list[_MeasuredAnswer] = []
        for scenario in self._scenarios:
            incumbent = await self._run_answer(
                candidate=candidate,
                scenario=scenario,
                use_candidate=False,
                cluster=cluster,
            )
            challenger = await self._run_answer(
                candidate=candidate,
                scenario=scenario,
                use_candidate=True,
                cluster=cluster,
            )
            if incumbent is None or challenger is None:
                return None
            incumbent_rows.append(incumbent)
            candidate_rows.append(challenger)
        if not _has_verified_answer_per_locale(
            incumbent_rows
        ) or not _has_verified_answer_per_locale(candidate_rows):
            return None
        deltas = [
            challenger.decision.content_score - incumbent.decision.content_score
            for incumbent, challenger in zip(incumbent_rows, candidate_rows, strict=True)
        ]
        evidence_material = "\0".join(
            (
                _SCENARIO_VERSION,
                candidate.stage.value,
                candidate.policy_digest,
                candidate.incumbent_policy_digest,
                *(item.answer_digest for item in incumbent_rows),
                *(item.answer_digest for item in candidate_rows),
            )
        )
        return PolicyTrialMetrics(
            observed_stage=candidate.stage,
            evidence_digest=hashlib.sha256(evidence_material.encode()).hexdigest(),
            sample_count=len(self._scenarios),
            score_delta_lcb95=_lower_confidence_bound(deltas),
            hard_failure_escapes=sum(_hard_failure(item.decision) for item in candidate_rows),
            candidate_cost_per_verified_microusd=_cost_per_verified(candidate_rows),
            incumbent_cost_per_verified_microusd=_cost_per_verified(incumbent_rows),
            latency_delta_ms=statistics.fmean(item.latency_ms for item in candidate_rows)
            - statistics.fmean(item.latency_ms for item in incumbent_rows),
            locale_gap_delta=_locale_gap(candidate_rows) - _locale_gap(incumbent_rows),
            disagreement_rate_delta=_disagreement_rate(candidate_rows)
            - _disagreement_rate(incumbent_rows),
        )

    async def _run_answer(
        self,
        *,
        candidate: ChatPolicyCandidate,
        scenario: BlindConversationScenario,
        use_candidate: bool,
        cluster: FailureCluster,
    ) -> _MeasuredAnswer | None:
        context: dict[str, Any] = {"locale": scenario.locale}
        if use_candidate:
            context["_conversation_assurance_policy"] = {
                "candidate_id": candidate.candidate_id,
                "policy_digest": candidate.policy_digest,
                "stage": candidate.stage.value,
                "target": candidate.target.value,
                "text": candidate.policy_text,
            }
        started = time.monotonic()
        try:
            reply = await self._backend.answer(
                prompt=scenario.question,
                view_context=context,
                history=[],
            )
        except Exception:
            return None
        latency_ms = max(0.0, (time.monotonic() - started) * 1_000)
        answer = reply.get("answer")
        model = reply.get("model")
        if not isinstance(answer, str) or not answer.strip() or not isinstance(model, str):
            return None
        narrator_cost = self._cost_estimator(reply)
        if narrator_cost is None or narrator_cost < 0:
            return None
        variant = "candidate" if use_candidate else "incumbent"
        turn = TurnAssessmentInput(
            turn_id=f"blind:{cluster.cluster_id}:{scenario.scenario_id}:{variant}",
            conversation_id=f"blind:{cluster.cluster_id}",
            principal_scope=cluster.principal_scope,
            question=scenario.question,
            answer=answer,
            question_digest=hashlib.sha256(scenario.question.encode()).hexdigest(),
            answer_digest=hashlib.sha256(answer.encode()).hexdigest(),
            evidence_manifest_digest=hashlib.sha256(
                "\0".join(scenario.reference_facts).encode()
            ).hexdigest(),
            evidence_refs=(),
            verification_status="benchmark_reference",
            verification_authority="conversation_assurance_frozen_scenario",
            checks_completed=len(scenario.reference_facts),
            checks_total=len(scenario.reference_facts),
            locale=scenario.locale,
            answer_model_identity=model,
            reference_facts=scenario.reference_facts,
        )
        decision = await self._reviewer.review(turn)
        if decision.verdict is AssuranceVerdict.INCONCLUSIVE:
            return None
        return _MeasuredAnswer(
            decision=decision,
            answer_digest=turn.answer_digest,
            latency_ms=latency_ms,
            total_cost_microusd=narrator_cost + decision.cost_microusd,
            locale=scenario.locale,
        )


@dataclass(frozen=True, slots=True)
class _MeasuredAnswer:
    decision: AssuranceDecision
    answer_digest: str
    latency_ms: float
    total_cost_microusd: int
    locale: str


def _directive(criterion: AssuranceCriterion) -> str:
    return {
        AssuranceCriterion.FACTUAL_CORRECTNESS: (
            "State only claims supported by supplied evidence and preserve every identifier "
            "exactly."
        ),
        AssuranceCriterion.INTENT_RESOLUTION: "Answer the operator's requested intent directly.",
        AssuranceCriterion.COMPLETENESS: (
            "Include required constraints, uncertainty, and a safe next step when available."
        ),
        AssuranceCriterion.CALIBRATION: (
            "State uncertainty explicitly and abstain instead of guessing when evidence is "
            "incomplete."
        ),
        AssuranceCriterion.ACTIONABILITY: (
            "Give a bounded read-only next step without granting execution or approval authority."
        ),
        AssuranceCriterion.CLARITY: "Use concise, natural language in the operator's locale.",
    }[criterion]


def _lower_confidence_bound(values: list[float]) -> float:
    mean = statistics.fmean(values)
    if len(values) < 2:
        return mean
    return mean - 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def _has_verified_answer_per_locale(rows: list[_MeasuredAnswer]) -> bool:
    return all(
        any(
            item.locale == locale and item.decision.verdict is AssuranceVerdict.PASS
            for item in rows
        )
        for locale in ("en", "ko")
    )


def _cost_per_verified(rows: list[_MeasuredAnswer]) -> float:
    verified = sum(item.decision.verdict is AssuranceVerdict.PASS for item in rows)
    if verified == 0:
        raise ValueError("blind trial has no verified answers")
    return sum(item.total_cost_microusd for item in rows) / verified


def _hard_failure(decision: AssuranceDecision) -> int:
    factual = next(
        (
            item
            for item in decision.criteria
            if item.criterion is AssuranceCriterion.FACTUAL_CORRECTNESS
        ),
        None,
    )
    return int(factual is None or factual.score < 3)


def _locale_gap(rows: list[_MeasuredAnswer]) -> float:
    by_locale = {
        locale: statistics.fmean(
            item.decision.content_score for item in rows if item.locale == locale
        )
        for locale in ("en", "ko")
    }
    return abs(by_locale["en"] - by_locale["ko"]) / 100.0


def _disagreement_rate(rows: list[_MeasuredAnswer]) -> float:
    return sum(item.decision.disagreement for item in rows) / len(rows)


__all__ = [
    "BLIND_CONVERSATION_SCENARIOS",
    "BilingualBlindPolicyTrialMeasurer",
    "BlindConversationScenario",
    "DeterministicNarratorPolicyProposer",
    "NarratorCostEstimator",
    "NarratorBackend",
    "pricing_narrator_cost_estimator",
]
