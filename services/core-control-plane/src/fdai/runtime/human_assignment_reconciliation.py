"""Bounded runtime worker for observation-only human assignment reconciliation."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from fdai.core.human_assignment import AssignmentReconciler

_LOGGER = logging.getLogger("fdai.human_assignment.reconciliation")


@dataclass(frozen=True, slots=True)
class AssignmentReconciliationWorker:
    reconciler: AssignmentReconciler
    interval_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("assignment reconciliation interval MUST be positive")

    async def run_once(self) -> int:
        return len(await self.reconciler.plan())

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
