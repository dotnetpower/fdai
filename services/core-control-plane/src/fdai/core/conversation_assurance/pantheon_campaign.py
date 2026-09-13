"""Explicit bounded campaign orchestration for Pantheon diagnostics."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from fdai.core.conversation_assurance.pantheon_census import PantheonCensus, PantheonCensusCase
from fdai.core.conversation_assurance.pantheon_ledger import (
    PrivateJsonlLedger,
    private_marker_exists,
)
from fdai.core.conversation_assurance.pantheon_scorecard import PantheonTurnDiagnostic

_MAX_CHILD_QUESTIONS = 20
_MAX_SERIES_QUESTIONS = 10_000


class CampaignState(StrEnum):
    COMPLETED = "completed"
    HELD = "held"
    STOPPED = "stopped"


class CampaignHoldError(RuntimeError):
    """Signal an external or unavailable measurement that must not be retried."""


class PantheonCaseEvaluator(Protocol):
    async def evaluate(
        self,
        case: PantheonCensusCase,
        *,
        campaign_id: str,
    ) -> PantheonTurnDiagnostic:
        """Measure one case once through the real conversation path."""


@dataclass(frozen=True, slots=True)
class CampaignRunResult:
    campaign_id: str
    state: CampaignState
    evaluated: int
    requested: int
    reason: str


@dataclass(frozen=True, slots=True)
class CampaignSeriesPlan:
    """Immutable bounded execution plan for one large assurance series."""

    question_count: int
    child_count: int
    child_sizes: tuple[int, ...]
    corpus_digest: str
    children: tuple[tuple[PantheonCensusCase, ...], ...]


def plan_campaign_series(
    cases: Sequence[PantheonCensusCase],
) -> CampaignSeriesPlan:
    """Validate and split at most 10,000 unique cases into 20-case children."""

    if not 1 <= len(cases) <= _MAX_SERIES_QUESTIONS:
        raise ValueError("a campaign series MUST contain between 1 and 10000 questions")
    case_ids = tuple(case.case_id for case in cases)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("a campaign series MUST contain unique case ids")
    children = tuple(
        tuple(cases[start : start + _MAX_CHILD_QUESTIONS])
        for start in range(0, len(cases), _MAX_CHILD_QUESTIONS)
    )
    return CampaignSeriesPlan(
        question_count=len(cases),
        child_count=len(children),
        child_sizes=tuple(len(child) for child in children),
        corpus_digest=PantheonCensus(
            version="campaign-series-plan-v1", cases=tuple(cases)
        ).content_digest,
        children=children,
    )


class PantheonCampaignController:
    """Run explicit child campaigns without acquiring execution authority."""

    def __init__(
        self,
        *,
        state_root: Path,
        evaluator: PantheonCaseEvaluator,
        timeout_seconds: float = 300.0,
        no_progress_seconds: float = 300.0,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("campaign timeout_seconds MUST be in [1, 300]")
        if not 1 <= no_progress_seconds <= 86_400:
            raise ValueError("campaign no_progress_seconds MUST be in [1, 86400]")
        self._state_root = state_root
        self._evaluator = evaluator
        self._timeout_seconds = timeout_seconds
        self._no_progress_seconds = no_progress_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._campaigns = PrivateJsonlLedger(state_root / "campaigns.jsonl")
        self._evaluations = PrivateJsonlLedger(state_root / "evaluations.jsonl")

    async def run_child(
        self,
        cases: Sequence[PantheonCensusCase],
        *,
        parent_series_id: str | None = None,
    ) -> CampaignRunResult:
        """Run at most 20 cases once each, stopping on the first hold."""

        if not 1 <= len(cases) <= _MAX_CHILD_QUESTIONS:
            raise ValueError("a child campaign MUST contain between 1 and 20 questions")
        campaign_id = _identity("campaign")
        started_at = self._now()
        last_progress = self._monotonic()
        self._campaigns.append(
            {
                "schema_version": "1.0.0",
                "event": "campaign_started",
                "campaign_id": campaign_id,
                "parent_series_id": parent_series_id,
                "requested": len(cases),
                "recorded_at": started_at.isoformat(),
            }
        )
        evaluated = 0
        state = CampaignState.COMPLETED
        reason = "question_budget_completed"
        for case in cases:
            if self.stop_requested():
                state = CampaignState.STOPPED
                reason = "stop_requested"
                break
            remaining_progress = self._no_progress_seconds - (self._monotonic() - last_progress)
            if remaining_progress <= 0:
                state = CampaignState.HELD
                reason = "no_progress_deadline"
                break
            try:
                diagnostic = await asyncio.wait_for(
                    self._evaluator.evaluate(case, campaign_id=campaign_id),
                    timeout=min(self._timeout_seconds, remaining_progress),
                )
            except TimeoutError:
                state = CampaignState.HELD
                reason = "measurement_timeout"
                break
            except CampaignHoldError as error:
                state = CampaignState.HELD
                reason = str(error)[:128] or "measurement_held"
                break
            self._evaluations.append(
                {
                    "schema_version": "1.0.0",
                    "campaign_id": campaign_id,
                    "parent_series_id": parent_series_id,
                    "recorded_at": self._now().isoformat(),
                    **diagnostic.to_dict(),
                }
            )
            evaluated += 1
            last_progress = self._monotonic()
        result = CampaignRunResult(
            campaign_id=campaign_id,
            state=state,
            evaluated=evaluated,
            requested=len(cases),
            reason=reason,
        )
        self._campaigns.append(
            {
                "schema_version": "1.0.0",
                "event": "campaign_completed",
                "campaign_id": campaign_id,
                "parent_series_id": parent_series_id,
                "state": state.value,
                "evaluated": evaluated,
                "requested": len(cases),
                "reason": reason,
                "recorded_at": self._now().isoformat(),
            }
        )
        return result

    async def run_series(
        self,
        cases: Sequence[PantheonCensusCase],
    ) -> tuple[CampaignRunResult, ...]:
        """Run sequential bounded children and stop after an incomplete child."""

        plan = plan_campaign_series(cases)
        series_id = _identity("series")
        self._campaigns.append(
            {
                "schema_version": "1.0.0",
                "event": "series_started",
                "parent_series_id": series_id,
                "question_count": plan.question_count,
                "child_count": plan.child_count,
                "child_sizes": list(plan.child_sizes),
                "corpus_digest": plan.corpus_digest,
                "recorded_at": self._now().isoformat(),
            }
        )
        results: list[CampaignRunResult] = []
        for child in plan.children:
            result = await self.run_child(
                child,
                parent_series_id=series_id,
            )
            results.append(result)
            if result.state is not CampaignState.COMPLETED or result.evaluated != result.requested:
                break
        self._campaigns.append(
            {
                "schema_version": "1.0.0",
                "event": "series_completed",
                "parent_series_id": series_id,
                "state": results[-1].state.value,
                "evaluated": sum(result.evaluated for result in results),
                "requested": plan.question_count,
                "completed_children": len(results),
                "planned_children": plan.child_count,
                "corpus_digest": plan.corpus_digest,
                "recorded_at": self._now().isoformat(),
            }
        )
        return tuple(results)

    def stop_requested(self) -> bool:
        return private_marker_exists(self._state_root / "STOP")


def _identity(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(16)}"


__all__ = [
    "CampaignHoldError",
    "CampaignRunResult",
    "CampaignSeriesPlan",
    "CampaignState",
    "PantheonCampaignController",
    "PantheonCaseEvaluator",
    "plan_campaign_series",
]
