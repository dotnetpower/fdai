"""Shared one-shot orchestration for manual and scheduled question campaigns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.conversation.question_campaign import QuestionCampaignIdentity
from fdai.core.conversation.question_campaign_runner import (
    QuestionCampaignRunner,
    QuestionCampaignRunResult,
    QuestionGenerationInput,
)
from fdai.core.conversation.question_schedule import (
    QuestionCampaignPrerequisites,
    QuestionScheduleProfile,
    evaluate_question_campaign_due,
)
from fdai.core.conversation.question_universe import (
    GeneratedQuestionCase,
    GeneratedQuestionUniverse,
)


@dataclass(frozen=True, slots=True)
class QuestionCampaignWork:
    """Exact universe selection and sanitized descriptors for one campaign."""

    identity: QuestionCampaignIdentity
    universe: GeneratedQuestionUniverse
    cases: tuple[GeneratedQuestionCase, ...]
    generation_inputs: Mapping[str, QuestionGenerationInput]
    prior_questions: tuple[str, ...] = ()


class QuestionCampaignWorkProvider(Protocol):
    """Build exact-release campaign work without model or semantic execution."""

    async def build(self, *, question_budget: int, scheduled: bool) -> QuestionCampaignWork: ...


@dataclass(frozen=True, slots=True)
class OntologyQuestionCampaignJobResult:
    """Executed campaign result or pre-model scheduled skip/hold."""

    state: str
    reason: str
    campaign: QuestionCampaignRunResult | None
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.state not in {"completed", "held", "cancelled", "failed", "skipped"}:
            raise ValueError("ontology question campaign job state is invalid")
        if self.execution_authority:
            raise ValueError("ontology question campaign job has no execution authority")


class OntologyQuestionCampaignJob:
    """Route explicit and scheduled triggers into one bounded campaign package."""

    def __init__(
        self,
        *,
        work_provider: QuestionCampaignWorkProvider,
        runner: QuestionCampaignRunner,
    ) -> None:
        self._work_provider = work_provider
        self._runner = runner

    async def run_manual(self, *, question_budget: int = 20) -> OntologyQuestionCampaignJobResult:
        """Run one explicitly requested local campaign without a schedule profile."""

        if not 1 <= question_budget <= 100:
            raise ValueError("manual question campaign budget MUST be in [1, 100]")
        return await self._run_campaign(question_budget=question_budget, scheduled=False)

    async def run_scheduled(
        self,
        *,
        profile: QuestionScheduleProfile,
        prerequisites: QuestionCampaignPrerequisites,
        now: datetime,
        last_started_at: datetime | None,
    ) -> OntologyQuestionCampaignJobResult:
        """Run only after schedule and server-owned principal readiness pass."""

        decision = evaluate_question_campaign_due(
            profile=profile,
            prerequisites=prerequisites,
            now=now,
            last_started_at=last_started_at,
        )
        if not decision.due:
            return OntologyQuestionCampaignJobResult(
                state=decision.state,
                reason=decision.reason,
                campaign=None,
            )
        return await self._run_campaign(
            question_budget=profile.question_budget,
            scheduled=True,
        )

    async def _run_campaign(
        self,
        *,
        question_budget: int,
        scheduled: bool,
    ) -> OntologyQuestionCampaignJobResult:
        work = await self._work_provider.build(
            question_budget=question_budget,
            scheduled=scheduled,
        )
        if work.identity.question_budget != question_budget:
            raise ValueError("question campaign work budget does not match its trigger")
        if work.identity.question_universe_digest != work.universe.receipt.receipt_digest:
            raise ValueError("question campaign work binds a different universe")
        result = await self._runner.run(
            identity=work.identity,
            cases=work.cases,
            full_universe_case_ids=work.universe.receipt.case_ids,
            generation_inputs=work.generation_inputs,
            prior_questions=work.prior_questions,
        )
        state = {
            "completed": "completed",
            "held": "held",
            "cancelled": "cancelled",
            "failed": "failed",
            "running": "failed",
        }[result.state.value]
        return OntologyQuestionCampaignJobResult(
            state=state,
            reason=result.reason,
            campaign=result,
        )


def project_job_result(result: OntologyQuestionCampaignJobResult) -> dict[str, object]:
    """Project bounded machine output without question, answer, or provider payloads."""

    campaign = result.campaign
    return {
        "state": result.state,
        "reason": result.reason,
        "campaign_id": None if campaign is None else campaign.evaluation.campaign_id,
        "selected_case_count": (
            None if campaign is None else campaign.evaluation.selected_case_count
        ),
        "terminal_case_count": (
            None if campaign is None else campaign.evaluation.terminal_case_count
        ),
        "hard_zero_total": (None if campaign is None else campaign.evaluation.hard_zero.total),
        "release_evidence_eligible": (
            None if campaign is None else campaign.evaluation.release_evidence_eligible
        ),
        "execution_authority": False,
    }


__all__ = [
    "OntologyQuestionCampaignJob",
    "OntologyQuestionCampaignJobResult",
    "QuestionCampaignWork",
    "QuestionCampaignWorkProvider",
    "project_job_result",
]
