"""Bounded revalidation worker for the deployment-owned operating-intent source.

Startup admission proves the pinned source was complete, current, and fresh *then*.
This worker re-proves it on a bounded cadence so authority tracks the source rather
than the process lifetime: a source that later leaves its effective interval, exceeds
its declared freshness, disappears from the deployment mount, or becomes unreachable
is quarantined, and a source that becomes valid again is re-admitted without a
restart. It never widens authority - it only re-runs the identical fail-closed
admission and refreshes or withdraws the bounded record consumers gate on.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.runtime.operating_intent_source import OperatingIntentSourceRuntime

_LOGGER = logging.getLogger("fdai.operating_intent_source.revalidation")


@dataclass(frozen=True, slots=True)
class OperatingIntentSourceRevalidationWorker:
    """Re-admit the pinned intent source on a bounded interval until shutdown."""

    runtime: OperatingIntentSourceRuntime

    @property
    def interval_seconds(self) -> int:
        return self.runtime.revalidation_seconds

    async def run_once(self, *, now: datetime | None = None) -> None:
        """Run one admission pass, refreshing or withdrawing the durable admission."""

        await self.runtime.admit(now=now if now is not None else datetime.now(UTC))

    async def run(self, stop: asyncio.Event) -> None:
        """Revalidate until supervised shutdown.

        Sleeps first so the pass that startup already performed is not immediately
        repeated. An unexpected failure is logged and retried on the next tick rather
        than ending the worker; the admission record self-expires, so a worker that
        cannot make progress withdraws authority on its own.
        """

        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
                return
            except TimeoutError:
                pass
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - retain the next bounded revalidation
                _LOGGER.exception("operating_intent_source_revalidation_failed")


__all__ = ["OperatingIntentSourceRevalidationWorker"]
