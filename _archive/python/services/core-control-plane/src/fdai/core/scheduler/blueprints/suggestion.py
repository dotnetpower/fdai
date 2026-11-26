"""Off-path suggestion orchestration over audited turns and scheduler history."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from fdai.core.scheduler.blueprints.aggregator import AutomationBlueprintAggregator
from fdai.core.scheduler.blueprints.models import (
    AutomationBlueprintCandidate,
    AutomationBlueprintEvidence,
)
from fdai.core.scheduler.blueprints.review import AutomationBlueprintReviewService


class AutomationBlueprintEvidenceFeed(Protocol):
    async def completed_turns(self) -> Sequence[AutomationBlueprintEvidence]: ...

    async def scheduler_history(self) -> Sequence[AutomationBlueprintEvidence]: ...


class AutomationBlueprintSuggestionService:
    """Aggregate off-path evidence and submit only inert candidate records."""

    def __init__(
        self,
        *,
        feed: AutomationBlueprintEvidenceFeed,
        aggregator: AutomationBlueprintAggregator,
        review: AutomationBlueprintReviewService,
    ) -> None:
        self._feed = feed
        self._aggregator = aggregator
        self._review = review

    async def suggest(self, *, now: datetime) -> tuple[AutomationBlueprintCandidate, ...]:
        evidence = (*await self._feed.completed_turns(), *await self._feed.scheduler_history())
        candidates = self._aggregator.aggregate(evidence, now=now)
        return tuple([await self._review.submit(candidate) for candidate in candidates])


__all__ = ["AutomationBlueprintEvidenceFeed", "AutomationBlueprintSuggestionService"]
