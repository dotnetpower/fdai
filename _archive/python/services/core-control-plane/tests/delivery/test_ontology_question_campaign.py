"""Shared manual and scheduled ontology question job tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fdai.core.conversation.question_campaign import (
    QuestionCampaignState,
    QuestionCampaignTrigger,
)
from fdai.core.conversation.question_campaign_runner import QuestionCampaignRunResult
from fdai.core.conversation.question_perspectives import QuestionPerspective
from fdai.core.conversation.question_schedule import (
    QuestionCampaignPrerequisites,
    QuestionScheduleProfile,
    QuestionWorkloadPrincipalReceipt,
)
from fdai.delivery.ontology_question_campaign import (
    OntologyQuestionCampaignJob,
)
from fdai.delivery.ontology_question_campaign_cli import run_once

NOW = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


class _Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bool]] = []

    async def build(self, *, question_budget: int, scheduled: bool):
        self.calls.append((question_budget, scheduled))
        return SimpleNamespace(
            identity=SimpleNamespace(
                question_budget=question_budget,
                question_universe_digest="universe",
                trigger=(
                    QuestionCampaignTrigger.SCHEDULED
                    if scheduled
                    else QuestionCampaignTrigger.MANUAL
                ),
            ),
            universe=SimpleNamespace(
                receipt=SimpleNamespace(receipt_digest="universe", case_ids=("q:1",))
            ),
            cases=(SimpleNamespace(case_id="q:1"),),
            generation_inputs={"q:1": SimpleNamespace(case_id="q:1")},
            prior_questions=(),
        )


class _Runner:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, **_kwargs):
        self.calls += 1
        return QuestionCampaignRunResult(
            state=QuestionCampaignState.COMPLETED,
            reason="campaign_completed",
            evaluation=SimpleNamespace(
                campaign_id="qs:" + "a" * 64,
                selected_case_count=1,
                terminal_case_count=1,
                hard_zero=SimpleNamespace(total=0),
                release_evidence_eligible=True,
            ),
            attempts=(),
        )


def _profile() -> QuestionScheduleProfile:
    return QuestionScheduleProfile(
        profile_id="weekly-question-assurance",
        enabled=True,
        cron="0 2 * * 1",
        generation_profile="balanced-bilingual-v1",
        model_profile="question-generator-default",
        question_budget=20,
        time_budget_seconds=1_800,
        no_progress_seconds=300,
        token_budget=1_000,
        cost_budget_microusd=10_000,
        locales=("en", "ko"),
        perspectives=tuple(sorted(QuestionPerspective, key=lambda item: item.value)),
    )


def _ready() -> QuestionCampaignPrerequisites:
    return QuestionCampaignPrerequisites(
        previous_campaign_terminal=True,
        ontology_available=True,
        manifest_available=True,
        semantic_transport_ready=True,
        workload_principal=QuestionWorkloadPrincipalReceipt(
            principal_digest=DIGEST,
            role="reader",
            role_source="server-role-mapping",
            scope_digest=DIGEST,
            purpose="operations-review",
            authentication_evidence_digest=DIGEST,
            authenticated_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=30),
        ),
        generation_model_available=True,
        evidence_minimum_ready=True,
        budget_remaining=True,
        campaign_lock_available=True,
    )


async def test_manual_and_scheduled_use_the_same_runner() -> None:
    provider = _Provider()
    runner = _Runner()
    job = OntologyQuestionCampaignJob(
        work_provider=provider,  # type: ignore[arg-type]
        runner=runner,  # type: ignore[arg-type]
    )

    manual = await run_once(job=job, manual_question_budget=20)
    scheduled = await run_once(
        job=job,
        schedule_profile=_profile(),
        prerequisites=_ready(),
        now=NOW,
    )

    assert provider.calls == [(20, False), (20, True)]
    assert runner.calls == 2
    assert manual["state"] == "completed"
    assert scheduled["state"] == "completed"


async def test_scheduled_reader_hold_never_builds_or_runs_campaign() -> None:
    provider = _Provider()
    runner = _Runner()
    job = OntologyQuestionCampaignJob(
        work_provider=provider,  # type: ignore[arg-type]
        runner=runner,  # type: ignore[arg-type]
    )

    principal = _ready().workload_principal
    assert principal is not None
    result = await run_once(
        job=job,
        schedule_profile=_profile(),
        prerequisites=replace(
            _ready(),
            workload_principal=replace(principal, role="operator"),
        ),
        now=NOW,
    )

    assert result["state"] == "held"
    assert result["reason"] == "scheduled_principal_reader_mapping_unavailable"
    assert provider.calls == []
    assert runner.calls == 0
