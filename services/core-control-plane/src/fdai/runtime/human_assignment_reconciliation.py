"""Bounded runtime worker for observation-only human assignment reconciliation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fdai.core.human_assignment import AssignmentReconciler
from fdai.core.human_assignment.readiness import HandoverReadinessPublisher

_LOGGER = logging.getLogger("fdai.human_assignment.reconciliation")


@dataclass(frozen=True, slots=True)
class AssignmentReconciliationWorker:
    reconciler: AssignmentReconciler
    interval_seconds: float = 300.0
    removal_artifact: Callable[[str, int], Awaitable[None]] | None = None
    readiness: HandoverReadinessPublisher | None = None
    scoped_observation: Callable[[], Awaitable[None]] | None = None

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("assignment reconciliation interval MUST be positive")

    async def run_once(self) -> int:
        """Observe a bounded page and retry independently verified review-only artifacts."""
        items = await self.reconciler.plan()
        for item in items:
            if item.next_step == "review_old_duty_removal" and self.removal_artifact is not None:
                try:
                    await self.removal_artifact(item.case_id, item.revision)
                except ValueError:
                    _LOGGER.warning(
                        "assignment_removal_artifact_held", extra={"case_id": item.case_id}
                    )
        if self.readiness is not None:
            await self.readiness.publish()
        if self.scoped_observation is not None:
            await self.scoped_observation()
        return len(items)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                observed = await self.run_once()
                _LOGGER.info("assignment_reconciliation_observed", extra={"cases": observed})
            except Exception:  # noqa: BLE001 - retain the next bounded observation
                _LOGGER.exception("assignment_reconciliation_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue


__all__ = ["AssignmentReconciliationWorker"]
