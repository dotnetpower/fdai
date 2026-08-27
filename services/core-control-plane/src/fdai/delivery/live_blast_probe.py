"""Production-capable Axis-E adapter over deployment-supplied neutral sources."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from math import isfinite

from fdai.shared.providers.blast_probe import (
    BlastSignalSource,
    LiveBlastProbe,
    ProbeFailureStreakSource,
    ProbeQuery,
    ProbeResult,
    ProbeVerdict,
)

_FAILURE_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class LiveBlastProbeAdapter(LiveBlastProbe):
    """Read a bounded live signal and fail toward a lower autonomy posture.

    The adapter performs no provider discovery and has no substrate mutation
    capability. Both sources are deployment-owned dependency-injection seams.
    A source failure returns ``active`` until the durable streak reaches the
    threshold, then returns ``overloaded``. A missing or malformed source
    response is never treated as ``quiet``.
    """

    signal_source: BlastSignalSource
    failure_streak_source: ProbeFailureStreakSource
    failure_threshold: int = _FAILURE_THRESHOLD

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold MUST be positive")

    async def measure(self, query: ProbeQuery) -> ProbeResult:
        """Return one bounded result, with timeout and streak handling."""
        try:
            streak = await asyncio.wait_for(
                self.failure_streak_source.get(query),
                timeout=query.deadline_seconds,
            )
            if isinstance(streak, bool) or not isinstance(streak, int) or streak < 0:
                raise ValueError("probe failure streak MUST be a non-negative integer")
            result = await asyncio.wait_for(
                self.signal_source.read(query),
                timeout=query.deadline_seconds,
            )
            _validate_result(result)
        except TimeoutError as exc:
            return await self._failure(
                query, "probe measurement timed out", timeout=True, cause=exc
            )
        except Exception as exc:
            return await self._failure(
                query,
                "probe measurement unavailable",
                timeout=False,
                cause=exc,
            )

        try:
            await asyncio.wait_for(
                self.failure_streak_source.record_success(query),
                timeout=query.deadline_seconds,
            )
        except Exception as exc:
            # A successful reading without a durable streak update is not
            # trustworthy for a future dispatch.
            return await self._failure(
                query,
                "probe failure streak source unavailable",
                timeout=False,
                cause=exc,
            )
        return result

    async def _failure(
        self,
        query: ProbeQuery,
        reason: str,
        *,
        timeout: bool,
        cause: BaseException,
    ) -> ProbeResult:
        try:
            streak = await asyncio.wait_for(
                self.failure_streak_source.record_failure(query),
                timeout=query.deadline_seconds,
            )
        except Exception:
            # The streak source is part of the safety decision. If it cannot
            # be read, use the most restrictive result rather than guessing.
            return ProbeResult(
                verdict=ProbeVerdict.OVERLOADED,
                reason=f"{reason}; failure streak unavailable",
                degraded=True,
            )
        if isinstance(streak, bool) or not isinstance(streak, int) or streak < 1:
            return ProbeResult(
                verdict=ProbeVerdict.OVERLOADED,
                reason=f"{reason}; failure streak malformed",
                degraded=True,
            )
        verdict = (
            ProbeVerdict.OVERLOADED if streak >= self.failure_threshold else ProbeVerdict.ACTIVE
        )
        detail = f"{reason}; consecutive failures={streak}"
        if timeout:
            detail = f"{detail}; timeout"
        del cause
        return ProbeResult(verdict=verdict, reason=detail, degraded=True)


def _validate_result(result: object) -> None:
    if not isinstance(result, ProbeResult):
        raise TypeError("probe source MUST return ProbeResult")
    if not isinstance(result.verdict, ProbeVerdict):
        raise TypeError("probe source returned an invalid verdict")
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
        for value in result.metrics.values()
    ):
        raise ValueError("probe source metrics MUST be finite numeric values")


__all__ = ["LiveBlastProbeAdapter"]
