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

from fdai.core.conversation_assurance.pantheon_census import PantheonCensusCase
from fdai.core.conversation_assurance.pantheon_ledger import (
    PrivateJsonlLedger,
    private_marker_exists,
)
from fdai.core.conversation_assurance.pantheon_scorecard import PantheonTurnDiagnostic

_MAX_CHILD_QUESTIONS = 20


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

        if not cases:
            raise ValueError("a campaign series requires at least one case")
        series_id = _identity("series")
        results: list[CampaignRunResult] = []
        for start in range(0, len(cases), _MAX_CHILD_QUESTIONS):
            result = await self.run_child(
                cases[start : start + _MAX_CHILD_QUESTIONS],
                parent_series_id=series_id,
            )
            results.append(result)
            if result.state is not CampaignState.COMPLETED or result.evaluated != result.requested:
                break
        return tuple(results)

    def stop_requested(self) -> bool:
        return private_marker_exists(self._state_root / "STOP")


def _identity(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(16)}"


__all__ = [
    "CampaignHoldError",
    "CampaignRunResult",
    "CampaignState",
    "PantheonCampaignController",
    "PantheonCaseEvaluator",
]
