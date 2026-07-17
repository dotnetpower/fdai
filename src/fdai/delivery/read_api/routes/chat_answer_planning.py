"""Shadow Answer Planning Round integration for Command Deck chat routes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Protocol, cast

from fdai.core.conversation.answer_plan import AnswerPlan, DiscussPolicy
from fdai.core.conversation.answer_planning import (
    AnswerPlanningConfig,
    AnswerPlanningProvider,
    AnswerPlanningResult,
    AnswerPlanningRoute,
    ContributorFailure,
    PlanningStatus,
    run_answer_planning_round,
    should_run_shadow_round,
)

_LOG = logging.getLogger(__name__)


class AnswerPlanningDelegate(AnswerPlanningProvider, Protocol):
    def route_answer_planning(self, prompt: str) -> AnswerPlanningRoute: ...


def compatible_planning_delegate(value: object | None) -> AnswerPlanningDelegate | None:
    if value is None:
        return None
    if not callable(getattr(value, "route_answer_planning", None)):
        return None
    if not callable(getattr(value, "contribute", None)):
        return None
    return cast(AnswerPlanningDelegate, value)


def start_shadow_answer_planning(
    *,
    prompt: str,
    plan: AnswerPlan,
    delegate: AnswerPlanningDelegate | None,
    config: AnswerPlanningConfig | None = None,
) -> tuple[AnswerPlan, asyncio.Task[AnswerPlanningResult] | None]:
    if delegate is None:
        return plan, None
    try:
        route = delegate.route_answer_planning(prompt)
    except Exception:  # noqa: BLE001 - routing metadata cannot block an answer
        return plan, asyncio.create_task(_failure_result("route_error"))
    eligible = should_run_shadow_round(prompt=prompt, plan=plan, route=route)
    if not eligible:
        return plan, None
    effective_plan = replace(plan, discuss=DiscussPolicy.SHADOW)
    return effective_plan, asyncio.create_task(
        run_answer_planning_round(
            prompt=prompt,
            plan=effective_plan,
            route=route,
            provider=delegate,
            config=config,
        )
    )


async def planning_metadata(
    task: asyncio.Task[AnswerPlanningResult] | None,
) -> dict[str, object] | None:
    if task is None:
        return None
    try:
        result = await task
        if result.status is not PlanningStatus.SKIPPED:
            _LOG.info(
                "answer_planning_round",
                extra={
                    "status": result.status.value,
                    "consulted_count": len(result.consulted_agents),
                    "contribution_count": len(result.contributions),
                    "failure_count": len(result.failures),
                    "elapsed_ms": result.elapsed_ms,
                    "unique_evidence_count": result.unique_evidence_count,
                    "duplicate_evidence_count": result.duplicate_evidence_count,
                    "covered_section_count": len(result.covered_sections),
                    "estimated_added_tokens": result.estimated_added_tokens,
                },
            )
        return result.to_dict()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - shadow metadata never blocks a supported answer
        return (await _failure_result("round_error")).to_dict()


async def cancel_planning(task: asyncio.Task[AnswerPlanningResult] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _failure_result(kind: str) -> AnswerPlanningResult:
    config = AnswerPlanningConfig()
    return AnswerPlanningResult(
        status=PlanningStatus.DEGRADED,
        primary_agent=None,
        consulted_agents=(),
        contributions=(),
        failures=(ContributorFailure(agent="planning", kind=kind),),
        elapsed_ms=0,
        unique_evidence_count=0,
        duplicate_evidence_count=0,
        conflicting_evidence_refs=(),
        covered_sections=(),
        estimated_added_tokens=0,
        budget=config,
        reason=kind,
    )


__all__ = [
    "AnswerPlanningDelegate",
    "cancel_planning",
    "compatible_planning_delegate",
    "planning_metadata",
    "start_shadow_answer_planning",
]
