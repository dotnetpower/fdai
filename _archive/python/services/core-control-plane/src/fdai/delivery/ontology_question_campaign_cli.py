"""One-shot CLI shell for an injected ontology question campaign job."""

from __future__ import annotations

import json
from datetime import datetime

from fdai.core.conversation.question_schedule import (
    QuestionCampaignPrerequisites,
    QuestionScheduleProfile,
)
from fdai.delivery.ontology_question_campaign import (
    OntologyQuestionCampaignJob,
    project_job_result,
)


async def run_once(
    *,
    job: OntologyQuestionCampaignJob,
    manual_question_budget: int | None = None,
    schedule_profile: QuestionScheduleProfile | None = None,
    prerequisites: QuestionCampaignPrerequisites | None = None,
    now: datetime | None = None,
    last_started_at: datetime | None = None,
) -> dict[str, object]:
    """Run one explicit or scheduled trigger through the shared job package."""

    manual = manual_question_budget is not None
    scheduled = schedule_profile is not None
    if manual == scheduled:
        raise ValueError("question campaign CLI requires exactly one trigger mode")
    if manual:
        result = await job.run_manual(question_budget=manual_question_budget or 20)
    else:
        if prerequisites is None or now is None or schedule_profile is None:
            raise ValueError("scheduled question campaign requires measured readiness and time")
        result = await job.run_scheduled(
            profile=schedule_profile,
            prerequisites=prerequisites,
            now=now,
            last_started_at=last_started_at,
        )
    return project_job_result(result)


def render_result(result: dict[str, object]) -> str:
    """Return one stable JSON line for local and deployed job logs."""

    return json.dumps(result, allow_nan=False, separators=(",", ":"), sort_keys=True)


__all__ = ["render_result", "run_once"]
