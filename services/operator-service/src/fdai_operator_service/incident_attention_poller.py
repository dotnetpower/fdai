"""Process-local coalescing for the authoritative incident attention projection."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Protocol

from fdai_service_contracts import (
    IncidentAttentionProjection,
    IncidentAttentionQuery,
)


class IncidentAttentionReader(Protocol):
    """Read one authoritative incident attention snapshot."""

    async def incident_attention(
        self, query: IncidentAttentionQuery
    ) -> IncidentAttentionProjection | None: ...


class IncidentAttentionPoller:
    """Share one bounded read across concurrent SSE subscribers."""

    def __init__(
        self,
        read_model: IncidentAttentionReader,
        *,
        poll_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("incident attention poll interval MUST be positive")
        self._read_model = read_model
        self._poll_seconds = poll_seconds
        self._clock = clock
        self._lock = asyncio.Lock()
        self._projection: IncidentAttentionProjection | None = None
        self._next_poll_at = 0.0

    async def read(self, *, after_seq: int | None) -> IncidentAttentionProjection | None:
        """Return a newer projection while coalescing reads inside one poll interval."""

        async with self._lock:
            now = self._clock()
            if self._projection is None or now >= self._next_poll_at:
                self._projection = await self._read_model.incident_attention(
                    IncidentAttentionQuery(after_seq=None, limit=50)
                )
                self._next_poll_at = now + self._poll_seconds
            projection = self._projection
        if projection is None or (after_seq is not None and projection.sequence <= after_seq):
            return None
        return projection


__all__ = ["IncidentAttentionPoller", "IncidentAttentionReader"]
