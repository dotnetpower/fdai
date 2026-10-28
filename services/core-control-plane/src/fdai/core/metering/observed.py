"""Fan one metering write out to best-effort observers.

The durable store stays the system of record for token usage and cost.
:class:`ObservedMeteringStore` wraps it so a development observer (for
example an LLM trace viewer) sees every recorded invocation too, without
the observer ever becoming a dependency of the hot path: an observer
failure is logged and swallowed, and the wrapped store is written first.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

from fdai.core.metering.records import LlmInvocation
from fdai.core.metering.sink import MeteringReader, MeteringSink

_log = logging.getLogger(__name__)


class _MeteringStore(MeteringSink, MeteringReader, Protocol):
    """A store that can both record and read back invocations."""


class ObservedMeteringStore:
    """Write to ``primary`` and mirror each record to ``observers``.

    Implements both :class:`MeteringSink` and :class:`MeteringReader`;
    reads delegate to ``primary`` only, so observers never affect cost
    rollups. A ``primary`` failure propagates to the caller (after the
    observers have still seen the call, since the model call did happen);
    an observer failure never does.
    """

    __slots__ = ("_observers", "_primary")

    def __init__(
        self,
        primary: _MeteringStore,
        observers: Sequence[MeteringSink],
    ) -> None:
        self._primary = primary
        self._observers = tuple(observers)

    async def record(self, invocation: LlmInvocation) -> None:
        try:
            await self._primary.record(invocation)
        finally:
            await self._observe(invocation)

    async def invocations(self) -> tuple[LlmInvocation, ...]:
        return await self._primary.invocations()

    async def _observe(self, invocation: LlmInvocation) -> None:
        for observer in self._observers:
            try:
                await observer.record(invocation)
            except Exception:
                _log.warning(
                    "metering_observer_failed",
                    extra={
                        "correlation_id": invocation.correlation_id,
                        "observer": type(observer).__name__,
                    },
                    exc_info=True,
                )


__all__ = ["ObservedMeteringStore"]
